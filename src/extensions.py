import atexit

from .server import AudioStreamController

__all__ = ["audio_controller"]

audio_controller = AudioStreamController()
atexit.register(audio_controller.shutdown)
