import json
import logging
import subprocess
from array import array
from queue import Empty, Queue
from threading import Event, Lock, Thread
from time import sleep
from typing import Generator, Union

from . import extractor
from .opusreader import OggStream
from .utils.general import MISSING_TYPE, execute_in_thread

logger = logging.getLogger(__name__)

MISSING = MISSING_TYPE()


class EventManager:
    NEXT_TRACK = "next"
    QUEUE_ADD = "queueadd"
    NOW_PLAYING = "nowplaying"

    def __init__(self) -> None:
        logger.info("Initializing EventManager")

        self._event_queue: Queue = Queue()
        self._event_data: str = ""
        self._event_signal: Event = Event()
        self._shutdown_requested: bool = False

        self._event_manager_thread = Thread(
            target=self._manage_events, name="event_manager", daemon=True
        )
        self._event_manager_thread.start()

        logger.debug("EventManager initialized successfully")

    def watch(self) -> Generator[str, None, None]:
        logger.debug("Client connected to event stream")

        if "nowplaying" in self._event_data:
            logger.debug("Sending current now playing event to new client")
            yield self._event_data

        try:
            while not self._shutdown_requested:
                if self._event_signal.wait(timeout=1.0):
                    yield self._event_data
                    self._event_signal.clear()
        except GeneratorExit:
            logger.debug("Client disconnected from event stream")

    def _manage_events(self) -> None:
        logger.debug("Event manager thread started")

        while not self._shutdown_requested:
            try:
                try:
                    event_type, event_data = self._event_queue.get(timeout=1.0)
                except Empty:
                    continue

                self._event_data = (
                    f"event: {event_type}\ndata: {json.dumps(event_data)}\n\n"
                )
                self._event_signal.set()

                logger.debug(f"Processed event: {event_type}")

            except Exception as e:
                logger.error(f"Error processing event: {e}")
                sleep(0.1)  # prevent busy loop on repeated errors

        logger.debug("Event manager thread stopping")

    def add_event(self, event_type: str, data: dict) -> None:
        if self._shutdown_requested:
            return

        try:
            self._event_queue.put((event_type, data), timeout=1.0)
            logger.debug(f"Added event to queue: {event_type}")
        except Exception as e:
            logger.error(f"Failed to add event to queue: {e}")

    def shutdown(self) -> None:
        logger.info("Shutting down EventManager")
        self._shutdown_requested = True
        self._event_signal.set()


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
        "_skip_requested",
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
        self._queue_lock = Lock()  # add queue lock for thread safety

        # queues and state
        self._user_queue: list[Union[str, dict]] = []
        self._auto_queue: list[Union[str, dict]] = []
        self._skip_requested: bool = False
        self._now_playing: dict = {}

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
            if self._ffmpeg_process and self._ffmpeg_process != MISSING:
                try:
                    self._ffmpeg_process.terminate()
                    try:
                        self._ffmpeg_process.wait(timeout=5.0)  # pyright: ignore[reportCallIssue]
                    except subprocess.TimeoutExpired:
                        self._ffmpeg_process.kill()
                except Exception:
                    pass
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
    def now_playing(self) -> dict:
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

    def _populate_auto_queue(self) -> None:
        if self._stopped:
            return

        try:
            if not self._auto_queue and self._now_playing:
                logger.info("Populating auto queue with related tracks")
                self._auto_queue = extractor.get_youtube_related_tracks(
                    self._now_playing
                )
                logger.info(f"Added {len(self._auto_queue)} tracks to auto queue")
        except Exception as e:
            logger.error(f"Failed to populate auto queue: {e}")

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
            logger.error(f"Error adding track to queue: {e}")

    def add_track(self, url: str) -> None:
        if not self._stopped:
            execute_in_thread(self._add_to_queue, url, wait_for_result=False)

    def get_next_track(self) -> Union[str, dict, None]:
        if self._stopped:
            return None

        try:
            with self._queue_lock:
                if self._user_queue:
                    self._auto_queue.clear()
                    next_track = self._user_queue.pop(0)
                    logger.debug("Retrieved track from user queue")
                    return next_track

            if not self._auto_queue:
                self._populate_auto_queue()

            if self._auto_queue:
                next_track = self._auto_queue.pop(0)
                logger.debug("Retrieved track from auto queue")
                return next_track

            logger.debug("No tracks available in any queue")
            return None

        except Exception as e:
            logger.error(f"Error getting next track: {e}")
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
        logger.debug("Starting Ogg stream reader")

        if not self._ffmpeg_stdout:
            logger.error("FFmpeg stdout is not available")
            return

        try:
            pages_iterator = OggStream(self._ffmpeg_stdout).iter_pages()

            first_page = next(pages_iterator)
            if first_page.flag == 2:
                self._header_data += (
                    b"OggS" + first_page.header + first_page.segtable + first_page.data
                )

            second_page = next(pages_iterator)
            self._header_data += (
                b"OggS" + second_page.header + second_page.segtable + second_page.data
            )
            self._audio_header_event.set()

            logger.debug("Ogg stream headers processed")
            for page in pages_iterator:
                if self._stopped:
                    break

                try:
                    partial_data = array("b")
                    partial_data.frombytes(b"OggS" + page.header + page.segtable)

                    for packet_data, _ in page.iter_packets():
                        partial_data.frombytes(packet_data)
                    self._buffer_data = partial_data.tobytes()

                    self._audio_buffer_event.set()
                    self._audio_buffer_event.clear()

                except Exception as e:
                    logger.warning(f"Error processing audio page: {e}")

        except StopIteration:
            logger.info("Ogg stream ended")
        except Exception as e:
            if not self._stopped:
                logger.error(f"Error in Ogg stream reader: {e}")

        logger.debug("Ogg stream reader thread stopping")

    def _cleanup_track_process(self, process: subprocess.Popen) -> None:
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3.0)  # pyright: ignore[reportCallIssue]
                except subprocess.TimeoutExpired:
                    logger.warning("Track process did not terminate, killing")
                    process.kill()

            if process in self._track_processes:
                self._track_processes.remove(process)

        except Exception as e:
            logger.error(f"Error cleaning up track process: {e}")

    def _write_to_ffmpeg(self, queue: Queue, signal: Event) -> None:
        logger.debug("Starting FFmpeg stdin writer")

        while not self._stopped:
            try:
                try:
                    current_track = queue.get(timeout=1.0)
                except Empty:
                    continue

                if self._stopped:
                    break

                logger.info(
                    f"Starting playback: {current_track.get('title', 'Unknown')}"
                )
                self._event_manager.add_event(EventManager.NOW_PLAYING, current_track)

                ffmpeg_cmd = [
                    "ffmpeg",
                    "-reconnect",
                    "1",
                    "-reconnect_streamed",
                    "1",
                    "-reconnect_delay_max",
                    "5",
                    "-i",
                    current_track["url"],
                    "-threads",
                    "2",
                    "-b:a",
                    "128k",  # audio bitrate
                    "-ar",
                    "48000",  # sample rate
                    "-c:a",
                    "copy",
                    "-f",
                    "opus",  # output format
                    "-vn",  # no video
                    "-bufsize",
                    "64k",  # limit buffer size
                    "-loglevel",
                    "error",
                    "pipe:1",
                ]

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
                    if not audio_data or self._skip_requested or self._stopped:
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
                signal.set()
                self._skip_requested = False

                logger.info(
                    f"Finished playback: {current_track.get('title', 'Unknown')}"
                )

            except Exception as e:
                logger.error(f"Error in FFmpeg stdin writer: {e}")
                signal.set()

        logger.debug("FFmpeg stdin writer thread stopping")

    def _handle_queue(self) -> None:
        logger.debug("Starting queue handler")

        track_queue = Queue()
        stdin_writer_thread = Thread(
            target=self._write_to_ffmpeg,
            args=(track_queue, self._next_track_signal),
            name="ffmpeg_stdin_writer",
            daemon=True,
        )
        stdin_writer_thread.start()

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
                    next_track = extractor.extract_video_info(next_track)
                elif not next_track.get("process", False):
                    next_track = extractor.extract_video_info(next_track["webpage_url"])

                if not next_track:
                    logger.warning("Failed to process track, skipping")
                    continue

                if self._stopped:
                    break

                self._now_playing = next_track
                track_queue.put(self._now_playing)

                logger.info(
                    f"Queued track for playback: {next_track.get('title', 'Unknown')}"
                )

                self._next_track_signal.wait()

            except Exception as e:
                logger.error(f"Error in queue handler: {e}")
                sleep(0.1)  # prevent busy loop

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

    def _skip_current_track(self) -> None:
        if self._stopped:
            return

        try:
            logger.info("Skipping current track")
            next_track = self.get_next_track()
            if next_track:
                with self._queue_lock:
                    self._user_queue.insert(0, next_track)
            self._skip_requested = True
        except Exception as e:
            logger.error(f"Error skipping track: {e}")

    def skip_track(self) -> None:
        if not self._stopped:
            execute_in_thread(self._skip_current_track, wait_for_result=False)

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

            self._event_manager.shutdown()

            for process in self._track_processes[:]:
                self._cleanup_track_process(process)

            try:
                if self._ffmpeg_process and self._ffmpeg_process != MISSING:
                    if self._ffmpeg_stdin:
                        self._ffmpeg_stdin.close()
                    if self._ffmpeg_stdout:
                        self._ffmpeg_stdout.close()

                    self._ffmpeg_process.terminate()
                    try:
                        self._ffmpeg_process.wait(timeout=5.0)  # pyright: ignore[reportCallIssue]
                    except subprocess.TimeoutExpired:
                        logger.warning("Main FFmpeg process did not terminate, killing")
                        self._ffmpeg_process.kill()
                    logger.info("FFmpeg process terminated successfully")
            except Exception as e:
                logger.error(f"Error terminating FFmpeg process: {e}")

            # signal all events to unblock waiting threads
            self._audio_buffer_event.set()
            self._audio_header_event.set()
            self._next_track_signal.set()

            logger.info("AudioQueueManager shutdown complete")
