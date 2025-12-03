# audio streaming constants
POLL_INTERVAL = 0.1  # seconds between FFmpeg stdin writes
AUDIO_BUFFER_SIZE = 4096  # bytes per audio read chunk

# queue limits
QUEUE_MAX_SIZE = 50
TRACK_HISTORY_SIZE = 50
MAX_SSE_CONNECTIONS = 1000

# video duration limits
MAX_DURATION_SECONDS = 8 * 60  # 8 minutes (480 seconds)

# playlist and related tracks limits
MAX_PLAYLIST_ENTRIES = 25
MAX_RELATED_TRACKS = 25

# cache configuration
VIDEO_INFO_CACHE_TTL = 30 * 60  # 30 minutes
VIDEO_INFO_CACHE_MAXSIZE = 500
RELATED_TRACKS_CACHE_TTL = 15 * 60  # 15 minutes
RELATED_TRACKS_CACHE_MAXSIZE = 200
