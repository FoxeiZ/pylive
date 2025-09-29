import logging

from .server import AudioQueueManager

__all__ = ["audio_manager"]

logger = logging.getLogger(__name__)

try:
    audio_manager = AudioQueueManager()
    logger.info("Audio manager initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize audio manager: {e}")
    audio_manager = None
