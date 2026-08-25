export class AudioVisualizer {
  static MODES = {
    BARS: "bars",
    WAVEFORM: "waveform",
    SYMMETRIC: "symmetric",
    ROUND_BARS: "round_bars",
  };

  static THEMES = {
    cyan: {
      color: "#06b6d4",
      cap: "#a5f3fc",
    },
    emerald: {
      color: "#10b981",
      cap: "#a7f3d0",
    },
    violet: {
      color: "#8b5cf6",
      cap: "#ddd6fe",
    },
    amber: {
      color: "#f59e0b",
      cap: "#fde68a",
    },
    coral: {
      color: "#f43f5e",
      cap: "#fecdd3",
    },
    monochrome: {
      color: "#f1f5f9",
      cap: "#ffffff",
    },
  };

  constructor(options = {}) {
    this.canvas = options.canvas || null;
    this.ctx = this.canvas ? this.canvas.getContext("2d") : null;
    this.audioElement = options.audioElement || null;
    this.audioContext = null;
    this.analyser = null;
    this.sourceNode = null;

    this.mode = options.mode || AudioVisualizer.MODES.BARS;
    this.themeName = options.theme || "cyan";
    this.barCount = options.barCount || 48;
    this.fftSize = options.fftSize || 1024;
    this.smoothingTimeConstant = options.sensitivity ?? 0.8;
    this.minDecibels = options.minDecibels ?? -85;
    this.maxDecibels = options.maxDecibels ?? -20;
    this.fps = options.fps || 60;
    this.thickness = options.thickness || 2;
    this.multiplier = options.multiplier || 1.0;

    this.animationId = null;
    this.lastFrameTime = 0;
    this.isInitialized = false;
    this.isRunning = false;
    this.resizeObserver = null;

    this.frequencyData = null;
    this.timeDomainData = null;
  }

  // initialize audio context and connect media element source
  init(audioElement, canvasElement) {
    if (audioElement) this.audioElement = audioElement;
    if (canvasElement) {
      this.canvas = canvasElement;
      this.ctx = this.canvas.getContext("2d");
    }

    if (!this.canvas || !this.audioElement) {
      console.warn("[AudioVisualizer] Canvas or audio element not provided");
      return false;
    }

    this._setupResizeObserver();
    this._resizeCanvas();

    return true;
  }

  // connect web audio nodes once user initiates playback
  setupAudioNodes() {
    if (this.isInitialized && this.analyser) {
      return true;
    }

    try {
      const AudioCtxClass = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtxClass) {
        console.warn("[AudioVisualizer] Web Audio API not supported");
        return false;
      }

      if (!window.__pylive_audio_ctx) {
        window.__pylive_audio_ctx = new AudioCtxClass();
      }
      this.audioContext = window.__pylive_audio_ctx;

      if (!this.analyser) {
        this.analyser = this.audioContext.createAnalyser();
        this.analyser.fftSize = this.fftSize;
        this.analyser.smoothingTimeConstant = this.smoothingTimeConstant;
        this.analyser.minDecibels = this.minDecibels;
        this.analyser.maxDecibels = this.maxDecibels;
      }

      if (!this.sourceNode && this.audioElement) {
        if (!window.__pylive_audio_source) {
          window.__pylive_audio_source =
            this.audioContext.createMediaElementSource(this.audioElement);
        }
        this.sourceNode = window.__pylive_audio_source;
        this.sourceNode.connect(this.analyser);
        this.analyser.connect(this.audioContext.destination);
      }

      this.frequencyData = new Uint8Array(this.analyser.frequencyBinCount);
      this.timeDomainData = new Uint8Array(this.analyser.frequencyBinCount);
      this.isInitialized = true;

      return true;
    } catch (err) {
      console.error("[AudioVisualizer] Error setting up audio nodes:", err);
      return false;
    }
  }

  start() {
    if (this.isRunning) return;

    if (!this.isInitialized) {
      const ok = this.setupAudioNodes();
      if (!ok) return;
    }

    if (this.audioContext && this.audioContext.state === "suspended") {
      this.audioContext.resume().catch((err) => {
        console.warn("[AudioVisualizer] Could not resume audio context:", err);
      });
    }

    this.isRunning = true;
    this.lastFrameTime = performance.now();
    this._renderLoop();
  }

  pause() {
    this.isRunning = false;
    if (this.animationId) {
      cancelAnimationFrame(this.animationId);
      this.animationId = null;
    }
    this._clearCanvas();
  }

  setMode(mode) {
    if (Object.values(AudioVisualizer.MODES).includes(mode)) {
      this.mode = mode;
    }
  }

  setTheme(themeName) {
    if (AudioVisualizer.THEMES[themeName]) {
      this.themeName = themeName;
    }
  }

  setBarCount(count) {
    const num = Math.min(Math.max(parseInt(count, 10) || 48, 16), 256);
    this.barCount = num;
  }

  setFftSize(size) {
    const num = parseInt(size, 10);
    const validSizes = [256, 512, 1024, 2048, 4096, 8192];
    if (validSizes.includes(num)) {
      this.fftSize = num;
      if (this.analyser) {
        this.analyser.fftSize = num;
        this.frequencyData = new Uint8Array(this.analyser.frequencyBinCount);
        this.timeDomainData = new Uint8Array(this.analyser.frequencyBinCount);
      }
    }
  }

  setSensitivity(val) {
    const num = Math.min(Math.max(parseFloat(val), 0.1), 0.98);
    this.smoothingTimeConstant = num;
    if (this.analyser) {
      this.analyser.smoothingTimeConstant = num;
    }
  }

  setMinDecibels(val) {
    const num = Math.min(Math.max(parseFloat(val), -100), -35);
    this.minDecibels = num;
    if (this.analyser) {
      this.analyser.minDecibels = num;
    }
  }

  setMaxDecibels(val) {
    const num = Math.min(Math.max(parseFloat(val), -60), -5);
    this.maxDecibels = num;
    if (this.analyser) {
      this.analyser.maxDecibels = num;
    }
  }

  setThickness(val) {
    this.thickness = Math.max(parseFloat(val) || 1, 0.5);
  }

  setMultiplier(val) {
    this.multiplier = Math.max(parseFloat(val) || 1, 0.1);
  }

  setFps(val) {
    this.fps = Math.max(parseInt(val, 10) || 30, 15);
  }

  // internal loop with fps throttling
  _renderLoop(timestamp = performance.now()) {
    if (!this.isRunning) return;

    this.animationId = requestAnimationFrame((ts) => this._renderLoop(ts));

    const elapsed = timestamp - this.lastFrameTime;
    const interval = 1000 / this.fps;

    if (elapsed < interval) return;
    this.lastFrameTime = timestamp - (elapsed % interval);

    this._drawFrame();
  }

  _drawFrame() {
    if (!this.ctx || !this.canvas || !this.analyser) return;

    const width = this.canvas.width;
    const height = this.canvas.height;
    if (width === 0 || height === 0) return;

    this.ctx.clearRect(0, 0, width, height);

    const theme =
      AudioVisualizer.THEMES[this.themeName] || AudioVisualizer.THEMES.cyan;

    switch (this.mode) {
      case AudioVisualizer.MODES.WAVEFORM:
        this._renderWaveform(width, height, theme);
        break;
      case AudioVisualizer.MODES.SYMMETRIC:
        this._renderSymmetric(width, height, theme);
        break;
      case AudioVisualizer.MODES.ROUND_BARS:
        this._renderRoundBars(width, height, theme);
        break;
      case AudioVisualizer.MODES.BARS:
      default:
        this._renderBars(width, height, theme);
        break;
    }
  }

  // frequency bars with solid color
  _renderBars(width, height, theme) {
    this.analyser.getByteFrequencyData(this.frequencyData);

    const count = this.barCount;
    const totalGap = width * 0.22;
    const gap = totalGap / (count - 1);
    const barWidth = (width - totalGap) / count;
    const step = Math.floor(this.frequencyData.length / (count * 1.5)) || 1;

    this.ctx.fillStyle = theme.color;

    for (let i = 0; i < count; i++) {
      const dataIndex = Math.min(i * step, this.frequencyData.length - 1);
      const rawValue = (this.frequencyData[dataIndex] / 255) * this.multiplier;
      const barHeight = Math.max(rawValue * height * 0.95, 2);
      const x = i * (barWidth + gap);
      const y = height - barHeight;

      this._drawRoundedRect(
        this.ctx,
        x,
        y,
        barWidth,
        barHeight,
        Math.min(barWidth / 2, 3),
      );
    }
  }

  // oscilloscope waveform with solid line stroke
  _renderWaveform(width, height, theme) {
    this.analyser.getByteTimeDomainData(this.timeDomainData);

    this.ctx.lineWidth = this.thickness * (window.devicePixelRatio || 1);
    this.ctx.strokeStyle = theme.color;

    this.ctx.beginPath();
    const sliceWidth = width / this.timeDomainData.length;
    let x = 0;

    for (let i = 0; i < this.timeDomainData.length; i++) {
      const v = (this.timeDomainData[i] / 128.0 - 1.0) * this.multiplier + 1.0;
      const y = (v * height) / 2;

      if (i === 0) {
        this.ctx.moveTo(x, y);
      } else {
        this.ctx.lineTo(x, y);
      }
      x += sliceWidth;
    }

    this.ctx.stroke();
  }

  // symmetric center-out frequency spectrum with solid color
  _renderSymmetric(width, height, theme) {
    this.analyser.getByteFrequencyData(this.frequencyData);

    const count = Math.floor(this.barCount * 0.7);
    const barWidth = Math.max((width / (count * 2)) * 0.7, 2);
    const step = Math.floor(this.frequencyData.length / (count * 1.4)) || 1;
    const centerX = width / 2;
    const centerY = height / 2;

    this.ctx.fillStyle = theme.color;

    for (let i = 0; i < count; i++) {
      const dataIndex = Math.min(i * step, this.frequencyData.length - 1);
      const rawValue = (this.frequencyData[dataIndex] / 255) * this.multiplier;
      const barHeight = Math.max(rawValue * (height * 0.45), 2);
      const offset = i * (barWidth * 1.5);

      // right side
      this._drawRoundedRect(
        this.ctx,
        centerX + offset,
        centerY - barHeight,
        barWidth,
        barHeight * 2,
        barWidth / 2,
      );

      // left side
      if (i > 0) {
        this._drawRoundedRect(
          this.ctx,
          centerX - offset,
          centerY - barHeight,
          barWidth,
          barHeight * 2,
          barWidth / 2,
        );
      }
    }
  }

  // round pill bars with solid floating peak caps
  _renderRoundBars(width, height, theme) {
    this.analyser.getByteFrequencyData(this.frequencyData);

    const count = Math.floor(this.barCount * 0.65);
    const totalGap = width * 0.3;
    const gap = totalGap / (count - 1);
    const barWidth = (width - totalGap) / count;
    const step = Math.floor(this.frequencyData.length / (count * 1.6)) || 1;

    for (let i = 0; i < count; i++) {
      const dataIndex = Math.min(i * step, this.frequencyData.length - 1);
      const rawValue = (this.frequencyData[dataIndex] / 255) * this.multiplier;
      const barHeight = Math.max(rawValue * (height - 12), 4);
      const x = i * (barWidth + gap);
      const y = height - barHeight;

      // solid body
      this.ctx.fillStyle = theme.color;
      this._drawRoundedRect(this.ctx, x, y, barWidth, barHeight, barWidth / 2);

      // solid cap
      if (barHeight > 8) {
        this.ctx.fillStyle = theme.cap;
        this._drawRoundedRect(this.ctx, x, y - 5, barWidth, 2.5, 1.25);
      }
    }
  }

  _drawRoundedRect(ctx, x, y, w, h, radius) {
    const r = Math.min(radius, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h - r);
    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
    ctx.fill();
  }

  _clearCanvas() {
    if (this.ctx && this.canvas) {
      this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    }
  }

  _setupResizeObserver() {
    if (typeof ResizeObserver === "undefined" || !this.canvas) return;

    this.resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        if (entry.contentRect) {
          this._resizeCanvasWithDimensions(
            entry.contentRect.width,
            entry.contentRect.height,
          );
        }
      }
    });
    this.resizeObserver.observe(this.canvas);
  }

  _resizeCanvasWithDimensions(width, height) {
    if (!this.canvas) return;
    const dpr = window.devicePixelRatio || 1;
    const displayWidth = Math.floor(width) || 640;
    const displayHeight = Math.floor(height) || 120;

    if (displayHeight <= 0) return;

    const targetWidth = Math.floor(displayWidth * dpr);
    const targetHeight = Math.floor(displayHeight * dpr);

    if (
      this.canvas.width !== targetWidth ||
      this.canvas.height !== targetHeight
    ) {
      this.canvas.width = targetWidth;
      this.canvas.height = targetHeight;
    }
  }

  _resizeCanvas() {
    if (!this.canvas) return;
    const rect = this.canvas.getBoundingClientRect();
    this._resizeCanvasWithDimensions(rect.width, rect.height);
  }

  destroy() {
    this.pause();
    if (this.resizeObserver) {
      this.resizeObserver.disconnect();
      this.resizeObserver = null;
    }
    this.isInitialized = false;
  }
}
