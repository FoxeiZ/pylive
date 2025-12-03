from __future__ import annotations

import asyncio
import contextlib
import logging
import struct
from collections import OrderedDict
from typing import TYPE_CHECKING

from ..extractor import extract_video_info
from ..models.extract import BaseExtractModel
from ..utils.validator import validate_typed_dict

if TYPE_CHECKING:
    from typing import AsyncGenerator, Callable, Coroutine, Iterable

    from ..models.extract import ProcessedExtractModel

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


class BoundedHistory[T]:
    """bounded history with O(1) membership checks."""

    def __init__(self, maxlen: int) -> None:
        self._maxlen = maxlen
        self._data: OrderedDict[T, None] = OrderedDict()

    def add(self, item: T) -> None:
        """add an item to the history, evicting oldest if at capacity."""
        if item in self._data:
            return  # already exists, skip duplicate

        if len(self._data) >= self._maxlen:
            self._data.popitem(last=False)  # remove oldest (FIFO)

        self._data[item] = None
        self._data.move_to_end(item, last=True)

    def __setitem__(self, key: T, value: None) -> None:
        self.add(key)

    def __delitem__(self, key: T) -> None:
        del self._data[key]

    def __contains__(self, item: T) -> bool:
        return item in self._data

    def __len__(self) -> int:
        return len(self._data)

    def __iter__(self):
        return iter(self._data)

    def clear(self) -> None:
        self._data.clear()


class AsyncOggPage:
    __slots__ = (
        "header",
        "flag",
        "gran_pos",
        "serial",
        "pagenum",
        "crc",
        "segnum",
        "segtable",
        "data",
    )

    def __init__(
        self,
        header: bytes,
        flag: int,
        gran_pos: int,
        serial: int,
        pagenum: int,
        crc: int,
        segnum: int,
        segtable: bytes,
        data: bytes,
    ) -> None:
        self.header = header
        self.flag = flag
        self.gran_pos = gran_pos
        self.serial = serial
        self.pagenum = pagenum
        self.crc = crc
        self.segnum = segnum
        self.segtable = segtable
        self.data = data

    def iter_packets(self):
        packetlen = offset = 0
        partial = True

        for seg in self.segtable:
            if seg == 255:
                packetlen += 255
                partial = True
            else:
                packetlen += seg
                yield self.data[offset : offset + packetlen], True
                offset += packetlen
                packetlen = 0
                partial = False

        if partial:
            yield self.data[offset:], False

    def to_bytes(self) -> bytes:
        """convert the page to its raw byte representation."""
        page_header = b"OggS" + self.header + self.segtable
        page_payload = b"".join(packet_data for packet_data, _ in self.iter_packets())
        return page_header + page_payload


class OggStreamProcessor:
    _HEADER_STRUCT = struct.Struct("<xBQIIIB")
    _HEADER_SIZE = _HEADER_STRUCT.size

    async def read_page(self, stdout: asyncio.StreamReader) -> AsyncOggPage | None:
        try:
            head = await stdout.readexactly(4)
            if head != b"OggS":
                if not head:
                    return None
                raise ValueError("invalid ogg header magic")

            header_data = await stdout.readexactly(self._HEADER_SIZE)

            (
                flag,
                gran_pos,
                serial,
                pagenum,
                crc,
                segnum,
            ) = self._HEADER_STRUCT.unpack(header_data)
            segtable = await stdout.readexactly(segnum)
            bodylen = sum(segtable)
            body_data = await stdout.readexactly(bodylen)

            return AsyncOggPage(
                header=header_data,
                flag=flag,
                gran_pos=gran_pos,
                serial=serial,
                pagenum=pagenum,
                crc=crc,
                segnum=segnum,
                segtable=segtable,
                data=body_data,
            )

        except asyncio.IncompleteReadError:
            logger.debug("ogg stream ended (incomplete read)")
            return None

        except asyncio.CancelledError:
            raise

        except Exception as e:
            logger.error(f"error reading ogg page: {e}", exc_info=True)
            return None

    async def iter_pages(
        self, stdout: asyncio.StreamReader, stop_check: asyncio.Event | None = None
    ) -> AsyncGenerator[AsyncOggPage, None]:
        try:
            while True:
                if stop_check and stop_check.is_set():
                    break

                page = await self.read_page(stdout)
                if not page:
                    break
                yield page

        except asyncio.CancelledError:
            raise

        except Exception as e:
            logger.error(f"error in async ogg page iteration: {e}", exc_info=True)


class AudioStreamController:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        self._lock = asyncio.Lock()
        self._stopped = asyncio.Event()
        self._shutdown_requested = False

        self._queue: asyncio.Queue[BaseExtractModel] = asyncio.Queue()
        self._auto_queue: asyncio.Queue[BaseExtractModel] = asyncio.Queue()
        self._track_history: BoundedHistory[str] = BoundedHistory(maxlen=100)
        self._now_playing: ProcessedExtractModel | None = None

        self._stderr_task: asyncio.Task[None] | None = None
        self._handle_queue_task: asyncio.Task[None] | None = None
        self._active_forward_tasks: set[asyncio.Task[None]] = set()

        self._ffmpeg_process: asyncio.subprocess.Process | None = None
        self._feed_process: asyncio.subprocess.Process | None = None
        self._silence_process: asyncio.subprocess.Process | None = None

        self._cached_header: bytes | None = None
        self._header_expired: bool = True

        self._audio_buffer_event = asyncio.Event()
        self._buffer_data: bytes = b""

    async def _spawn_ffmpeg_process(
        self,
        cmd: Iterable[str],
        *,
        reason: str = "no reason",
        stdin: int | None = asyncio.subprocess.PIPE,
        stdout: int | None = asyncio.subprocess.PIPE,
        stderr: int | None = asyncio.subprocess.PIPE,
    ) -> asyncio.subprocess.Process:
        """spawn the ffmpeg process"""
        logger.debug(f"spawning ffmpeg process, reason: {reason}")

        process = await asyncio.create_subprocess_exec(
            *cmd, stdin=stdin, stdout=stdout, stderr=stderr
        )
        return process

    async def _stop_ffmpeg_process(
        self, process: asyncio.subprocess.Process, timeout: float = 5.0
    ) -> None:
        """stop a given ffmpeg process."""
        if not process:
            return

        _io_errors = (BrokenPipeError, ConnectionResetError, OSError, ValueError)

        if process.stdin:
            with contextlib.suppress(*_io_errors):
                process.stdin.close()
                await process.stdin.wait_closed()

        with contextlib.suppress(ProcessLookupError, OSError):
            process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            with contextlib.suppress(ProcessLookupError, OSError):
                process.kill()
            await process.wait()

        if process.stdout:
            with contextlib.suppress(*_io_errors):
                await process.stdout.read()
        if process.stderr:
            with contextlib.suppress(*_io_errors):
                await process.stderr.read()

    async def _generate_header(
        self,
        track: ProcessedExtractModel | None = None,
        extra: dict[str, str | int] | None = None,
    ) -> bytes:
        """generate the Opus header for a given track."""
        logger.info("generating Opus header for track")
        if not extra:
            meta_args = {}
        else:
            meta_args = extra

        if track:
            for key in ("title", "artist", "album", "comment"):
                val = None
                if isinstance(track, dict):
                    val = track.get(key)
                else:
                    val = getattr(track, key, None)
                if val:
                    meta_args[key] = val

        cmd: list[str] = [
            "ffmpeg",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=stereo",
            "-af",
            "aformat=sample_fmts=s16",
            "-t",
            "1",
        ]

        if meta_args:
            cmd = [*cmd, *[f"-metadata {key}={val}" for key, val in meta_args.items()]]

        cmd.extend(
            [
                "-vn",
                "-c:a",
                "libopus",
                "-frames:a",
                "0",
                "-f",
                "opus",
                "-loglevel",
                "error",
                "pipe:1",
            ]
        )

        proc: asyncio.subprocess.Process | None = None
        proc = await self._spawn_ffmpeg_process(
            cmd, reason="generate header", stdin=None
        )

        if not proc.stdout:
            raise ValueError("ffmpeg header generator has no stdout pipe")

        try:
            data = await asyncio.wait_for(proc.stdout.read(8192), timeout=2.0)
        except asyncio.TimeoutError:
            raise ValueError("timeout while reading header from ffmpeg")

        if data:
            return data

        if proc:
            with contextlib.suppress(Exception):
                await self._stop_ffmpeg_process(proc)

        raise ValueError("no data received from ffmpeg header generator")

    async def get_header(
        self,
        *,
        track: ProcessedExtractModel | None = None,
        extra: dict[str, str | int] | None = None,
    ) -> bytes:
        """get cached header or generate a new one if expired."""
        if self._cached_header and not self._header_expired:
            return self._cached_header

        track = track or self._now_playing
        try:
            header = await self._generate_header(track, extra)
            self._cached_header = header
            self._header_expired = False
            return header
        except Exception as e:
            logger.error(f"failed to get or generate header: {e}", exc_info=True)
            raise

    async def _spawn_main_ffmpeg_process(self) -> asyncio.subprocess.Process:
        return await self._spawn_ffmpeg_process(
            [
                "ffmpeg",
                "-hide_banner",
                "-f",
                "s16le",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-re",  # real-time
                "-i",
                "pipe:0",  # stdin
                "-threads",
                "4",
                "-c:a",
                "libopus",
                "-b:a",
                "128k",
                "-ar",
                "48000",
                "-f",
                "ogg",
                "-vn",
                "-bufsize",
                "64k",
                "-loglevel",
                "error",
                "pipe:1",  # stdout
            ],
            reason="main audio stream",
        )

    async def _stop_main_ffmpeg_process(self) -> None:
        """stop the main ffmpeg process if it exists."""
        async with self._lock:
            if self._ffmpeg_process:
                await self._stop_ffmpeg_process(self._ffmpeg_process)
            self._ffmpeg_process = None

    async def _spawn_feed_ffmpeg_process(
        self, track: ProcessedExtractModel
    ) -> asyncio.subprocess.Process:
        return await self._spawn_ffmpeg_process(
            [
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
                "-f",
                "s16le",  # output format is raw PCM
                "-acodec",
                "pcm_s16le",  # output codec is PCM 16-bit little endian
                "-ar",
                "48000",  # sample rate
                "-ac",
                "2",  # stereo
                "-loglevel",
                "error",
                "pipe:1",
            ],
            reason="feed track process",
            stdin=None,
        )

    async def _stop_feed_ffmpeg_process(self) -> None:
        """stop the feed ffmpeg process if it exists."""
        async with self._lock:
            if self._feed_process:
                await self._stop_ffmpeg_process(self._feed_process)
            self._feed_process = None

    async def _spawn_silence_ffmpeg_process(self) -> asyncio.subprocess.Process:
        return await self._spawn_ffmpeg_process(
            [
                "ffmpeg",
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=48000:cl=stereo",
                "-f",
                "s16le",
                "-acodec",
                "pcm_s16le",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-loglevel",
                "error",
                "pipe:1",
            ],
            reason="silence generation",
            stdin=None,
        )

    async def _stop_silence_ffmpeg_process(self) -> None:
        """stop the silence ffmpeg process if it exists."""
        async with self._lock:
            if self._silence_process:
                await self._stop_ffmpeg_process(self._silence_process)
            self._silence_process = None

    async def _consume_ffmpeg_stderr(self) -> None:
        logger.debug("starting ffmpeg stderr consumer")

        if not self._ffmpeg_process:
            logger.debug("ffmpeg process not available")
            return

        stderr = self._ffmpeg_process.stderr
        if not stderr:
            logger.debug("ffmpeg stderr pipe is not available")
            return

        try:
            while not self._stopped.is_set():
                try:
                    line = await asyncio.wait_for(stderr.readline(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                if not line:
                    break

                message = line.decode("utf-8", errors="replace").strip()
                if message:
                    logger.error(f"ffmpeg stderr: {message}")

        except asyncio.CancelledError:
            logger.debug("ffmpeg stderr consumer task cancelled")

        except Exception as e:
            logger.error(f"error in ffmpeg stderr consumer: {e}", exc_info=True)

        logger.debug("ffmpeg stderr consumer task ended")

    async def _forward_process_output(
        self,
        source_process: asyncio.subprocess.Process,
        *,
        callback: Callable[[], Coroutine[None, None, None]] | None = None,
    ) -> None:
        """forward stdout from source_process into main ffmpeg stdin."""
        logger.debug("starting forwarder from source process to main ffmpeg stdin")

        if not self._ffmpeg_process:
            logger.warning("main ffmpeg process not available; cancelling forwarder")
            try:
                source_process.terminate()
            except Exception:
                pass
            return

        src_stdout = source_process.stdout
        dst_stdin = self._ffmpeg_process.stdin
        if not src_stdout or not dst_stdin:
            logger.warning("source stdout or main stdin missing")
            return

        try:
            while not self._stopped.is_set():
                chunk = await src_stdout.read(4096)
                if not chunk:
                    break
                try:
                    dst_stdin.write(chunk)
                    await dst_stdin.drain()
                except Exception:
                    logger.error("failed to write to main ffmpeg stdin", exc_info=True)
                    break

        except asyncio.CancelledError:
            logger.debug("forwarder task cancelled")

        except Exception as e:
            logger.error(f"unexpected error in forwarder: {e}", exc_info=True)

        finally:
            await self._stop_ffmpeg_process(source_process)
            if callback:
                await callback()
            logger.debug("forwarder task ended and source process cleaned up")

    async def add_track(self, url: str) -> None:
        """add a url to the queue."""
        if not url:
            logger.warning("no url provided to add to queue")
            return

    def _filter_duplicate_tracks(
        self, tracks: list[BaseExtractModel]
    ) -> list[BaseExtractModel]:
        if not tracks:
            return []

        history_ids = set(self._track_history)
        filtered_tracks = []

        for track in tracks:
            track_id = track.get("id")
            if track_id and track_id not in history_ids:
                filtered_tracks.append(track)
            else:
                logger.debug(
                    f"skipping duplicate track: {track.get('title', 'Unknown')} (ID: {track_id})"
                )

        logger.debug(
            f"filtered {len(tracks) - len(filtered_tracks)} duplicate tracks from auto queue"
        )
        return filtered_tracks

    async def _populate_auto_queue(self) -> None:
        """populate the auto queue with related tracks."""
        ...

    async def _process_track(self, track: BaseExtractModel) -> ProcessedExtractModel:
        """process a track into a playable format."""
        logger.debug(
            f"processing track: {track.get('title', 'Unknown')} (ID: {track.get('id', 'Unknown')})"
        )

        if track := validate_typed_dict(track, BaseExtractModel):
            return await extract_video_info(track["webpage_url"], process=True)

        if track := validate_typed_dict(track, ProcessedExtractModel):
            if track["is_expired"]():
                logger.info(
                    f"track URL expired, re-extracting: {track.get('title', 'Unknown')} (ID: {track.get('id', 'Unknown')})"
                )
                return await extract_video_info(track["webpage_url"], process=True)
            return track

        raise ValueError("invalid track data structure")

    async def get_next_track(self) -> ProcessedExtractModel | None:
        """get the next track from the queue without removing it."""
        if self._stopped.is_set():
            logger.debug("controller stopped; cannot get next track")
            return None

        try:
            track = self._queue.get_nowait()
            return await self._process_track(track)
        except asyncio.QueueEmpty:
            if self._now_playing:
                return self._now_playing

    async def _handle_queue(self) -> None:
        logger.debug("starting queue handler")

        error_count = 0
        max_errors = 5

        while not self._stopped.is_set():
            try:
                if self._queue.empty():
                    logger.debug("queue is empty, spawning silence process")
                    self._silence_process = await self._spawn_silence_ffmpeg_process()
                    self._active_forward_tasks.add(
                        self._loop.create_task(
                            self._forward_process_output(self._silence_process),
                            name="silence_forwarder",
                        )
                    )

                track_info = await self._queue.get()
                track = await self._process_track(track_info)
                logger.info("processing next track in queue")

                # stop silence process if running
                await self._stop_silence_ffmpeg_process()

                self._feed_process = await self._spawn_feed_ffmpeg_process(track)
                await self._forward_process_output(self._feed_process)

            except Exception as e:
                error_count += 1
                logger.error(f"error in queue handler: {e}", exc_info=True)
                if error_count >= max_errors:
                    logger.error("maximum error threshold reached in queue handler")
                    break

            except asyncio.CancelledError:
                logger.debug("queue handler task cancelled")
                break

    async def _ogg_reading_loop(self) -> None:
        logger.debug("starting ogg reading loop")

        ogg_processor = OggStreamProcessor()

        if not self._ffmpeg_process or not self._ffmpeg_process.stdout:
            logger.error("ffmpeg process or stdout not available for ogg reading")
            return

        stdout = self._ffmpeg_process.stdout

        try:
            async for page in ogg_processor.iter_pages(stdout):
                self._buffer_data = page.to_bytes()
                self._audio_buffer_event.set()
                self._audio_buffer_event.clear()

        except asyncio.CancelledError:
            logger.debug("ogg reading loop task cancelled")

        except Exception as e:
            logger.error(f"error in ogg reading loop: {e}", exc_info=True)

    async def start(self) -> None:
        if self._ffmpeg_process:
            logger.warning("ffmpeg process already running")
            return

        try:
            self._ffmpeg_process = await self._spawn_main_ffmpeg_process()
            logger.info("ffmpeg main process initialized successfully")
        except Exception as e:
            logger.error(f"failed to initialize FFmpeg process: {e}")
            await self._stop_main_ffmpeg_process()
            raise

        self._stderr_task = self._loop.create_task(
            self._consume_ffmpeg_stderr(),
            name="ffmpeg_stderr_consumer",
        )
        self._handle_queue_task = self._loop.create_task(
            self._handle_queue(),
            name="audio_queue_handler",
        )
        await self._ogg_reading_loop()

    async def stop(self) -> None:
        """gracefully stop the controller and clean up resources."""
        if self._stopped.is_set():
            logger.debug("stop called but controller already stopped")
            return

        logger.info("stopping audio stream controller")
        self._stopped.set()

        async def cancel_task(task: asyncio.Task[None] | None) -> None:
            if task:
                task.cancel()
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(task, timeout=2.0)

        # cancel queue task
        await cancel_task(self._handle_queue_task)
        self._handle_queue_task = None

        # cancel tracked forwarder tasks
        for task in set(self._active_forward_tasks):
            await cancel_task(task)
        self._active_forward_tasks.clear()

        # cancel stderr task
        await cancel_task(self._stderr_task)
        self._stderr_task = None

        # stop subprocesses
        await self._stop_feed_ffmpeg_process()
        await self._stop_silence_ffmpeg_process()
        await self._stop_main_ffmpeg_process()

        logger.info("audio stream controller stopped and cleaned up")


if __name__ == "__main__":

    async def pp(controller: AudioStreamController):
        while True:
            await controller._audio_buffer_event.wait()
            logger.info(controller._audio_buffer_event.is_set())
            logger.debug(controller._buffer_data[:32])

    async def main():
        controller = AudioStreamController()
        try:
            tasks = [controller.start(), pp(controller)]
            await asyncio.gather(*tasks)
        except KeyboardInterrupt:
            return
        finally:
            await controller.stop()

    asyncio.run(main())
