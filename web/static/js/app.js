/* ==========================================================================
   Outpost Conduit — Core SPA Framework
   ========================================================================== */

/* ---------- Auth ---------- */
const Auth = {
  getToken()  { return localStorage.getItem('token'); },
  setToken(t) { localStorage.setItem('token', t); },
  clearToken() { localStorage.removeItem('token'); },
  isLoggedIn() { return !!this.getToken(); },
  logout() {
    this.clearToken();
    window.location.href = '/login';
  },
};

/* ---------- API Helper ---------- */
const Api = {
  /**
   * Make an authenticated API request.
   * Automatically redirects to /login on 401.
   */
  async request(method, path, body) {
    const opts = {
      method,
      headers: {
        'Authorization': 'Bearer ' + Auth.getToken(),
      },
    };

    if (body !== undefined && body !== null) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }

    const resp = await fetch(path, opts);

    if (resp.status === 401) {
      Auth.logout();
      return null;
    }

    if (resp.status === 204) {
      return null;
    }

    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      throw new Error(data.detail || `Request failed (${resp.status})`);
    }

    return resp.json();
  },

  get(path) { return this.request('GET', path); },
  post(path, body) { return this.request('POST', path, body); },
  put(path, body) { return this.request('PUT', path, body); },
  del(path) { return this.request('DELETE', path); },
};

/* ---------- Router ---------- */
const Router = {
  _routes: {},
  _current: null,

  /**
   * Register a view: Router.on('dashboard', { render(container) { ... } })
   */
  on(name, view) {
    this._routes[name] = view;
  },

  /**
   * Navigate to a view by name.
   */
  navigate(name) {
    if (!this._routes[name]) name = 'dashboard';
    window.location.hash = '#' + name;
  },

  /**
   * Resolve the current hash and render the matching view.
   */
  resolve() {
    const rawHash = window.location.hash.replace('#', '') || 'dashboard';
    // Strip query params — e.g. "deploy?site=X" → "deploy"
    const hash = rawHash.split('?')[0];
    const view = this._routes[hash];

    if (!view) {
      this.navigate('dashboard');
      return;
    }

    // Don't re-render if we're already on this view
    if (this._current === rawHash) return;

    // Clean up previous view's stats listener
    if (this._currentView && typeof this._currentView.cleanup === 'function') {
      this._currentView.cleanup();
    }

    this._current = rawHash;
    this._currentView = view;

    // Update active nav link
    document.querySelectorAll('.nav-link').forEach((link) => {
      const linkView = link.dataset.view;
      link.classList.toggle('active', linkView === hash);
    });

    // Render into content container
    const container = document.getElementById('content');
    if (container && typeof view.render === 'function') {
      view.render(container);
    }
  },

  /**
   * Initialize the router — listen for hash changes.
   */
  init() {
    window.addEventListener('hashchange', () => this.resolve());
    this.resolve();
  },
};

/* ---------- WebSocket Manager ---------- */
const WS = {
  _ws: null,
  _onMessage: null,
  _reconnectTimer: null,
  _reconnectDelay: 1000,
  _maxDelay: 30000,

  /**
   * Connect to the stats WebSocket.
   */
  connect(onMessage) {
    this._onMessage = onMessage;
    this._doConnect();
  },

  _doConnect() {
    if (this._ws) {
      try { this._ws.close(); } catch (_) { /* ignore */ }
    }

    const token = Auth.getToken();
    if (!token) return;

    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${proto}//${window.location.host}/api/ws/stats?token=${encodeURIComponent(token)}`;

    this._ws = new WebSocket(url);

    this._ws.onopen = () => {
      this._reconnectDelay = 1000;
    };

    this._ws.onmessage = (event) => {
      if (this._onMessage) {
        try {
          const data = JSON.parse(event.data);
          this._onMessage(data);
        } catch (_) { /* ignore parse errors */ }
      }
    };

    this._ws.onclose = () => {
      this._scheduleReconnect();
    };

    this._ws.onerror = () => {
      // onerror is always followed by onclose, which handles reconnect
    };
  },

  _scheduleReconnect() {
    if (this._reconnectTimer) return;
    this._reconnectTimer = setTimeout(() => {
      this._reconnectTimer = null;
      if (Auth.isLoggedIn()) {
        this._reconnectDelay = Math.min(this._reconnectDelay * 2, this._maxDelay);
        this._doConnect();
      }
    }, this._reconnectDelay);
  },

  /**
   * Disconnect and stop reconnecting.
   */
  disconnect() {
    if (this._reconnectTimer) {
      clearTimeout(this._reconnectTimer);
      this._reconnectTimer = null;
    }
    if (this._ws) {
      try { this._ws.close(); } catch (_) { /* ignore */ }
      this._ws = null;
    }
  },

  /**
   * Force reconnect now.
   */
  reconnect() {
    this.disconnect();
    this._reconnectDelay = 1000;
    if (Auth.isLoggedIn()) {
      this._doConnect();
    }
  },
};

/* ---------- Utility Functions ---------- */
const Utils = {
  /**
   * Format a byte count into a human-readable string.
   */
  formatBytes(n) {
    if (n === null || n === undefined) return '—';
    if (n === 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    const k = 1024;
    const i = Math.floor(Math.log(n) / Math.log(k));
    const val = n / Math.pow(k, i);
    return val.toFixed(i === 0 ? 0 : 1) + ' ' + units[i];
  },

  /**
   * Given a Unix timestamp (seconds), return a human-readable age string.
   */
  formatAge(timestamp) {
    if (!timestamp) return '—';
    const seconds = Math.floor(Date.now() / 1000 - timestamp);
    return this.timeAgo(seconds);
  },

  /**
   * Convert seconds into a human-readable "time ago" string.
   */
  timeAgo(seconds) {
    if (seconds < 0) seconds = 0;
    if (seconds < 60) return seconds + 's ago';
    if (seconds < 3600) return Math.floor(seconds / 60) + 'm ago';
    if (seconds < 86400) return Math.floor(seconds / 3600) + 'h ago';
    return Math.floor(seconds / 86400) + 'd ago';
  },

  /**
   * Escape HTML entities in a string.
   */
  escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  },
};

/* ---------- Shared State ---------- */
// Latest stats from WebSocket — views can read this.
window._latestStats = null;

/* ---------- Initialization ---------- */
document.addEventListener('DOMContentLoaded', () => {
  // Auth check
  if (!Auth.isLoggedIn()) {
    window.location.href = '/login';
    return;
  }

  // Logout button
  const logoutBtn = document.getElementById('logoutBtn');
  if (logoutBtn) {
    logoutBtn.addEventListener('click', () => Auth.logout());
  }

  // Show hub hostname
  const hubEl = document.getElementById('hubInfo');
  if (hubEl) {
    hubEl.textContent = 'hub: ' + window.location.hostname;
  }

  // Register views (stubs set their view objects on window)
  if (window.DashboardView) Router.on('dashboard', window.DashboardView);
  if (window.SitesView)     Router.on('sites', window.SitesView);
  if (window.DeployView)    Router.on('deploy', window.DeployView);
  if (window.DiagnosticsView) Router.on('diagnostics', window.DiagnosticsView);
  if (window.SettingsView) Router.on('settings', window.SettingsView);

  // Start router
  Router.init();

  // Connect WebSocket — broadcast to current view
  WS.connect((data) => {
    window._latestStats = data;
    // Dispatch a custom event so views can listen
    window.dispatchEvent(new CustomEvent('stats-update', { detail: data }));
  });
});
