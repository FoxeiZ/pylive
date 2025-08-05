import json
import subprocess
from array import array
from queue import Queue
from threading import Event, Lock, Thread
from time import sleep
from typing import Any, Generator, Union

from src import extractor
from src.general import MISSING_TYPE, run_in_thread
from src.opusreader import OggStream

MISSING = MISSING_TYPE()


class SendEvent:
    NEXT_TRACK = "next"
    QUEUE_ADD = "queueadd"
    NOW_PLAYING = "nowplaying"

    def __init__(self) -> None:
        self.event_queue = Queue()
        self.event_data = ""
        self.event_signal = Event()

        self._event_manager_thread = Thread(
            target=self.manage_event, name="send_event_manager", daemon=True
        )
        self._event_manager_thread.start()

    def watch(self) -> Generator[str, None, None]:
        if "nowplaying" in self.event_data:
            yield self.event_data

        while True:
            self.event_signal.wait()
            yield self.event_data

    def manage_event(self):
        while True:
            self.event_signal.clear()
            data: tuple[str, dict[str, Any]] = self.event_queue.get()
            self.event_data = f"event: {data[0]}\ndata: {json.dumps(data[1])}\n\n"
            self.event_signal.set()

    def add_event(self, event_type: str, data: dict):
        self.event_queue.put((event_type, data))


class QueueAudioHandler:
    __slots__ = (
        "queue",
        "auto_queue",
        "_skip",
        "lock",
        "event",
        "now_playing",
        "header",
        "buffer",
        "next_signal",
        "ffmpeg",
        "ffmpeg_stdout",
        "ffmpeg_stdin",
        "_audio_position",
        "_audio_thread",
        "_audio_queue_thread",
        "event_queue",
    )

    def __init__(self):
        # self.queue = ["https://music.youtube.com/watch?v=cUuQ5L6Obu4"]
        self.queue: list[Union[str, dict[str, str | bool | float]]] = []
        self.auto_queue: list[Union[str, dict[str, str | bool | float]]] = []

        self._skip = False
        self.lock = Lock()
        self.event = Event()
        self.now_playing: dict = {}

        self.header = b""
        self.buffer = b""

        self.next_signal = Event()

        self.event_queue = SendEvent()

        self.ffmpeg = MISSING
        self.ffmpeg = self._spawn_main_process()
        self.ffmpeg_stdout = self.ffmpeg.stdout
        self.ffmpeg_stdin = self.ffmpeg.stdin

        self._audio_position: int = 0
        self._audio_thread = Thread(
            target=self.oggstream_reader, name="audio_vroom_vroom", daemon=True
        )
        self._audio_queue_thread = Thread(
            target=self.queue_handler, name="queue", daemon=True
        )
        self._audio_queue_thread.start()
        self._audio_thread.start()

    @property
    def audio_duration(self):
        if not isinstance(self.now_playing, dict):
            return 0

        return self.now_playing.get("duration", 0)

    @property
    def audio_position(self):
        return self._audio_position

    @audio_position.setter
    def audio_position(self, value):
        with self.lock:
            self._audio_position = value

    def populate_autoqueue(self):
        if not self.auto_queue and not self.queue:
            # take 2 items only
            self.auto_queue = extractor.youtube_get_related_tracks(self.now_playing)[:2]

    def __add(self, url):
        ret = extractor.create(url, process=False)
        self.queue.append(ret)
        self.event_queue.add_event(SendEvent.QUEUE_ADD, ret)

    def add(self, url):
        run_in_thread(self.__add, url)

    def pop(self):
        if self.queue:
            self.auto_queue.clear()
            return self.queue.pop(0)

        if not self.auto_queue:
            self.populate_autoqueue()
        return self.auto_queue.pop(0)

    @staticmethod
    def _spawn_main_process():
        return subprocess.Popen(
            [
                "ffmpeg",
                "-re",
                "-i",
                "-",
                "-threads",
                "2",
                "-c:a",
                "copy",
                "-f",
                "opus",
                "-loglevel",
                "error",
                "pipe:1",
            ],
            stdout=subprocess.PIPE,
            stdin=subprocess.PIPE,
            stderr=None,
        )

    def oggstream_reader(self):
        assert self.ffmpeg_stdout is not None, "ffmpeg stdout is None or not set"
        pages_iter = OggStream(self.ffmpeg_stdout).iter_pages()
        try:
            page = next(pages_iter)
            if page.flag == 2:
                self.header += b"OggS" + page.header + page.segtable + page.data

            page = next(pages_iter)
            self.header += b"OggS" + page.header + page.segtable + page.data

            for page in pages_iter:
                partial = array("b")
                partial.frombytes(b"OggS" + page.header + page.segtable)
                for data, _ in page.iter_packets():
                    partial.frombytes(data)

                self.buffer = partial.tobytes()
                self.audio_position += 1
                self.event.set()
                self.event.clear()
        except ValueError:
            return

    def ffmpeg_stdin_writer(self, q: Queue, sig: Event):
        while True:
            audio_np = q.get()
            self.audio_position = 0

            self.event_queue.add_event(SendEvent.NOW_PLAYING, audio_np)

            s = subprocess.Popen(
                [
                    "ffmpeg",
                    "-reconnect",
                    "1",
                    "-reconnect_streamed",
                    "1",
                    "-reconnect_delay_max",
                    "5",
                    "-i",
                    audio_np["url"],
                    "-threads",
                    "2",
                    "-b:a",
                    "152k",
                    "-ar",
                    "48000",
                    "-c:a",
                    "copy",
                    "-f",
                    "opus",
                    "-vn",
                    "-loglevel",
                    "error",
                    "pipe:1",
                ],
                stdout=subprocess.PIPE,
                stdin=None,
                stderr=None,
            )

            while True:
                if s.poll():
                    break

                data = s.stdout.read(8192)  # type: ignore
                if not data or self._skip:
                    break
                self.ffmpeg_stdin.write(data)  # type: ignore

            sig.set()
            self._skip = False
            # self.header = b""
            # self.buffer = b""
            print("signal is set")

    def queue_handler(self):
        queue = Queue()
        stdin_writer_thread = Thread(
            target=self.ffmpeg_stdin_writer,
            args=(queue, self.next_signal),
            name="ffmpeg_stdin_writer",
            daemon=True,
        )
        stdin_writer_thread.start()
        print("start stdin writer")

        while True:
            self.next_signal.clear()
            next_track = self.pop()  # type: ignore

            try:
                if isinstance(next_track, str):
                    next_track = extractor.create(next_track)  # type: ignore
                elif not next_track.get("process", False):  # type: ignore
                    next_track = extractor.create(next_track["webpage_url"])  # type: ignore  # noqa: E501

                if not next_track:
                    continue
            except Exception:
                continue

            self.now_playing = next_track
            queue.put(self.now_playing)
            print(f"Playing {self.now_playing['title']}")
            print("wait for signal")
            self.next_signal.wait()

    def wait_for_header(self):
        while True:
            if self.header:
                return self.header
            sleep(0.5)

    def __skip(self):
        track = self.pop()
        self.queue.append(track)
        self._skip = True

    def skip(self):
        run_in_thread(self.__skip, wait_for_result=False)
