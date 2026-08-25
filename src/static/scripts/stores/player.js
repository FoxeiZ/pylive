import Alpine from "../vendor/alpine.esm.min.js";
import { AudioVisualizer } from "../dist/visualizer.js";
import { formatTime, THEME_ACCENTS } from "../utils/format.js";

const FFT_SIZES = [256, 512, 1024, 2048, 4096, 8192];

export const playerStore = {
  // playback state
  isPlaying: false,
  isMuted: false,
  volume: 0.8,
  currentDuration: 0,
  durationInterval: null,

  // synchronization state
  startedAt: 0,
  trackDuration: 0,
  isPaused: false,
  serverTimeOffset: 0, // client_time - server_time
  syncInterval: null,
  isAdvancing: false,

  // visualizer toggle
  showVisualizer: true,

  // track and queue state
  nowPlaying: {
    title: "Waiting for stream...",
    artist: "Unknown",
    source_url: "#",
    artwork_url: "",
    duration: 0,
    stream_url: "",
  },
  queue: [],
  autoQueue: [],
  activeQueueTab: "queue",

  // ui panel states
  isSettingsOpen: false,
  newTrackUrl: "",
  isSubmittingTrack: false,
  isSkippingTrack: false,
  isRefreshingAutoplay: false,

  // connectivity and notifications
  sseStatus: "connecting",
  realtimeClient: null,
  realtimeChannel: null,
  pollTimer: null,
  toasts: [],
  toastCounter: 0,

  // visualizer instance and configuration
  visualizer: null,
  visualizerSettings: {
    mode: "bars",
    theme: "cyan",
    barCount: 48,
    fftSize: 1024,
    sensitivity: 0.8,
    minDecibels: -85,
    maxDecibels: -20,
    fps: 60,
    thickness: 2,
    multiplier: 1.0,
  },

  sliderConfigs: [
    {
      key: "barCount",
      label: "BAR DENSITY",
      unit: "BARS",
      min: 16,
      max: 256,
      step: 4,
      disabledIn: ["waveform"],
    },
    {
      key: "sensitivity",
      label: "SMOOTHING CONSTANT",
      unit: "",
      min: 0.1,
      max: 0.95,
      step: 0.01,
      disabledIn: ["waveform"],
    },
    {
      key: "fftSize",
      label: "FFT SIZE",
      unit: "",
      min: 0,
      max: FFT_SIZES.length - 1,
      step: 1,
      options: FFT_SIZES,
      disabledIn: [],
    },
    {
      key: "multiplier",
      label: "GAIN MULTIPLIER",
      unit: "X",
      min: 0.4,
      max: 2.5,
      step: 0.1,
      disabledIn: [],
    },
    {
      key: "minDecibels",
      label: "MIN DECIBELS",
      unit: "dB",
      min: -120,
      max: -30,
      step: 1,
      disabledIn: [],
    },
    {
      key: "maxDecibels",
      label: "MAX DECIBELS",
      unit: "dB",
      min: -40,
      max: 0,
      step: 1,
      disabledIn: [],
    },
    {
      key: "fps",
      label: "FRAME RATE",
      unit: "FPS",
      min: 30,
      max: 144,
      step: 1,
      disabledIn: [],
    },
    {
      key: "thickness",
      label: "LINE THICKNESS",
      unit: "PX",
      min: 1,
      max: 6,
      step: 0.5,
      disabledIn: ["bars"],
    },
  ],

  get formattedDuration() {
    return formatTime(this.currentDuration);
  },

  get formattedTotalDuration() {
    return formatTime(this.nowPlaying.duration || 0);
  },

  getSliderValue(item) {
    if (item.key === "fftSize") {
      const idx = item.options.indexOf(this.visualizerSettings[item.key]);
      return idx !== -1 ? idx : item.options.indexOf(1024);
    }
    return this.visualizerSettings[item.key];
  },

  get progressPercent() {
    if (this.nowPlaying && this.nowPlaying.duration && this.nowPlaying.duration > 0) {
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
      this._setupRealtime();
      this._setupVisualizer();
      this._startSyncLoop();
      Alpine.store("auth").fetchAuthStatus();
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
        const parsed = JSON.parse(savedSettings);
        if (parsed.fftSize && !FFT_SIZES.includes(parseInt(parsed.fftSize, 10))) {
          delete parsed.fftSize;
        } else if (parsed.fftSize) {
          parsed.fftSize = parseInt(parsed.fftSize, 10);
        }
        this.visualizerSettings = {
          ...this.visualizerSettings,
          ...parsed,
        };
      }
    } catch (err) {
      console.warn("failed to load preferences", err);
    }
  },

  _savePreferences() {
    try {
      localStorage.setItem("pylive_volume", this.volume.toString());
      localStorage.setItem("pylive_show_viz", this.showVisualizer.toString());
      localStorage.setItem("pylive_viz_settings", JSON.stringify(this.visualizerSettings));
    } catch (err) {
      console.warn("failed to save preferences", err);
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
          if (initial.np.stream_url) {
            this._applyTrackData(initial.np);
          }
        }
        if (Array.isArray(initial.queue)) {
          this.queue = initial.queue;
        }
        if (Array.isArray(initial.auto_queue)) {
          this.autoQueue = initial.auto_queue;
        }
        if (initial.user) {
          Alpine.store("auth").setUser(initial.user);
        }
      } catch (err) {
        console.error("failed to parse initial SSR state", err);
      }
    }
    // fetch authoritative room state from api
    this.fetchRoomState();
  },

  _setupAudioElement() {
    const audio = document.getElementById("audio-stream-player");
    if (!audio) return;

    audio.volume = this.volume;
    audio.muted = this.isMuted;
    audio.crossOrigin = "anonymous";

    audio.addEventListener("playing", () => {
      this.isPlaying = true;
      if (this.visualizer && this.showVisualizer) {
        this.visualizer.start();
      }
    });

    audio.addEventListener("pause", () => {
      this.isPlaying = false;
      if (this.visualizer) {
        this.visualizer.pause();
      }
    });

    audio.addEventListener("ended", () => {
      this.triggerTrackAdvance();
    });

    audio.addEventListener("error", (e) => {
      console.error("audio stream error", e);
      this.isPlaying = false;
      if (this.visualizer) {
        this.visualizer.pause();
      }
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
      fftSize: this.visualizerSettings.fftSize,
    });

    this.visualizer.init(audio, canvas);
  },

  _setupRealtime() {
    const config = window.__PYLIVE_CONFIG__ || {};
    if (window.supabase && config.supabaseUrl && config.supabaseKey) {
      try {
        this.realtimeClient = window.supabase.createClient(config.supabaseUrl, config.supabaseKey);
        this.realtimeChannel = this.realtimeClient
          .channel("realtime:main")
          .on("broadcast", { event: "track_change" }, (payload) => {
            this._handleTrackChangeEvent(payload.payload);
          })
          .on("broadcast", { event: "playback_sync" }, (payload) => {
            this._handlePlaybackSyncEvent(payload.payload);
          })
          .on("broadcast", { event: "queue_update" }, () => {
            this.fetchQueue();
          })
          .subscribe((status) => {
            if (status === "SUBSCRIBED") {
              this.sseStatus = "connected";
            } else if (status === "CLOSED" || status === "CHANNEL_ERROR") {
              this.sseStatus = "disconnected";
            }
          });
        return;
      } catch (err) {
        console.warn("supabase realtime initialization failed, falling back to polling", err);
      }
    }

    // fallback polling if supabase is not configured
    this.sseStatus = "connected";
    this.pollTimer = setInterval(() => {
      this.fetchRoomState();
    }, 5000);
  },

  _startSyncLoop() {
    if (this.syncInterval) clearInterval(this.syncInterval);
    this.syncInterval = setInterval(() => {
      this.syncDrift();
    }, 1000);
  },

  syncDrift() {
    const audio = document.getElementById("audio-stream-player");
    if (!audio || this.isPaused || !this.startedAt || !this.nowPlaying.stream_url) {
      if (audio && !audio.paused && (!this.nowPlaying.stream_url || this.isPaused)) {
        audio.pause();
      }
      return;
    }

    const currentServerTime = Date.now() - this.serverTimeOffset;
    const elapsedSeconds = Math.max(0, (currentServerTime - this.startedAt) / 1000);
    this.currentDuration = Math.floor(elapsedSeconds);

    // track finished detection
    if (this.trackDuration > 0 && elapsedSeconds >= this.trackDuration) {
      this.triggerTrackAdvance();
      return;
    }

    if (audio.paused && !this.isPaused && audio.src) {
      audio.play().catch(() => {});
    }

    const actualTime = audio.currentTime;
    const drift = elapsedSeconds - actualTime;

    if (Math.abs(drift) > 2.0) {
      audio.currentTime = elapsedSeconds;
      audio.playbackRate = 1.0;
    } else if (drift > 0.3) {
      audio.playbackRate = 1.05;
    } else if (drift < -0.3) {
      audio.playbackRate = 0.95;
    } else {
      audio.playbackRate = 1.0;
    }
  },

  async triggerTrackAdvance() {
    if (this.isAdvancing) return;
    this.isAdvancing = true;
    try {
      await fetch("/api/room/advance", { method: "POST" });
    } catch (err) {
      console.warn("advance request failed", err);
    } finally {
      setTimeout(() => {
        this.isAdvancing = false;
      }, 2000);
    }
  },

  _applyTrackData(data) {
    const audio = document.getElementById("audio-stream-player");
    this.nowPlaying = {
      title: data.title || "Unknown Track",
      artist: data.artist || "Unknown Artist",
      duration: Number(data.duration || 0),
      stream_url: data.stream_url || "",
      artwork_url: data.artwork_url || "",
      source_url: data.source_url || "#",
    };
    this.startedAt = Number(data.started_at || Date.now());
    this.trackDuration = Number(data.duration || 0);
    this.isPaused = Boolean(data.is_paused);

    if (data.server_time) {
      this.serverTimeOffset = Date.now() - Number(data.server_time);
    }

    document.title = `${this.nowPlaying.title} - PyLive`;

    if (audio && data.stream_url) {
      if (audio.src !== data.stream_url) {
        audio.crossOrigin = "anonymous";
        audio.src = data.stream_url;
        const currentServerTime = Date.now() - this.serverTimeOffset;
        const elapsed = Math.max(0, (currentServerTime - this.startedAt) / 1000);
        audio.currentTime = elapsed;
        if (!this.isPaused) {
          audio.play().catch(() => {
            this.addToast("Click anywhere to enable audio playback", "info");
          });
        }
      }
    }
  },

  _handleTrackChangeEvent(data) {
    if (!data) return;
    this._applyTrackData(data);
    this.fetchQueue();
    if (data.title) {
      this.addToast(`Now Playing: ${data.title}`, "info");
    }
  },

  _handlePlaybackSyncEvent(data) {
    if (!data) return;
    this.isPaused = Boolean(data.is_paused);
    const audio = document.getElementById("audio-stream-player");
    if (!audio) return;

    if (data.server_time) {
      this.serverTimeOffset = Date.now() - Number(data.server_time);
    }

    if (this.isPaused) {
      audio.pause();
    } else {
      if (data.position !== undefined) {
        audio.currentTime = Number(data.position);
      }
      audio.play().catch(() => {});
    }
  },

  async fetchRoomState() {
    try {
      const res = await fetch("/api/room/state");
      if (!res.ok) return;
      const json = await res.json();
      if (json.data && json.data.now_playing) {
        const np = json.data.now_playing;
        np.server_time = json.data.server_time;
        this._applyTrackData(np);
      }
    } catch (err) {
      console.warn("failed to fetch room state", err);
    }
  },

  togglePlay() {
    const audio = document.getElementById("audio-stream-player");
    if (!audio) return;

    if (this.isPlaying) {
      audio.pause();
    } else if (this.nowPlaying.stream_url) {
      audio.play().catch(() => {
        this.addToast("Click to enable audio playback", "info");
      });
    }
  },

  toggleVisualizer() {
    this.showVisualizer = !this.showVisualizer;
    this._savePreferences();

    if (!this.visualizer) return;
    if (this.showVisualizer && this.isPlaying) {
      setTimeout(() => this.visualizer.start(), 150);
    } else {
      this.visualizer.pause();
    }
  },

  setQueueTab(tab) {
    this.activeQueueTab = tab;
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
      console.warn("error fetching queue", err);
    }
  },

  async addToQueue() {
    const authStore = Alpine.store("auth");
    if (!authStore.hasPermission("queue:add")) {
      if (!authStore.isAuthenticated) {
        this.addToast("Please login to queue tracks", "info");
        authStore.openLoginModal();
      } else {
        this.addToast("Permission denied: queue:add required", "error");
      }
      return;
    }

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
      console.error("error adding track", err);
      this.addToast("Network error while adding track", "error");
    } finally {
      this.isSubmittingTrack = false;
    }
  },

  async voteSkip() {
    const authStore = Alpine.store("auth");
    if (!authStore.hasPermission("queue:skip_vote")) {
      if (!authStore.isAuthenticated) {
        this.addToast("Please login to skip tracks", "info");
        authStore.openLoginModal();
      } else {
        this.addToast("Permission denied: queue:skip_vote required", "error");
      }
      return;
    }

    if (this.isSkippingTrack) return;
    this.isSkippingTrack = true;

    try {
      const res = await fetch("/queue/skip", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });

      const data = await res.json();
      if (res.ok && data.msg === "success") {
        this.addToast("Track skipped", "info");
      } else {
        this.addToast(data.msg || "Skip request failed", "error");
      }
    } catch (err) {
      console.error("error skipping track", err);
      this.addToast("Network error during skip", "error");
    } finally {
      setTimeout(() => {
        this.isSkippingTrack = false;
      }, 1500);
    }
  },

  async refreshAutoplayQueue() {
    if (this.isRefreshingAutoplay) return;
    this.isRefreshingAutoplay = true;
    try {
      await this.fetchQueue();
      this.addToast("Autoplay queue refreshed", "success");
    } finally {
      this.isRefreshingAutoplay = false;
    }
  },

  updateVisualizer(key, val) {
    if (key === "fftSize") {
      const parsed = parseInt(val, 10);
      const fftConfig = this.sliderConfigs.find((c) => c.key === "fftSize");
      const targetSize =
        fftConfig && fftConfig.options && fftConfig.options[parsed] !== undefined
          ? fftConfig.options[parsed]
          : FFT_SIZES.includes(parsed)
            ? parsed
            : 1024;
      this.visualizerSettings.fftSize = targetSize;
      if (this.visualizer) {
        this.visualizer.setFftSize(targetSize);
      }
    } else {
      this.visualizerSettings[key] = val;
      if (this.visualizer) {
        if (key === "mode") this.visualizer.setMode(val);
        if (key === "theme") this.visualizer.setTheme(val);
        if (key === "barCount") this.visualizer.setBarCount(val);
        if (key === "sensitivity") this.visualizer.setSensitivity(val);
        if (key === "minDecibels") this.visualizer.setMinDecibels(val);
        if (key === "maxDecibels") this.visualizer.setMaxDecibels(val);
        if (key === "thickness") this.visualizer.setThickness(val);
        if (key === "multiplier") this.visualizer.setMultiplier(val);
        if (key === "fps") this.visualizer.setFps(val);
      }
    }

    this._savePreferences();
    if (key === "theme") {
      this._applyGlobalAccent();
    }
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
};
