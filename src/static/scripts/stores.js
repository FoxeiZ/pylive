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

Alpine.store("auth", {
  isAuthenticated: false,
  user: null,
  availablePermissions: [
    "queue:add",
    "queue:remove",
    "queue:skip_vote",
    "queue:skip_force",
    "queue:clear",
    "queue:autoplay_refresh",
    "admin:manage_users",
  ],

  // modal visibility
  isLoginModalOpen: false,
  isChangePasswordModalOpen: false,
  isUserMgmtModalOpen: false,
  isResetPasswordModalOpen: false,

  // forms
  loginForm: {
    username: "",
    password: "",
    error: "",
    isSubmitting: false,
  },
  changePasswordForm: {
    currentPassword: "",
    newPassword: "",
    confirmPassword: "",
    error: "",
    isSubmitting: false,
  },
  resetPasswordForm: {
    username: "",
    newPassword: "",
    error: "",
    isSubmitting: false,
  },
  createUserForm: {
    username: "",
    password: "",
    role: "user",
    permissions: ["queue:add", "queue:skip_vote"],
    error: "",
    isSubmitting: false,
  },

  // admin user list
  adminUsersList: [],
  isLoadingUsers: false,

  setUser(userData) {
    if (userData && userData.username) {
      this.user = userData;
      this.isAuthenticated = true;
    } else {
      this.user = null;
      this.isAuthenticated = false;
    }
  },

  hasPermission(perm) {
    if (!this.isAuthenticated || !this.user) return false;
    if (this.user.role === "admin") return true;
    return Array.isArray(this.user.permissions) && this.user.permissions.includes(perm);
  },

  get isAdmin() {
    return this.isAuthenticated && this.user && this.user.role === "admin";
  },

  get username() {
    return this.user ? this.user.username : "";
  },

  get role() {
    return this.user ? this.user.role : "guest";
  },

  get formattedRole() {
    return this.user && this.user.role ? `[${this.user.role.toUpperCase()}]` : "";
  },

  openLoginModal() {
    this.loginForm.error = "";
    this.loginForm.username = "";
    this.loginForm.password = "";
    this.isLoginModalOpen = true;
  },

  closeLoginModal() {
    this.isLoginModalOpen = false;
  },

  openChangePasswordModal() {
    this.changePasswordForm.error = "";
    this.changePasswordForm.currentPassword = "";
    this.changePasswordForm.newPassword = "";
    this.changePasswordForm.confirmPassword = "";
    this.isChangePasswordModalOpen = true;
  },

  closeChangePasswordModal() {
    this.isChangePasswordModalOpen = false;
  },

  async openUserMgmtModal() {
    this.isUserMgmtModalOpen = true;
    await this.fetchAdminUsers();
  },

  closeUserMgmtModal() {
    this.isUserMgmtModalOpen = false;
  },

  openResetPasswordModal(username) {
    this.resetPasswordForm.username = username;
    this.resetPasswordForm.newPassword = "";
    this.resetPasswordForm.error = "";
    this.isResetPasswordModalOpen = true;
  },

  closeResetPasswordModal() {
    this.isResetPasswordModalOpen = false;
  },

  async fetchAuthStatus() {
    try {
      const res = await fetch("/auth/status");
      if (!res.ok) return;
      const data = await res.json();
      if (data && data.data) {
        this.isAuthenticated = Boolean(data.data.authenticated);
        this.user = data.data.user || null;
        if (Array.isArray(data.data.available_permissions)) {
          this.availablePermissions = data.data.available_permissions;
        }
      }
    } catch (err) {
      console.warn("Failed to fetch auth status", err);
    }
  },

  async login() {
    const { username, password } = this.loginForm;
    if (!username.trim() || !password) {
      this.loginForm.error = "Please provide username and password";
      return;
    }

    this.loginForm.isSubmitting = true;
    this.loginForm.error = "";

    try {
      const res = await fetch("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: username.trim(), password }),
      });
      const data = await res.json();

      if (res.ok && !data.error) {
        this.setUser(data.data);
        this.closeLoginModal();
        Alpine.store("player").addToast(`Logged in as ${data.data.username}`, "success");
      } else {
        this.loginForm.error = data.msg || "Invalid username or password";
      }
    } catch (err) {
      console.error("Login request failed", err);
      this.loginForm.error = "Network error during login";
    } finally {
      this.loginForm.isSubmitting = false;
    }
  },

  async logout() {
    try {
      await fetch("/auth/logout", { method: "POST" });
      this.setUser(null);
      Alpine.store("player").addToast("Logged out", "info");
    } catch (err) {
      console.error("Logout failed", err);
    }
  },

  async changePassword() {
    const { currentPassword, newPassword, confirmPassword } = this.changePasswordForm;
    if (!currentPassword || !newPassword) {
      this.changePasswordForm.error = "All password fields are required";
      return;
    }
    if (newPassword !== confirmPassword) {
      this.changePasswordForm.error = "New passwords do not match";
      return;
    }
    if (newPassword.length < 6) {
      this.changePasswordForm.error = "New password must be at least 6 characters";
      return;
    }

    this.changePasswordForm.isSubmitting = true;
    this.changePasswordForm.error = "";

    try {
      const res = await fetch("/auth/change-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      });
      const data = await res.json();
      if (res.ok && !data.error) {
        this.closeChangePasswordModal();
        Alpine.store("player").addToast("Password changed successfully", "success");
      } else {
        this.changePasswordForm.error = data.msg || "Failed to change password";
      }
    } catch (err) {
      console.error("Change password failed", err);
      this.changePasswordForm.error = "Network error during password change";
    } finally {
      this.changePasswordForm.isSubmitting = false;
    }
  },

  async fetchAdminUsers() {
    this.isLoadingUsers = true;
    try {
      const res = await fetch("/auth/users");
      if (!res.ok) throw new Error(`HTTP error ${res.status}`);
      const data = await res.json();
      if (data.data && Array.isArray(data.data.users)) {
        this.adminUsersList = data.data.users;
      }
    } catch (err) {
      console.error("Failed to list users", err);
      Alpine.store("player").addToast("Failed to load users list", "error");
    } finally {
      this.isLoadingUsers = false;
    }
  },

  async adminCreateUser() {
    const { username, password, role, permissions } = this.createUserForm;
    if (!username.trim() || !password) {
      this.createUserForm.error = "Username and password are required";
      return;
    }

    this.createUserForm.isSubmitting = true;
    this.createUserForm.error = "";

    try {
      const res = await fetch("/auth/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: username.trim(),
          password,
          role,
          permissions,
        }),
      });
      const data = await res.json();
      if (res.ok && !data.error) {
        this.createUserForm.username = "";
        this.createUserForm.password = "";
        this.createUserForm.permissions = ["queue:add", "queue:skip_vote"];
        Alpine.store("player").addToast(`User ${username} created`, "success");
        await this.fetchAdminUsers();
      } else {
        this.createUserForm.error = data.msg || "Failed to create user";
      }
    } catch (err) {
      console.error("Failed to create user", err);
      this.createUserForm.error = "Network error creating user";
    } finally {
      this.createUserForm.isSubmitting = false;
    }
  },

  async adminDeleteUser(username) {
    if (!confirm(`Are you sure you want to delete user '${username}'?`)) return;

    try {
      const res = await fetch(`/auth/users/${encodeURIComponent(username)}`, {
        method: "DELETE",
      });
      const data = await res.json();
      if (res.ok && !data.error) {
        Alpine.store("player").addToast(`User '${username}' deleted`, "info");
        await this.fetchAdminUsers();
      } else {
        Alpine.store("player").addToast(data.msg || "Failed to delete user", "error");
      }
    } catch (err) {
      console.error("Delete user failed", err);
      Alpine.store("player").addToast("Network error deleting user", "error");
    }
  },

  async adminTogglePermission(userItem, permKey) {
    const currentPerms = new Set(userItem.permissions || []);
    if (currentPerms.has(permKey)) {
      currentPerms.delete(permKey);
    } else {
      currentPerms.add(permKey);
    }
    const updated = Array.from(currentPerms);

    try {
      const res = await fetch(`/auth/users/${encodeURIComponent(userItem.username)}/permissions`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ permissions: updated }),
      });
      const data = await res.json();
      if (res.ok && !data.error) {
        userItem.permissions = updated;
        Alpine.store("player").addToast(`Permissions updated for ${userItem.username}`, "success");
      } else {
        Alpine.store("player").addToast(data.msg || "Failed to update permissions", "error");
        await this.fetchAdminUsers();
      }
    } catch (err) {
      console.error("Failed to update user permissions", err);
      Alpine.store("player").addToast("Network error updating permissions", "error");
      await this.fetchAdminUsers();
    }
  },

  async adminResetPassword() {
    const { username, newPassword } = this.resetPasswordForm;
    if (!newPassword || newPassword.length < 6) {
      this.resetPasswordForm.error = "Password must be at least 6 characters";
      return;
    }

    this.resetPasswordForm.isSubmitting = true;
    this.resetPasswordForm.error = "";

    try {
      const res = await fetch(`/auth/users/${encodeURIComponent(username)}/reset-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ new_password: newPassword }),
      });
      const data = await res.json();
      if (res.ok && !data.error) {
        this.closeResetPasswordModal();
        Alpine.store("player").addToast(`Password reset for ${username}`, "success");
      } else {
        this.resetPasswordForm.error = data.msg || "Failed to reset password";
      }
    } catch (err) {
      console.error("Password reset failed", err);
      this.resetPasswordForm.error = "Network error resetting password";
    } finally {
      this.resetPasswordForm.isSubmitting = false;
    }
  },
});

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
  isRefreshingAutoplay: false,

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

  sliderConfigs: [
    {
      key: "barCount",
      label: "BAR DENSITY",
      unit: "BARS",
      min: 16,
      max: 96,
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
      min: -100,
      max: -40,
      step: 2,
      disabledIn: ["waveform"],
    },
    {
      key: "maxDecibels",
      label: "MAX DECIBELS",
      unit: "dB",
      min: -50,
      max: -10,
      step: 2,
      disabledIn: ["waveform"],
    },
    {
      key: "fps",
      label: "FPS CAP",
      unit: "FPS",
      min: 24,
      max: 120,
      step: 6,
      disabledIn: [],
    },
  ],

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

  formatSettingValue(item) {
    const val = this.visualizerSettings[item.key];
    if (!item.unit) return `${val}`;
    return item.unit === "X" ? `${val}X` : `${val} ${item.unit}`;
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
        if (initial.user) {
          Alpine.store("auth").setUser(initial.user);
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
      console.error("Error adding track", err);
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

  async refreshAutoplayQueue() {
    const authStore = Alpine.store("auth");
    if (!authStore.hasPermission("queue:autoplay_refresh")) {
      if (!authStore.isAuthenticated) {
        this.addToast("Please login to refresh autoplay", "info");
        authStore.openLoginModal();
      } else {
        this.addToast("Permission denied: queue:autoplay_refresh required", "error");
      }
      return;
    }

    if (this.isRefreshingAutoplay) return;
    this.isRefreshingAutoplay = true;

    try {
      const res = await fetch("/queue/autoplay/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });

      const data = await res.json();
      if (res.ok && data.msg === "success") {
        this.addToast("Autoplay queue refreshed", "success");
        await this.fetchQueue();
      } else {
        this.addToast(data.msg || "Failed to refresh autoplay queue", "error");
      }
    } catch (err) {
      console.error("Error refreshing autoplay queue", err);
      this.addToast("Network error while refreshing autoplay", "error");
    } finally {
      this.isRefreshingAutoplay = false;
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
