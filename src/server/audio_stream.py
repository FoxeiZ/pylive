from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
import os
import signal
import struct
import subprocess
import sys
from collections import OrderedDict
from typing import TYPE_CHECKING

from ..extractor import extract_video_info, get_related_tracks, is_track_expired
from ..models.extract import BaseExtractModel, ProcessedExtractModel
from ..utils.validator import validate_typed_dict
from .broadcaster import EventManager, EventType

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable, Coroutine, Iterable, Iterator


if __name__ == "__main__":
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

    def __iter__(self) -> Iterator[T]:
        return iter(self._data)

    def clear(self) -> None:
        self._data.clear()


class OggPage:
    __slots__ = (
        "crc",
        "data",
        "flag",
        "gran_pos",
        "header",
        "pagenum",
        "segnum",
        "segtable",
        "serial",
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
    HEADER_STRUCT = struct.Struct("<xBQIIIB")
    HEADER_SIZE = HEADER_STRUCT.size

    @staticmethod
    def rewrite_serial(page_bytes: bytes, new_serial: int) -> bytes:
        """rewrite the serial number in an ogg page and recalculate CRC."""
        if len(page_bytes) < 27 or page_bytes[:4] != b"OggS":
            return page_bytes

        data = bytearray(page_bytes)

        # write new serial number at offset 14 (little-endian)
        struct.pack_into("<I", data, 14, new_serial)

        # zero out CRC field before recalculating
        data[22:26] = b"\x00\x00\x00\x00"

        # calculate new CRC
        new_crc = OggStreamProcessor._calculate_crc(bytes(data))
        struct.pack_into("<I", data, 22, new_crc)

        return bytes(data)

    @staticmethod
    def rewrite_header_pages(header_data: bytes, new_serial: int) -> bytes:
        """rewrite serial numbers in all ogg pages within header data."""
        result = bytearray()
        offset = 0

        while offset < len(header_data):
            if header_data[offset : offset + 4] != b"OggS":
                break

            if len(header_data) < offset + 27:
                break

            # get segment count and calculate page size
            segment_count = header_data[offset + 26]
            header_size = 27 + segment_count

            if len(header_data) < offset + header_size:
                break

            segment_table = header_data[offset + 27 : offset + header_size]
            body_size = sum(segment_table)
            total_page_size = header_size + body_size

            if len(header_data) < offset + total_page_size:
                break

            # extract page and rewrite serial
            page_bytes = header_data[offset : offset + total_page_size]
            rewritten_page = OggStreamProcessor.rewrite_serial(page_bytes, new_serial)
            result.extend(rewritten_page)

            offset += total_page_size

        return bytes(result)

    @staticmethod
    def _calculate_crc(data: bytes) -> int:
        """calculate ogg CRC-32 checksum."""
        crc_table = OggStreamProcessor._get_crc_table()
        crc = 0
        for byte in data:
            crc = ((crc << 8) ^ crc_table[((crc >> 24) & 0xFF) ^ byte]) & 0xFFFFFFFF
        return crc

    @staticmethod
    @functools.cache
    def _get_crc_table() -> tuple[int, ...]:
        """generate ogg CRC lookup table (cached)."""
        table: list[int] = []
        for i in range(256):
            crc = i << 24
            for _ in range(8):
                crc = (
                    (crc << 1 ^ 79764919) & 4294967295
                    if crc & 2147483648
                    else crc << 1 & 4294967295
                )
            table.append(crc)
        return tuple(table)

    async def read_page(self, stdout: asyncio.StreamReader) -> OggPage | None:
        try:
            head = await stdout.readexactly(4)
            if head != b"OggS":
                if not head:
                    return None
                raise ValueError("invalid ogg header magic")

            header_data = await stdout.readexactly(self.HEADER_SIZE)

            (
                flag,
                gran_pos,
                serial,
                pagenum,
                crc,
                segnum,
            ) = self.HEADER_STRUCT.unpack(header_data)
            segtable = await stdout.readexactly(segnum)
            bodylen = sum(segtable)
            body_data = await stdout.readexactly(bodylen)

            return OggPage(
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
    ) -> AsyncGenerator[OggPage, None]:
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
    __slots__ = (
        "_audio_listeners",
        "_audio_listeners_lock",
        "_auto_queue",
        "_broadcaster",
        "_cached_header",
        "_feed_process",
        "_ffmpeg_process",
        "_handle_queue_task",
        "_header_expired",
        "_header_lock",
        "_headers_ready",
        "_lock",
        "_loop",
        "_main_stream_serial",
        "_now_playing",
        "_ogg_reading_task",
        "_queue",
        "_shutdown_requested",
        "_silence_forwarder_task",
        "_silence_process",
        "_stderr_task",
        "_stdin_lock",
        "_stopped",
        "_track_history",
    )

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = asyncio.Lock()
        self._stdin_lock = asyncio.Lock()
        self._header_lock = asyncio.Lock()
        self._stopped = asyncio.Event()
        self._shutdown_requested = False

        self._queue: asyncio.Queue[BaseExtractModel] = asyncio.Queue(maxsize=500)
        self._auto_queue: asyncio.Queue[BaseExtractModel] = asyncio.Queue(maxsize=500)
        self._track_history: BoundedHistory[str] = BoundedHistory(maxlen=100)
        self._now_playing: ProcessedExtractModel | None = None

        self._stderr_task: asyncio.Task[None] | None = None
        self._handle_queue_task: asyncio.Task[None] | None = None
        self._ogg_reading_task: asyncio.Task[None] | None = None
        self._silence_forwarder_task: asyncio.Task[None] | None = None

        self._ffmpeg_process: asyncio.subprocess.Process | None = None
        self._feed_process: asyncio.subprocess.Process | None = None
        self._silence_process: asyncio.subprocess.Process | None = None

        self._main_stream_serial: int | None = None
        self._cached_header: bytes | None = None
        self._header_expired: bool = True
        self._headers_ready: asyncio.Event = asyncio.Event()

        self._audio_listeners: set[asyncio.Queue[bytes]] = set()
        self._audio_listeners_lock = asyncio.Lock()

        self._broadcaster = EventManager()

    @property
    def now_playing(self) -> ProcessedExtractModel | None:
        return self._now_playing

    @property
    def queue(self) -> list[BaseExtractModel]:
        return list(self._queue._queue)  # type: ignore

    @property
    def auto_queue(self) -> list[BaseExtractModel]:
        return list(self._auto_queue._queue)  # type: ignore

    @property
    def event_queue(self) -> EventManager:
        return self._broadcaster

    async def _spawn_ffmpeg_process(
        self,
        cmd: Iterable[str],
        *,
        reason: str = "no reason",
        stdin: int | None = asyncio.subprocess.PIPE,
        stdout: int | None = asyncio.subprocess.PIPE,
        stderr: int | None = asyncio.subprocess.PIPE,
    ) -> asyncio.subprocess.Process:
        """spawn the ffmpeg process in a new process group."""
        logger.debug(f"spawning ffmpeg process, reason: {reason}")

        # create process in new group for clean termination
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            creationflags = 0

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            creationflags=creationflags,
            start_new_session=(sys.platform != "win32"),
        )
        return process

    async def _stop_ffmpeg_process(
        self, process: asyncio.subprocess.Process | None, *, wait_timeout: float = 5.0
    ) -> None:
        """stop a given ffmpeg process and its children."""
        if not process:
            return

        if process.returncode is not None:
            logger.debug("process already terminated, skipping cleanup")
            return

        pid = process.pid
        _io_errors = (BrokenPipeError, ConnectionResetError, OSError, ValueError)

        if process.stdin:
            with contextlib.suppress(*_io_errors):
                logger.debug("closing process stdin")
                process.stdin.close()

        # send signal to process group
        with contextlib.suppress(ProcessLookupError, OSError):
            logger.debug("terminating ffmpeg process group")
            if sys.platform == "win32":
                os.kill(pid, signal.CTRL_BREAK_EVENT)
            else:
                os.killpg(os.getpgid(pid), signal.SIGTERM)

        try:
            async with asyncio.timeout(wait_timeout):
                logger.debug("waiting for process to terminate")
                await process.wait()

                if process.stdin:
                    with contextlib.suppress(*_io_errors):
                        await process.stdin.wait_closed()

        except TimeoutError:
            logger.debug("timeout waiting for process, force killing")
            with contextlib.suppress(ProcessLookupError, OSError):
                if sys.platform == "win32":
                    process.kill()
                else:
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
            with contextlib.suppress(ProcessLookupError, OSError):
                await process.wait()

        # note: we don't drain stdout/stderr here to avoid memory issues
        # with infinite sources like silence generators. The process is
        # already terminated so the pipes will be closed automatically.

    async def _generate_header(
        self,
        track: ProcessedExtractModel | None = None,
        extra: dict[str, str | int] | None = None,
    ) -> bytes:
        """generate the Opus header for a given track."""
        logger.info("generating Opus header for track")
        meta_args = extra or {}

        if track:
            for key in ("title", "artist", "album", "comment"):
                val = track.get(key)
                if val:
                    meta_args[key] = val

        # fmt: off
        cmd: list[str] = [
            "ffmpeg",
            "-f", "lavfi",
            "-i", "anullsrc=r=48000:cl=stereo",
            "-af", "aformat=sample_fmts=s16",
            "-t", "1",
        ]
        # fmt: on

        if meta_args:
            for key, val in meta_args.items():
                cmd.extend(["-metadata", f"{key}={val}"])

        # fmt: off
        cmd.extend(
            [
                "-vn",
                "-c:a", "libopus",
                "-frames:a", "0",
                "-ac", "2",
                "-ar", "48000",
                "-f", "ogg",
                "-loglevel", "error",
                "pipe:1",
            ]
        )
        # fmt: on

        proc: asyncio.subprocess.Process | None = None
        proc = await self._spawn_ffmpeg_process(
            cmd, reason="generate header", stdin=None
        )

        stdout, _ = await proc.communicate()
        return stdout

    async def get_header(
        self,
        *,
        track: ProcessedExtractModel | None = None,
        extra: dict[str, str | int] | None = None,
    ) -> bytes:
        """get current ogg header with correct serial number."""
        async with self._header_lock:
            if self._cached_header is None or self._header_expired:
                raw_header = await self._generate_header(track=track, extra=extra)

                # rewrite serial to match main stream if available
                if self._main_stream_serial is not None:
                    self._cached_header = OggStreamProcessor.rewrite_header_pages(
                        raw_header, self._main_stream_serial
                    )
                    logger.debug(
                        f"rewrote header serial to 0x{self._main_stream_serial:08X}"
                    )
                else:
                    self._cached_header = raw_header
                    logger.warning(
                        "main stream serial not yet available, using original"
                    )

                self._header_expired = False

            return self._cached_header

    async def _spawn_main_ffmpeg_process(self) -> asyncio.subprocess.Process:
        # fmt: off
        return await self._spawn_ffmpeg_process(
            [
                "ffmpeg",
                "-re",
                "-hide_banner",
                "-f", "s16le",
                "-ar", "48000",
                "-ac", "2",
                "-i", "pipe:0",
                "-threads", "4",
                "-c:a", "libopus",
                "-b:a", "128k",
                "-ar", "48000",
                "-frame_duration", "20",
                "-application", "audio",
                "-f", "ogg",
                "-flush_packets", "1",
                "-vbr", "off",
                "-vn",
                # "-bufsize", "64k",
                "-loglevel", "error",
                "pipe:1",
            ],
            reason="main audio stream",
        )
        # fmt: on

    async def _stop_main_ffmpeg_process(self) -> None:
        """stop the main ffmpeg process if it exists."""
        async with self._lock:
            if self._ffmpeg_process:
                await self._stop_ffmpeg_process(self._ffmpeg_process)
            self._ffmpeg_process = None

    async def _spawn_feed_ffmpeg_process(
        self, track: ProcessedExtractModel
    ) -> asyncio.subprocess.Process:
        # fmt: off
        return await self._spawn_ffmpeg_process(
            [
                "ffmpeg",
                "-reconnect", "1",
                "-reconnect_streamed", "1",
                "-reconnect_delay_max", "5",
                "-i",
                track["url"],
                "-threads", "2",
                "-af", "aresample=async=1",  # handle timestamp discontinuities
                "-f", "s16le",
                "-acodec", "pcm_s16le",
                "-ar", "48000",
                "-ac", "2",
                "-flush_packets", "1",
                "-loglevel", "error",
                "pipe:1",
            ],
            reason="feed track process",
            stdin=None,
            stderr=asyncio.subprocess.DEVNULL,
        )
        # fmt: on

    async def _stop_feed_ffmpeg_process(self) -> None:
        """stop the feed ffmpeg process if it exists."""
        async with self._lock:
            if self._feed_process:
                await self._stop_ffmpeg_process(self._feed_process)
            self._feed_process = None

    async def _spawn_silence_ffmpeg_process(self) -> asyncio.subprocess.Process:
        # fmt: off
        return await self._spawn_ffmpeg_process(
            [
                "ffmpeg",
                "-re",
                "-f", "lavfi",
                "-i", "anullsrc=r=48000:cl=stereo",
                "-f", "s16le",
                "-acodec", "pcm_s16le",
                "-ar", "48000",
                "-ac", "2",
                "-flush_packets", "1",
                "-loglevel", "error",
                "pipe:1",
            ],
            reason="silence generation",
            stdin=None,
            stderr=asyncio.subprocess.DEVNULL,
        )
        # fmt: on

    async def _stop_silence_ffmpeg_process(self) -> None:
        """stop the silence ffmpeg process and its forwarder task."""
        # cancel the forwarder task first to prevent read errors
        if self._silence_forwarder_task and not self._silence_forwarder_task.done():
            self._silence_forwarder_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._silence_forwarder_task
            self._silence_forwarder_task = None

        async with self._lock:
            if self._silence_process:
                await self._stop_ffmpeg_process(self._silence_process, wait_timeout=0.1)
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
                except TimeoutError:
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
            with contextlib.suppress(Exception):
                source_process.terminate()
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
                    async with self._stdin_lock:
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

        logger.info(f"adding track to queue: {url}")
        track_info = await extract_video_info(url, process=False)
        track_id = track_info.get("id")
        if track_id:
            self._track_history.add(track_id)
        await self._broadcaster.add_event(EventType.QUEUE_ADD, track_info)
        await self._queue.put(track_info)

    def _filter_duplicate_tracks(
        self, tracks: list[BaseExtractModel]
    ) -> list[BaseExtractModel]:
        if not tracks:
            return []

        history_ids = set(self._track_history)
        filtered_tracks: list[BaseExtractModel] = []

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

    async def _populate_auto_queue(
        self, current_track: BaseExtractModel | ProcessedExtractModel
    ) -> None:
        """populate the auto queue with related tracks."""
        try:
            related = await get_related_tracks(current_track)
            filtered = self._filter_duplicate_tracks(list(related))
            for track in filtered:
                track_id = track.get("id")
                if track_id:
                    self._track_history.add(track_id)
                try:
                    self._auto_queue.put_nowait(track)
                except asyncio.QueueFull:
                    break
            logger.info(f"populated auto queue with {len(filtered)} related tracks")
        except Exception as e:
            logger.warning(f"failed to populate auto queue: {e}")

    async def refresh_autoplay_queue(self) -> None:
        if not self._now_playing:
            logger.warning("no track currently playing; cannot refresh autoplay queue")
            return

        logger.info("refreshing autoplay queue with new related tracks")
        await self._populate_auto_queue(self._now_playing)

    async def _process_track(
        self, track: BaseExtractModel | ProcessedExtractModel
    ) -> ProcessedExtractModel:
        """process a track into a playable format."""
        logger.debug(
            f"processing track: {track.get('title', 'Unknown')} (ID: {track.get('id', 'Unknown')})"
        )

        with contextlib.suppress(ValueError, TypeError):
            processed = validate_typed_dict(track, ProcessedExtractModel)
            if is_track_expired(processed):
                logger.info(
                    f"track URL expired, re-extracting: {processed.get('title', 'Unknown')} (ID: {processed.get('id', 'Unknown')})"  # noqa: E501
                )
                return await extract_video_info(processed["webpage_url"], process=True)
            return processed

        with contextlib.suppress(ValueError, TypeError):
            base = validate_typed_dict(track, BaseExtractModel)
            return await extract_video_info(base["webpage_url"], process=True)

        raise ValueError("invalid track data structure")

    async def _handle_queue(self) -> None:
        logger.debug("starting queue handler")

        error_count = 0

        while not self._stopped.is_set() and self._loop:
            try:
                if self._queue.empty() and self._auto_queue.empty():
                    async with self._lock:
                        if not self._silence_process:
                            logger.debug("queue is empty, spawning silence process")
                            self._now_playing = None
                            self._silence_process = (
                                await self._spawn_silence_ffmpeg_process()
                            )
                            self._silence_forwarder_task = self._loop.create_task(
                                self._forward_process_output(self._silence_process),
                                name="silence_forwarder",
                            )

                if not self._queue.empty():
                    track_info = await self._queue.get()
                elif not self._auto_queue.empty():
                    track_info = await self._auto_queue.get()
                else:
                    track_info = await self._queue.get()

                track = await self._process_track(track_info)
                self._now_playing = track

                strip_track = track.copy()
                strip_track.pop("process", None)
                strip_track.pop("extractor", None)
                strip_track.pop("url", None)
                strip_track.pop("expires_in", None)
                await self._broadcaster.add_event(EventType.NOW_PLAYING, strip_track)

                track_id = track.get("id")
                if track_id:
                    self._track_history.add(track_id)

                logger.info(
                    "processing next track in queue: %s (ID: %s)",
                    track.get("title", "Unknown"),
                    track.get("id", "Unknown"),
                )

                if self._auto_queue.qsize() < 5:
                    self._loop.create_task(
                        self._populate_auto_queue(track),
                        name="populate_auto_queue",
                    )

                # stop silence process if running
                await self._stop_silence_ffmpeg_process()

                async with self._lock:
                    self._feed_process = await self._spawn_feed_ffmpeg_process(track)
                await self._forward_process_output(self._feed_process)

                error_count = 0  # reset on success

            except asyncio.CancelledError:
                logger.debug("queue handler task cancelled")
                break

            except Exception as e:
                error_count += 1
                backoff = min(error_count * 2, 10)
                logger.error(
                    f"error in queue handler (attempt {error_count}, retrying in {backoff}s): {e}",
                    exc_info=True,
                )
                await asyncio.sleep(backoff)

    async def _ogg_reading_loop(self) -> None:
        logger.debug("starting ogg reading loop")

        ogg_processor = OggStreamProcessor()

        if not self._ffmpeg_process or not self._ffmpeg_process.stdout:
            logger.error("ffmpeg process or stdout not available for ogg reading")
            return

        stdout = self._ffmpeg_process.stdout

        try:
            async for page in ogg_processor.iter_pages(stdout):
                if self._stopped.is_set():
                    break

                if not self._headers_ready.is_set() and (page.flag & 0x02):
                    self._main_stream_serial = page.serial
                    logger.info(
                        f"captured main stream serial: 0x{self._main_stream_serial:08X}"
                    )
                    self._headers_ready.set()
                    continue

                raw_page_data = page.to_bytes()

                async with self._audio_listeners_lock:
                    if self._audio_listeners:
                        for listener_queue in list(self._audio_listeners):
                            try:
                                listener_queue.put_nowait(raw_page_data)
                            except asyncio.QueueFull:
                                with contextlib.suppress(asyncio.QueueEmpty):
                                    listener_queue.get_nowait()
                                with contextlib.suppress(asyncio.QueueFull):
                                    listener_queue.put_nowait(raw_page_data)

        except asyncio.CancelledError:
            logger.debug("ogg reading loop task cancelled")
        except Exception as e:
            logger.error(f"error in ogg reading loop: {e}", exc_info=True)
        finally:
            async with self._audio_listeners_lock:
                for listener_queue in list(self._audio_listeners):
                    try:
                        listener_queue.put_nowait(b"")
                    except asyncio.QueueFull:
                        with contextlib.suppress(asyncio.QueueEmpty):
                            listener_queue.get_nowait()
                        with contextlib.suppress(Exception):
                            listener_queue.put_nowait(b"")

    async def start(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        self._loop = loop or asyncio.get_running_loop()
        self._stopped.clear()
        self._headers_ready.clear()
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
        self._ogg_reading_task = self._loop.create_task(
            self._ogg_reading_loop(),
            name="ogg_reading_loop",
        )
        logger.info("audio stream controller started")

    def is_alive(self) -> bool:
        """check if the audio stream controller is running."""
        return (
            self._ffmpeg_process is not None
            and self._ffmpeg_process.returncode is None
            and not self._stopped.is_set()
        )

    async def skip_current_track(self) -> None:
        if not self.is_alive():
            logger.warning("cannot skip track; audio stream controller is not running")
            return

        logger.info("skipping current track")
        await self._stop_feed_ffmpeg_process()
        await self._stop_silence_ffmpeg_process()

    async def stop(self) -> None:
        """gracefully stop the controller and clean up resources."""
        if self._stopped.is_set():
            logger.debug("stop called but controller already stopped")
            return

        logger.info("stopping audio stream controller")
        self._stopped.set()

        await self._broadcaster.shutdown()

        # notify with eof sentinel
        async with self._audio_listeners_lock:
            for listener_queue in list(self._audio_listeners):
                try:
                    listener_queue.put_nowait(b"")
                except asyncio.QueueFull:
                    with contextlib.suppress(asyncio.QueueEmpty):
                        listener_queue.get_nowait()
                    with contextlib.suppress(Exception):
                        listener_queue.put_nowait(b"")

        async def cancel_task(task: asyncio.Task[None] | None) -> None:
            if task and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await asyncio.wait_for(asyncio.shield(task), timeout=2.0)

        # stop subprocesses first to prevent broken pipe errors
        await self._stop_feed_ffmpeg_process()
        await self._stop_silence_ffmpeg_process()
        await self._stop_main_ffmpeg_process()

        await asyncio.gather(
            cancel_task(self._ogg_reading_task),
            cancel_task(self._handle_queue_task),
            cancel_task(self._stderr_task),
        )
        self._ogg_reading_task = None
        self._handle_queue_task = None
        self._stderr_task = None
        self._now_playing = None

        logger.info("audio stream controller stopped and cleaned up")

    async def stream(self) -> AsyncGenerator[bytes, None]:
        if not self.is_alive():
            raise RuntimeError("audio stream controller is not running")

        client_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=100)
        async with self._audio_listeners_lock:
            self._audio_listeners.add(client_queue)

        try:
            await asyncio.wait_for(self._headers_ready.wait(), timeout=10.0)
            header = await self.get_header()
            yield header

            while self.is_alive() and not self._stopped.is_set():
                try:
                    chunk = await asyncio.wait_for(client_queue.get(), timeout=1.0)
                except TimeoutError:
                    if self._stopped.is_set() or not self.is_alive():
                        break
                    continue

                if not chunk:  # eof sentinel
                    break
                yield chunk
                client_queue.task_done()

        except TimeoutError:
            logger.error("timeout waiting for stream headers")
            raise RuntimeError("failed to initialize audio stream") from TimeoutError
        except asyncio.CancelledError:
            logger.debug("client connection decoupled from audio stream")
            raise
        finally:
            async with self._audio_listeners_lock:
                self._audio_listeners.discard(client_queue)


if __name__ == "__main__":

    async def pp(controller: AudioStreamController):
        while True:
            s = await controller.stream().__anext__()
            logger.info(f"stream chunk received: {len(s)} bytes")

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
