import Alpine from "./vendor/alpine.esm.min.js";
import { AudioVisualizer } from "./visualizer.js";

const THEME_ACCENTS = {
  cyan: "#06b6d4",
  emerald: "#10b981",
  violet: "#8b5cf6",
  amber: "#f59e0b",
  coral: "#f43f5e",
  monochrome: "#f1f5f9",
};

function formatTime(totalSeconds) {
  if (!totalSeconds || totalSeconds < 0) return "00:00";
  const sec = Math.floor(totalSeconds);
  const hours = Math.floor(sec / 3600);
  const minutes = Math.floor((sec % 3600) / 60);
  const remainingSeconds = sec % 60;

  const mm = minutes.toString().padStart(2, "0");
  const ss = remainingSeconds.toString().padStart(2, "0");

  if (hours > 0) {
    return `${hours}:${mm}:${ss}`;
  }
  return `${mm}:${ss}`;
}

Alpine.store("player", {
  // playback state
  isPlaying: false,
  isMuted: false,
  volume: 0.8,
  currentDuration: 0,
  durationInterval: null,

  // visualizer toggle & display
  showVisualizer: true,

  // track & queue state
  nowPlaying: {
    title: "Waiting for stream...",
    channel: "Unknown",
    webpage_url: "#",
    channel_url: "#",
    duration: 0,
  },
  queue: [],
  autoQueue: [],
  activeQueueTab: "queue",

  // ui panel states
  isSettingsOpen: false,
  newTrackUrl: "",
  isSubmittingTrack: false,
  isSkippingTrack: false,

  // connectivity and notifications
  sseStatus: "connecting",
  eventSource: null,
  reconnectTimer: null,
  toasts: [],
  toastCounter: 0,

  // visualizer instance and configuration
  visualizer: null,
  visualizerSettings: {
    mode: "bars",
    theme: "cyan",
    barCount: 48,
    sensitivity: 0.8,
    minDecibels: -85,
    maxDecibels: -20,
    fps: 60,
    thickness: 2,
    multiplier: 1.0,
  },

  get formattedDuration() {
    return formatTime(this.currentDuration);
  },

  get formattedTotalDuration() {
    if (
      this.nowPlaying &&
      this.nowPlaying.duration &&
      this.nowPlaying.duration > 0
    ) {
      return formatTime(this.nowPlaying.duration);
    }
    return "LIVE";
  },

  get progressPercent() {
    if (
      this.nowPlaying &&
      this.nowPlaying.duration &&
      this.nowPlaying.duration > 0
    ) {
      const pct = (this.currentDuration / this.nowPlaying.duration) * 100;
      return Math.min(Math.max(pct, 0), 100);
    }
    return this.isPlaying ? 100 : 0;
  },

  get totalTracksInQueue() {
    return this.queue.length;
  },

  init() {
    const start = () => {
      this._loadSavedPreferences();
      this._applyGlobalAccent();
      this._bootstrapInitialData();
      this._setupAudioElement();
      this.connectSSE();
      this._setupVisualizer();
    };

    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", start);
    } else {
      start();
    }
  },

  _loadSavedPreferences() {
    try {
      const savedVol = localStorage.getItem("pylive_volume");
      if (savedVol !== null) {
        this.volume = parseFloat(savedVol);
      }
      const savedShowViz = localStorage.getItem("pylive_show_viz");
      if (savedShowViz !== null) {
        this.showVisualizer = savedShowViz === "true";
      }
      const savedSettings = localStorage.getItem("pylive_viz_settings");
      if (savedSettings) {
        this.visualizerSettings = {
          ...this.visualizerSettings,
          ...JSON.parse(savedSettings),
        };
      }
    } catch (err) {
      console.warn("Failed to load local preferences", err);
    }
  },

  _savePreferences() {
    try {
      localStorage.setItem("pylive_volume", this.volume.toString());
      localStorage.setItem("pylive_show_viz", this.showVisualizer.toString());
      localStorage.setItem(
        "pylive_viz_settings",
        JSON.stringify(this.visualizerSettings),
      );
    } catch (err) {
      console.warn("Failed to save preferences", err);
    }
  },

  _applyGlobalAccent() {
    const themeKey = this.visualizerSettings.theme || "cyan";
    const accentHex = THEME_ACCENTS[themeKey] || THEME_ACCENTS.cyan;
    document.documentElement.style.setProperty("--accent-primary", accentHex);
  },

  _bootstrapInitialData() {
    const stateEl = document.getElementById("initial-state");
    if (stateEl) {
      try {
        const initial = JSON.parse(stateEl.textContent || "{}");
        if (initial.np && initial.np.title) {
          this.nowPlaying = initial.np;
          document.title = `Playing - ${initial.np.title}`;
        }
        if (Array.isArray(initial.queue)) {
          this.queue = initial.queue;
        }
        if (Array.isArray(initial.auto_queue)) {
          this.autoQueue = initial.auto_queue;
        }
      } catch (err) {
        console.error("Failed to parse initial SSR state", err);
      }
    }
  },

  _setupAudioElement() {
    const audio = document.getElementById("audio-stream-player");
    if (!audio) return;

    audio.volume = this.volume;
    audio.muted = this.isMuted;

    audio.addEventListener("playing", () => {
      this.isPlaying = true;
      this._startDurationCounter();
      if (this.visualizer && this.showVisualizer) {
        this.visualizer.start();
      }
    });

    audio.addEventListener("pause", () => {
      this.isPlaying = false;
      this._stopDurationCounter();
      if (this.visualizer) {
        this.visualizer.pause();
      }
    });

    audio.addEventListener("error", (e) => {
      console.error("Audio stream playback error", e);
      this.isPlaying = false;
      this._stopDurationCounter();
      if (this.visualizer) {
        this.visualizer.pause();
      }
      this.addToast("Stream error encountered. Retrying...", "error");
    });
  },

  _setupVisualizer() {
    const canvas = document.getElementById("visualizer-canvas");
    const audio = document.getElementById("audio-stream-player");
    if (!canvas || !audio) return;

    this.visualizer = new AudioVisualizer({
      canvas,
      audioElement: audio,
      mode: this.visualizerSettings.mode,
      theme: this.visualizerSettings.theme,
      barCount: this.visualizerSettings.barCount,
      sensitivity: this.visualizerSettings.sensitivity,
      minDecibels: this.visualizerSettings.minDecibels,
      maxDecibels: this.visualizerSettings.maxDecibels,
      fps: this.visualizerSettings.fps,
      thickness: this.visualizerSettings.thickness,
      multiplier: this.visualizerSettings.multiplier,
    });

    this.visualizer.init(audio, canvas);
  },

  toggleVisualizer() {
    this.showVisualizer = !this.showVisualizer;
    this._savePreferences();

    if (!this.visualizer) return;

    if (this.showVisualizer) {
      if (this.isPlaying) {
        setTimeout(() => this.visualizer.start(), 150);
      }
    } else {
      this.visualizer.pause();
    }
  },

  setQueueTab(tab) {
    this.activeQueueTab = tab;
  },

  togglePlay() {
    const audio = document.getElementById("audio-stream-player");
    if (!audio) return;

    if (this.isPlaying) {
      audio.pause();
      audio.src = "";
    } else {
      audio.src = `/stream?_t=${Date.now()}`;
      audio.play().catch((err) => {
        console.warn("Playback initiation prevented", err);
        this.addToast("Click to enable audio playback", "info");
      });
    }
  },

  setVolume(value) {
    const num = Math.min(Math.max(parseFloat(value), 0), 1);
    this.volume = num;
    const audio = document.getElementById("audio-stream-player");
    if (audio) {
      audio.volume = num;
      if (num > 0 && this.isMuted) {
        this.isMuted = false;
        audio.muted = false;
      }
    }
    this._savePreferences();
  },

  toggleMute() {
    this.isMuted = !this.isMuted;
    const audio = document.getElementById("audio-stream-player");
    if (audio) {
      audio.muted = this.isMuted;
    }
  },

  _startDurationCounter() {
    this._stopDurationCounter();
    this.durationInterval = setInterval(() => {
      this.currentDuration += 1;
    }, 1000);
  },

  _stopDurationCounter() {
    if (this.durationInterval) {
      clearInterval(this.durationInterval);
      this.durationInterval = null;
    }
  },

  resetDuration() {
    this.currentDuration = 0;
  },

  connectSSE() {
    if (this.eventSource) {
      this.eventSource.close();
    }

    this.sseStatus = "connecting";
    try {
      this.eventSource = new EventSource("/watch_event");

      this.eventSource.onopen = () => {
        this.sseStatus = "connected";
      };

      this.eventSource.addEventListener("nowplaying", (e) => {
        this._handleNowPlayingEvent(e);
      });

      this.eventSource.addEventListener("queueadd", (e) => {
        this._handleQueueAddEvent(e);
      });

      this.eventSource.addEventListener("shutdown", () => {
        this.sseStatus = "disconnected";
        this.addToast("Radio stream is shutting down", "warning");
      });

      this.eventSource.onerror = (err) => {
        console.warn("EventSource disconnected, scheduling reconnect", err);
        this.sseStatus = "disconnected";
        this.eventSource.close();
        this._scheduleSSEReconnect();
      };
    } catch (err) {
      console.error("Failed to create EventSource", err);
      this.sseStatus = "disconnected";
      this._scheduleSSEReconnect();
    }
  },

  _scheduleSSEReconnect() {
    if (this.reconnectTimer) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connectSSE();
    }, 3500);
  },

  _handleNowPlayingEvent(event) {
    try {
      const data = JSON.parse(event.data);
      this.nowPlaying = data;
      this.resetDuration();
      document.title = `${data.title || "PyLive"} - PyLive`;

      // refresh full queue from api
      this.fetchQueue();
    } catch (err) {
      console.error("Error handling nowplaying event", err);
    }
  },

  _handleQueueAddEvent(event) {
    try {
      const data = JSON.parse(event.data);
      this.queue.push(data);
      this.addToast(`Queued: ${data.title || "New Track"}`, "success");
    } catch (err) {
      console.error("Error handling queueadd event", err);
    }
  },

  async fetchQueue() {
    try {
      const res = await fetch("/queue/?page=0&use_autoplay=true");
      if (!res.ok) throw new Error(`HTTP error ${res.status}`);
      const body = await res.json();
      if (body.data) {
        if (Array.isArray(body.data.queue)) {
          this.queue = body.data.queue;
        }
        if (Array.isArray(body.data.auto_queue)) {
          this.autoQueue = body.data.auto_queue;
        }
      }
    } catch (err) {
      console.warn("Error fetching queue updates", err);
    }
  },

  async addToQueue() {
    const url = this.newTrackUrl.trim();
    if (!url) return;

    this.isSubmittingTrack = true;
    try {
      const res = await fetch("/queue/add", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });

      const data = await res.json();
      if (res.ok && data.msg === "success") {
        this.newTrackUrl = "";
        this.addToast("Track added to queue", "success");
        await this.fetchQueue();
      } else {
        const msg = data.msg || "Failed to add track to queue";
        this.addToast(msg, "error");
      }
    } catch (err) {
      console.error("Error adding track", err);
      this.addToast("Network error while adding track", "error");
    } finally {
      this.isSubmittingTrack = false;
    }
  },

  async voteSkip() {
    if (this.isSkippingTrack) return;
    this.isSkippingTrack = true;

    try {
      const res = await fetch("/queue/skip", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });

      const data = await res.json();
      if (res.ok && data.msg === "success") {
        this.addToast("Vote skip recorded", "info");
      } else {
        this.addToast(data.msg || "Skip request failed", "error");
      }
    } catch (err) {
      console.error("Error skipping track", err);
      this.addToast("Network error during skip", "error");
    } finally {
      setTimeout(() => {
        this.isSkippingTrack = false;
      }, 1500);
    }
  },

  // visualizer settings updates
  updateVisualizer(key, val) {
    this.visualizerSettings[key] = val;
    this._savePreferences();

    if (key === "theme") {
      this._applyGlobalAccent();
    }

    if (!this.visualizer) return;

    if (key === "mode") this.visualizer.setMode(val);
    if (key === "theme") this.visualizer.setTheme(val);
    if (key === "barCount") this.visualizer.setBarCount(val);
    if (key === "sensitivity") this.visualizer.setSensitivity(val);
    if (key === "minDecibels") this.visualizer.setMinDecibels(val);
    if (key === "maxDecibels") this.visualizer.setMaxDecibels(val);
    if (key === "thickness") this.visualizer.setThickness(val);
    if (key === "multiplier") this.visualizer.setMultiplier(val);
    if (key === "fps") this.visualizer.setFps(val);
  },

  addToast(text, type = "info") {
    const id = ++this.toastCounter;
    this.toasts.push({ id, text, type });

    setTimeout(() => {
      this.removeToast(id);
    }, 4000);
  },

  removeToast(id) {
    this.toasts = this.toasts.filter((t) => t.id !== id);
  },
});

Alpine.data("audioDeck", () => ({
  get player() {
    return Alpine.store("player");
  },
}));

Alpine.data("queueSection", () => ({
  get player() {
    return Alpine.store("player");
  },
}));

Alpine.data("visualizerPopover", () => ({
  get player() {
    return Alpine.store("player");
  },
  modes: [
    { id: "bars", label: "Bars" },
    { id: "waveform", label: "Waveform" },
    { id: "symmetric", label: "Symmetric" },
    { id: "round_bars", label: "Pill Bars" },
  ],
  themes: [
    { id: "cyan", label: "Cyan", color: "#06b6d4" },
    { id: "emerald", label: "Emerald", color: "#10b981" },
    { id: "violet", label: "Violet", color: "#8b5cf6" },
    { id: "amber", label: "Amber", color: "#f59e0b" },
    { id: "coral", label: "Coral", color: "#f43f5e" },
    { id: "monochrome", label: "Mono", color: "#f1f5f9" },
  ],
}));

// expose alpine globally and start
window.Alpine = Alpine;
Alpine.start();
