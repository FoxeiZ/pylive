import Alpine from "../vendor/alpine.esm.min.js";

export const authStore = {
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
};
