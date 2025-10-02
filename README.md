A real-time audio streaming server that downloads YouTube videos and streams them as live audio with queue management and audio visualization.

## About The Project

PyLive transforms YouTube videos into a seamless live audio streaming experience. Built with a Flask backend and vanilla JavaScript frontend, it features dual queue management (user-requested + auto-generated), real-time audio visualization, and server-sent events for instant UI updates.

### Key Features

- **Real-time Audio Streaming**: Converts YouTube videos to live Opus/Ogg audio streams
- **Intelligent Queue Management**: User queue + auto-generated related tracks
- **Audio Visualization**: Canvas-based waveform display with Web Audio API
- **Live Updates**: Server-sent events for real-time queue and playback status
- **Smart Validation**: 15-minute duration limit, live stream blocking
- **Thread-safe Operations**: Background processing with graceful shutdown

## Built With

![Python](https://img.shields.io/badge/python-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54)
![Flask](https://img.shields.io/badge/flask-%23000.svg?style=for-the-badge&logo=flask&logoColor=white)
![JavaScript](https://img.shields.io/badge/javascript-%23323330.svg?style=for-the-badge&logo=javascript&logoColor=%23F7DF1E)
![HTML5](https://img.shields.io/badge/html5-%23E34F26.svg?style=for-the-badge&logo=html5&logoColor=white)
![CSS3](https://img.shields.io/badge/css3-%23157FC9.svg?style=for-the-badge&logo=css3&logoColor=white)
![FFmpeg](https://img.shields.io/badge/FFmpeg-%23171717.svg?style=for-the-badge&logo=ffmpeg&logoColor=white)

**Core Technologies:**

- **Backend**: Flask 3.1+ with Blueprint architecture
- **Audio Processing**: FFmpeg + yt-dlp for YouTube extraction
- **Frontend**: Vanilla JavaScript with Canvas API
- **Streaming**: Opus/Ogg format with real-time packet processing
- **Package Management**: uv for fast dependency resolution

## Getting Started

### Prerequisites

- **Python 3.12+**
- **FFmpeg** (system dependency for audio conversion)
- **uv** package manager (recommended)

#### Install FFmpeg

**Windows:**

```bash
# Using Chocolatey
choco install ffmpeg

# Or download from https://ffmpeg.org/download.html
```

**macOS:**

```bash
brew install ffmpeg
```

**Linux:**

```bash
# Ubuntu/Debian
sudo apt update && sudo apt install ffmpeg

# Arch Linux
sudo pacman -S ffmpeg
```

#### Install uv

```bash
# Windows/macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Installation

1. **Clone the repository**

   ```bash
   git clone https://github.com/FoxeiZ/pylive.git
   cd pylive
   ```

2. **Install dependencies**

   ```bash
   uv sync
   ```

3. **Verify FFmpeg installation**

   ```bash
   ffmpeg -version
   ```

4. **Run the application**

   ```bash
   uv run python main.py
   ```

5. **Access the application**
   ```
   http://localhost:8001
   ```

## Usage

### Adding Tracks

**Via Web Interface:**

1. Navigate to `http://localhost:8001`
2. Paste a YouTube URL in the input field
3. Click "Add to Queue"

**Via API:**

```bash
curl -X POST http://localhost:8001/queue/add \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=VIDEO_ID"}'
```

## API Reference

### Queue Endpoints

| Method | Endpoint      | Description                   |
| ------ | ------------- | ----------------------------- |
| `GET`  | `/queue/`     | Get current queue (paginated) |
| `POST` | `/queue/add`  | Add track to queue            |
| `POST` | `/queue/skip` | Skip current track            |
| `GET`  | `/queue/auto` | Get auto-generated queue      |

### Streaming Endpoints

| Method | Endpoint       | Description             |
| ------ | -------------- | ----------------------- |
| `GET`  | `/stream`      | Audio stream (Opus/Ogg) |
| `GET`  | `/watch_event` | Server-sent events      |
| `GET`  | `/np`          | Now playing information |

## License

This project is licensed under the **MIT License** - see the [LICENSE](LICENSE) file for details.
