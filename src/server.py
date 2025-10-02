from __future__ import annotations

import contextlib
import json
import logging
import subprocess
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread
from time import sleep
from typing import TYPE_CHECKING

from . import extractor
from .opusreader import OggStream
from .utils.general import MISSING_TYPE, execute_in_thread

if TYPE_CHECKING:
    from typing import Generator

    from .models.extract import BaseExtractModel, ProcessedExtractModel
    from .opusreader import OggPage
MISSING = MISSING_TYPE()

logger = logging.getLogger(__name__)


class EventManager:
    NEXT_TRACK = "next"
    QUEUE_ADD = "queueadd"
    NOW_PLAYING = "nowplaying"
    SHUTDOWN = "shutdown"

    __slots__ = (
        "_event_queue",
        "_shutdown_requested",
        "_user_list",
        "_event_manager_thread",
    )

    def __init__(self) -> None:
        logger.info("Initializing EventManager")

        self._event_queue: Queue = Queue()
        self._shutdown_requested: bool = False
        self._user_list: set[Queue] = set()

        self._event_manager_thread = Thread(
            target=self._manage_events, name="event_manager", daemon=True
        )
        self._event_manager_thread.start()

        logger.debug("EventManager initialized successfully")

    def watch(self) -> Generator[str, None, None]:
        logger.debug("Client connected to event stream")

        event_queue: Queue[str] = Queue()
        self._user_list.add(event_queue)
        try:
            while not self._shutdown_requested:
                with contextlib.suppress(Empty):
                    event = event_queue.get(timeout=1.0)
                    if event == EventManager.SHUTDOWN:
                        break
                    yield event

        except GeneratorExit:
            logger.debug("Client disconnected from event stream")

        finally:
            self._user_list.discard(event_queue)

    def _manage_events(self) -> None:
        logger.debug("Event manager thread started")

        while not self._shutdown_requested:
            try:
                try:
                    event_type, event_data = self._event_queue.get(timeout=1.0)
                except Empty:
                    continue

                event_data = f"event: {event_type}\ndata: {json.dumps(event_data)}\n\n"
                for user_queue in list(self._user_list):
                    with contextlib.suppress(Full):
                        user_queue.put_nowait(event_data)

                logger.debug(f"Processed event: {event_type}")

            except Exception as e:
                logger.error(f"Error processing event: {e}", exc_info=True)
                sleep(0.1)  # prevent busy loop on repeated errors

        logger.debug("Event manager thread stopping")

    def add_event(self, event_type: str, data: BaseExtractModel) -> None:
        if self._shutdown_requested:
            return

        try:
            self._event_queue.put((event_type, data), timeout=1.0)
            logger.debug(f"Added event to queue: {event_type}")
        except Exception as e:
            logger.error(f"Failed to add event to queue: {e}", exc_info=True)

    def shutdown(self) -> None:
        logger.info("Shutting down EventManager")
        self._shutdown_requested = True
        self._event_queue.put((EventManager.SHUTDOWN, None))
        self._user_list.clear()


class AudioQueueManager:
    """
    Manages audio queue, streaming, and playback for the PyLive application.

    This class handles:
    - Audio queue management (user queue and auto-generated queue)
    - FFmpeg process management for audio streaming
    - Ogg stream processing
    - Event broadcasting for queue changes
    """

    __slots__ = (
        "_stopped",
        "_shutdown_lock",
        "_queue_lock",
        "_user_queue",
        "_auto_queue",
        "_track_history",
        "_skip_event",
        "_audio_buffer_event",
        "_audio_header_event",
        "_now_playing",
        "_header_data",
        "_buffer_data",
        "_next_track_signal",
        "_ffmpeg_process",
        "_ffmpeg_stdout",
        "_ffmpeg_stdin",
        "_audio_reader_thread",
        "_queue_handler_thread",
        "_event_manager",
        "_track_processes",
    )

    def __init__(self):
        logger.info("Initializing AudioQueueManager")

        self._stopped: bool = False
        self._shutdown_lock = Lock()
        self._queue_lock = Lock()

        # queues and state
        self._user_queue: list[str | BaseExtractModel] = []
        self._auto_queue: list[BaseExtractModel] = []
        self._track_history: Queue[str] = Queue(maxsize=50)
        self._skip_event: Event = Event()
        self._now_playing: ProcessedExtractModel | None = None

        # audio components
        self._audio_header_event = Event()
        self._header_data: bytes = b""
        self._audio_buffer_event = Event()
        self._buffer_data: bytes = b""

        # track management
        self._next_track_signal = Event()
        self._track_processes: list[subprocess.Popen] = []

        # event management
        self._event_manager = EventManager()

        # process
        self._ffmpeg_process = MISSING
        self._ffmpeg_stdout = None
        self._ffmpeg_stdin = None

        try:
            self._ffmpeg_process = self._create_main_ffmpeg_process()
            self._ffmpeg_stdout = self._ffmpeg_process.stdout
            self._ffmpeg_stdin = self._ffmpeg_process.stdin
            logger.info("FFmpeg main process initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize FFmpeg process: {e}")
            # ensure cleanup if partial initialization occurred
            if isinstance(self._ffmpeg_process, subprocess.Popen):
                with contextlib.suppress(Exception):
                    self._ffmpeg_process.terminate()
                    try:
                        self._ffmpeg_process.wait(timeout=5.0)
                    except subprocess.TimeoutExpired:
                        self._ffmpeg_process.kill()

            self._ffmpeg_process = MISSING
            self._ffmpeg_stdout = None
            self._ffmpeg_stdin = None

        self._audio_reader_thread = Thread(
            target=self._read_ogg_stream, name="ogg_stream_reader", daemon=True
        )
        self._queue_handler_thread = Thread(
            target=self._handle_queue, name="queue_handler", daemon=True
        )

        self._queue_handler_thread.start()
        self._audio_reader_thread.start()

        logger.info("AudioQueueManager initialized successfully")

    @property
    def stopped(self) -> bool:
        return self._stopped

    @property
    def audio_duration(self) -> float:
        if not isinstance(self._now_playing, dict):
            return 0.0
        return self._now_playing.get("duration", 0.0)

    @property
    def now_playing(self) -> ProcessedExtractModel | None:
        return self._now_playing

    @property
    def queue(self) -> list:
        with self._queue_lock:
            return self._user_queue.copy()

    @property
    def auto_queue(self) -> list:
        with self._queue_lock:
            return self._auto_queue.copy()

    @property
    def event_queue(self) -> EventManager:
        return self._event_manager

    def _get_history_ids(self) -> set[str]:
        with self._track_history.mutex:
            return set(self._track_history.queue)

    def _add_to_history(self, track_id: str) -> None:
        if self._track_history.full():
            with contextlib.suppress(Empty):
                self._track_history.get_nowait()  # remove oldest
        try:
            self._track_history.put_nowait(track_id)
            logger.debug(f"Added track ID to history: {track_id}")
        except Exception as e:
            logger.warning(f"Failed to add track to history: {e}")

    def _filter_duplicate_tracks(
        self, tracks: list[BaseExtractModel]
    ) -> list[BaseExtractModel]:
        if not tracks:
            return []

        history_ids = self._get_history_ids()
        filtered_tracks = []

        for track in tracks:
            track_id = track.get("id")
            if track_id and track_id not in history_ids:
                filtered_tracks.append(track)
            else:
                logger.debug(
                    f"Skipping duplicate track: {track.get('title', 'Unknown')} (ID: {track_id})"
                )

        logger.debug(
            f"Filtered {len(tracks) - len(filtered_tracks)} duplicate tracks from auto queue"
        )
        return filtered_tracks

    def _populate_auto_queue(self) -> None:
        if self._stopped:
            return

        try:
            if not self._auto_queue and self._now_playing:
                logger.info("Populating auto queue with related tracks")
                related_tracks = (
                    extractor.get_youtube_music_related_tracks(self._now_playing)
                    or extractor.get_youtube_related_tracks(self._now_playing)
                    or []
                )

                # filter out tracks already in history
                filtered_tracks = self._filter_duplicate_tracks(related_tracks)
                self._auto_queue.extend(filtered_tracks)
                logger.info(
                    f"Added {len(filtered_tracks)} unique tracks to auto queue (filtered {len(related_tracks) - len(filtered_tracks)} duplicates)"
                )
        except Exception as e:
            logger.error(f"Failed to populate auto queue: {e}", exc_info=True)

    def _add_to_queue(self, url: str) -> None:
        if self._stopped:
            return

        try:
            logger.info(f"Processing URL for queue: {url}")
            track_info = extractor.extract_video_info(url, process=False)

            if track_info:
                with self._queue_lock:
                    self._user_queue.append(track_info)
                self._event_manager.add_event(EventManager.QUEUE_ADD, track_info)
                logger.info(
                    f"Successfully added track to queue: {track_info.get('title', 'Unknown')}"
                )
            else:
                logger.warning(f"Failed to extract track information from URL: {url}")

        except Exception as e:
            logger.error(f"Error adding track to queue: {e}", exc_info=True)

    def add_track(self, url: str) -> None:
        if not self._stopped:
            execute_in_thread(self._add_to_queue, url, wait_for_result=False)

    def get_next_track(self) -> str | BaseExtractModel | None:
        if self._stopped:
            return None

        try:
            with self._queue_lock:
                if self._user_queue:
                    self._auto_queue.clear()
                    next_track = self._user_queue.pop(0)
                    logger.debug("Retrieved track from user queue")
                    return next_track

            if not self._auto_queue and self._now_playing:
                self._populate_auto_queue()

            if self._auto_queue:
                next_track = self._auto_queue.pop(0)
                logger.debug("Retrieved track from auto queue")
                return next_track

            logger.debug("No tracks available in any queue")
            return None

        except Exception as e:
            logger.error(f"Error getting next track: {e}", exc_info=True)
            return None

    @staticmethod
    def _create_main_ffmpeg_process() -> subprocess.Popen:
        logger.debug("Creating main FFmpeg process")

        ffmpeg_cmd = [
            "ffmpeg",
            "-re",  # real-time
            "-i",
            "-",  # stdin
            "-threads",
            "2",
            "-c:a",
            "copy",
            "-f",
            "opus",
            "-loglevel",
            "error",
            "pipe:1",  # stdout
        ]

        try:
            process = subprocess.Popen(
                ffmpeg_cmd,
                stdout=subprocess.PIPE,
                stdin=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            logger.debug("Main FFmpeg process created successfully")
            return process
        except Exception as e:
            logger.error(f"Failed to create FFmpeg process: {e}")
            raise

    def _read_ogg_stream(self) -> None:
        logger.debug("starting ogg stream reader")

        if not self._ffmpeg_stdout:
            logger.error("ffmpeg stdout is not available, cannot read ogg stream")
            return

        try:
            pages_iterator: Generator[OggPage, None, None] = OggStream(
                self._ffmpeg_stdout
            ).iter_pages()

            try:
                first_page = next(pages_iterator)
                if first_page.flag != 2:
                    logger.warning("first ogg page is not a 'Beginning of Stream' page")
                second_page = next(pages_iterator)

                header1 = (
                    b"OggS" + first_page.header + first_page.segtable + first_page.data
                )
                header2 = (
                    b"OggS"
                    + second_page.header
                    + second_page.segtable
                    + second_page.data
                )
                self._header_data = header1 + header2
                self._audio_header_event.set()
                logger.debug("ogg stream headers processed")

            except StopIteration:
                logger.error(
                    "ogg stream ended before headers could be read. stream is likely empty or corrupt"
                )
                return

            for page in pages_iterator:
                if self._stopped:
                    break

                try:
                    page_header = b"OggS" + page.header + page.segtable
                    page_payload = b"".join(
                        packet_data for packet_data, _ in page.iter_packets()
                    )
                    self._buffer_data = page_header + page_payload

                    self._audio_buffer_event.set()
                    self._audio_buffer_event.clear()

                except Exception as e:
                    logger.warning(
                        f"error processing ogg audio page: {e}", exc_info=True
                    )

        except StopIteration:
            logger.info("ogg stream ended")
        except Exception as e:
            if not self._stopped:
                logger.error(f"error in ogg stream reader: {e}", exc_info=True)

        logger.debug("ogg stream reader thread stopping")

    def _cleanup_track_process(self, process: subprocess.Popen) -> None:
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    logger.warning("Track process did not terminate, killing")
                    process.kill()

            if process in self._track_processes:
                self._track_processes.remove(process)

        except Exception as e:
            logger.error(f"Error cleaning up track process: {e}", exc_info=True)

    @staticmethod
    def _build_track_ffmpeg_command(track: ProcessedExtractModel) -> list[str]:
        base_command = [
            "ffmpeg",
            "-reconnect",
            "1",
            "-reconnect_streamed",
            "1",
            "-reconnect_delay_max",
            "5",
            "-i",
            track["url"],
            "-threads",
            "2",
        ]

        # if audio needs re-encoding, apply proper codec and settings.
        # otherwise, copy the stream directly for better performance.
        if track.get("need_reencode"):
            audio_options = [
                "-c:a",
                "libopus",  # re-encode to opus
                "-b:a",
                "128k",  # audio bitrate
                "-ar",
                "48000",  # sample rate
            ]
        else:
            audio_options = [
                "-c:a",
                "copy",  # stream copy
            ]

        final_command = [
            *base_command,
            *audio_options,
            "-f",
            "opus",  # output format
            "-vn",  # no video
            "-bufsize",
            "64k",  # limit buffer size
            "-loglevel",
            "error",
            "pipe:1",
        ]

        return final_command

    def _write_to_ffmpeg(
        self, queue: Queue[ProcessedExtractModel], signal: Event
    ) -> None:
        logger.debug("Starting FFmpeg stdin writer")

        while not self._stopped:
            try:
                try:
                    track = queue.get(timeout=1.0)
                except Empty:
                    continue

                if self._stopped:
                    break

                logger.info(f"Starting playback: {track.get('title', 'Unknown')}")
                self._event_manager.add_event(EventManager.NOW_PLAYING, track)

                # add current track to history
                track_id = track.get("id")
                if track_id:
                    self._add_to_history(track_id)

                ffmpeg_cmd = self._build_track_ffmpeg_command(track)
                track_process = subprocess.Popen(
                    ffmpeg_cmd,
                    stdout=subprocess.PIPE,
                    stdin=None,
                    stderr=subprocess.PIPE,
                )
                self._track_processes.append(track_process)

                while not self._stopped:
                    if track_process.poll() is not None:
                        break

                    if track_process.stdout is None:
                        logger.error("Track process stdout is None")
                        break

                    audio_data = track_process.stdout.read(4096)
                    if not audio_data or self._skip_event.is_set() or self._stopped:
                        break

                    if self._ffmpeg_stdin and not self._stopped:
                        try:
                            self._ffmpeg_stdin.write(audio_data)
                            self._ffmpeg_stdin.flush()
                        except (BrokenPipeError, OSError) as e:
                            logger.error(f"Error writing to FFmpeg stdin: {e}")
                            break
                    sleep(0.001)

                self._cleanup_track_process(track_process)
                logger.info(f"Finished playback: {track.get('title', 'Unknown')}")
                self._skip_event.clear()
                signal.set()

            except Exception as e:
                logger.error(f"Error in FFmpeg stdin writer: {e}", exc_info=True)
                self._skip_event.clear()
                signal.set()

        logger.debug("FFmpeg stdin writer thread stopping")

    def _handle_queue(self) -> None:
        logger.debug("starting queue handler")

        track_queue: Queue[ProcessedExtractModel] = Queue()
        stdin_writer_thread = Thread(
            target=self._write_to_ffmpeg,
            args=(track_queue, self._next_track_signal),
            name="ffmpeg_stdin_writer",
            daemon=True,
        )
        stdin_writer_thread.start()

        error_count = 0
        max_error = 5

        while not self._stopped:
            try:
                self._next_track_signal.clear()
                next_track = self.get_next_track()

                if not next_track:
                    if not self._stopped:
                        logger.debug("No tracks available, waiting...")
                        sleep(1)
                    continue

                if isinstance(next_track, str):
                    processed_track = extractor.extract_video_info(next_track)
                else:
                    processed_track = extractor.extract_video_info(
                        next_track["webpage_url"]
                    )

                if not processed_track:
                    logger.warning("Failed to process track, skipping")
                    continue

                if self._stopped:
                    break

                self._now_playing = processed_track
                track_queue.put(self._now_playing)

                logger.info(
                    f"Queued track for playback: {processed_track.get('title', 'Unknown')}"
                )
                self._next_track_signal.wait()
                error_count = 0

            except Exception as e:
                error_count += 1
                logger.error(f"Error in queue handler: {e}", exc_info=True)
                if error_count >= max_error:
                    logger.error("Too many consecutive errors, stopping queue handler")
                    break

                sleep(min(0.1 * error_count, 2.0))

        logger.debug("Queue handler thread stopping")

    def wait_for_header(self) -> bytes:
        logger.debug("Waiting for stream header data")

        if not self._audio_header_event.wait(timeout=30.0):
            logger.error("Timeout waiting for stream header data")
            raise TimeoutError("Header data not available within timeout period")

        if not self._header_data or not self.is_alive() or self._stopped:
            logger.error("No header data available after waiting")
            raise InterruptedError("Stream not available")

        logger.debug("Stream header data available")
        return self._header_data

    @property
    def buffer(self) -> bytes:
        if not self._buffer_data and self.is_alive() or self._stopped:
            raise InterruptedError("Buffer not available")
        return self._buffer_data

    @property
    def event(self) -> Event:
        return self._audio_buffer_event

    def skip_track(self) -> None:
        if not self._stopped:
            self._skip_event.set()

    def is_alive(self) -> bool:
        return (
            self._audio_reader_thread.is_alive() if self._audio_reader_thread else False
        ) and not self._stopped

    def shutdown(self) -> None:
        """Gracefully shutdown the audio queue manager."""
        with self._shutdown_lock:
            if self._stopped:
                return

            logger.info("Shutting down AudioQueueManager")
            self._stopped = True
            self._skip_event.set()
            self._event_manager.shutdown()

            for process in self._track_processes[:]:
                self._cleanup_track_process(process)

            try:
                if isinstance(self._ffmpeg_process, subprocess.Popen):
                    if self._ffmpeg_stdin:
                        with contextlib.suppress(OSError):
                            self._ffmpeg_stdin.close()
                    if self._ffmpeg_stdout:
                        self._ffmpeg_stdout.close()

                    self._ffmpeg_process.terminate()
                    try:
                        self._ffmpeg_process.wait(timeout=5.0)
                    except subprocess.TimeoutExpired:
                        logger.warning("Main FFmpeg process did not terminate, killing")
                        self._ffmpeg_process.kill()
                    logger.info("FFmpeg process terminated successfully")
            except Exception as e:
                logger.error(f"Error terminating FFmpeg process: {e}", exc_info=True)

            # signal all events to unblock waiting threads
            self._audio_buffer_event.set()
            self._audio_header_event.set()
            self._next_track_signal.set()

            logger.info("AudioQueueManager shutdown complete")
