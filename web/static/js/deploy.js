/* ==========================================================================
   Outpost Conduit — Deploy View
   ========================================================================== */

window.DeployView = {
  _sites: [],
  _container: null,

  /* ---------- Entry Point ---------- */

  render(container) {
    this._container = container;
    container.innerHTML =
      '<div class="container">' +
        '<h2>Deploy</h2>' +
        '<p class="subtitle">Loading sites...</p>' +
      '</div>';
    this._loadSites();
  },

  /* ---------- Data Loading ---------- */

  async _loadSites() {
    try {
      this._sites = await Api.get('/api/sites') || [];
    } catch (err) {
      this._container.innerHTML =
        '<div class="container">' +
          '<h2>Deploy</h2>' +
          '<p class="subtitle" style="color:#ef4444">Failed to load sites: ' +
          Utils.escapeHtml(err.message) + '</p>' +
        '</div>';
      return;
    }
    this._renderView();
    this._applyUrlPreselect();
  },

  /* ---------- URL Hash Pre-selection ---------- */

  _applyUrlPreselect() {
    // Parse hash like #deploy?site=NAME
    var hash = window.location.hash.replace('#', '');
    var qIdx = hash.indexOf('?');
    if (qIdx === -1) return;

    var query = hash.slice(qIdx + 1);
    var params = {};
    query.split('&').forEach(function (pair) {
      var parts = pair.split('=');
      if (parts.length === 2) {
        params[decodeURIComponent(parts[0])] = decodeURIComponent(parts[1]);
      }
    });

    var siteName = params['site'];
    if (!siteName) return;

    // Check the matching checkbox
    var cb = this._container.querySelector('input[type="checkbox"][data-site="' + CSS.escape(siteName) + '"]');
    if (cb) {
      cb.checked = true;
      this._onSelectionChange();
    }
  },

  /* ---------- Main Render ---------- */

  _renderView() {
    var sites = this._sites;
    var html = '<div class="container">';
    html += '<h2>Deploy</h2>';
    html += '<p class="subtitle">Remote site management and action execution</p>';

    html += '<div class="deploy-layout">';

    // ---- Site selector panel ----
    html += '<div class="panel deploy-sites-panel">';
    html += '<div class="panel-header">';
    html += '<span class="panel-title">Select Sites</span>';
    html += '<div class="flex items-center gap-sm">';
    html += '<button class="btn btn-ghost btn-sm" id="deploySelectAll">Select All</button>';
    html += '<button class="btn btn-ghost btn-sm" id="deployDeselectAll">Deselect All</button>';
    html += '</div>';
    html += '</div>';

    html += '<div class="deploy-site-list">';

    if (sites.length === 0) {
      html += '<p style="color:#64748b;padding:1rem;font-size:0.875rem">No sites configured.</p>';
    }

    for (var i = 0; i < sites.length; i++) {
      var site = sites[i];
      var name = Utils.escapeHtml(site.name || '');
      var siteType = site.type || 'glinet';
      var tunnelIp = Utils.escapeHtml(site.tunnel_ip || '');
      var typeClass = siteType === 'cradlepoint' ? 'type-cradlepoint' : 'type-glinet';
      var typeLabel = siteType === 'cradlepoint' ? 'Cradlepoint' : 'GL.iNet';

      html += '<label class="deploy-site-item">';
      html += '<input type="checkbox" class="deploy-cb" data-site="' + name + '">';
      html += '<div class="deploy-site-info">';
      html += '<span class="deploy-site-name">' + name + '</span>';
      html += '<span class="type-tag ' + typeClass + '">' + typeLabel + '</span>';
      html += '</div>';
      html += '<span class="deploy-site-ip font-mono text-sm">' + tunnelIp + '</span>';
      html += '</label>';
    }

    html += '</div>'; // .deploy-site-list
    html += '</div>'; // .panel.deploy-sites-panel

    // ---- Action panel ----
    html += '<div class="panel deploy-action-panel">';
    html += '<div class="panel-header">';
    html += '<span class="panel-title">Remote Action</span>';
    html += '</div>';

    html += '<div style="padding:1rem;">';

    html += '<div class="form-group">';
    html += '<label for="deployAction">Action</label>';
    html += '<select id="deployAction">';
    html += '<option value="push">Push Config</option>';
    html += '<option value="setup">Run Setup</option>';
    html += '<option value="restart">Restart WireGuard</option>';
    html += '<option value="status">Check Status</option>';
    html += '<option value="reboot">Reboot</option>';
    html += '</select>';
    html += '</div>';

    html += '<button class="btn btn-primary" id="deployExecuteBtn" disabled>Execute</button>';
    html += '</div>';

    html += '</div>'; // .panel.deploy-action-panel

    html += '</div>'; // .deploy-layout

    // ---- Output log panel ----
    html += '<div class="panel" style="margin-top:1.5rem">';
    html += '<div class="panel-header">';
    html += '<span class="panel-title">Output</span>';
    html += '<button class="btn btn-ghost btn-sm" id="deployClearLog">Clear</button>';
    html += '</div>';
    html += '<div class="log-output" id="deployLog"></div>';
    html += '</div>';

    html += '</div>'; // .container

    this._container.innerHTML = html;
    this._bindEvents();
  },

  /* ---------- Event Binding ---------- */

  _bindEvents() {
    var self = this;

    // Select All
    var selectAllBtn = document.getElementById('deploySelectAll');
    if (selectAllBtn) {
      selectAllBtn.addEventListener('click', function () {
        self._container.querySelectorAll('.deploy-cb').forEach(function (cb) {
          cb.checked = true;
        });
        self._onSelectionChange();
      });
    }

    // Deselect All
    var deselectAllBtn = document.getElementById('deployDeselectAll');
    if (deselectAllBtn) {
      deselectAllBtn.addEventListener('click', function () {
        self._container.querySelectorAll('.deploy-cb').forEach(function (cb) {
          cb.checked = false;
        });
        self._onSelectionChange();
      });
    }

    // Individual checkboxes
    this._container.querySelectorAll('.deploy-cb').forEach(function (cb) {
      cb.addEventListener('change', function () {
        self._onSelectionChange();
      });
    });

    // Execute button
    var execBtn = document.getElementById('deployExecuteBtn');
    if (execBtn) {
      execBtn.addEventListener('click', function () {
        self._handleExecute();
      });
    }

    // Clear log button
    var clearBtn = document.getElementById('deployClearLog');
    if (clearBtn) {
      clearBtn.addEventListener('click', function () {
        var log = document.getElementById('deployLog');
        if (log) log.innerHTML = '';
      });
    }
  },

  /* ---------- Selection State ---------- */

  _onSelectionChange() {
    var selected = this._getSelectedSites();
    var execBtn = document.getElementById('deployExecuteBtn');
    if (execBtn) {
      execBtn.disabled = selected.length === 0;
    }
  },

  _getSelectedSites() {
    var selected = [];
    var checkboxes = this._container.querySelectorAll('.deploy-cb:checked');
    for (var i = 0; i < checkboxes.length; i++) {
      var name = checkboxes[i].getAttribute('data-site');
      for (var j = 0; j < this._sites.length; j++) {
        if (this._sites[j].name === name) {
          selected.push(this._sites[j]);
          break;
        }
      }
    }
    return selected;
  },

  /* ---------- Execute Flow ---------- */

  _handleExecute() {
    var selected = this._getSelectedSites();
    if (selected.length === 0) return;

    var action = document.getElementById('deployAction').value;

    // Destructive actions require confirmation
    var destructive = { setup: 'run setup', reboot: 'reboot' };
    if (destructive[action]) {
      this._showConfirmModal(action, selected, destructive[action]);
    } else {
      this._runActions(selected, action);
    }
  },

  /* ---------- Confirmation Modal ---------- */

  _showConfirmModal(action, selected, verb) {
    var self = this;
    var overlay = document.createElement('div');
    overlay.className = 'modal-overlay';

    var modal = document.createElement('div');
    modal.className = 'modal';

    var n = selected.length;
    var siteWord = n === 1 ? 'site' : 'sites';

    var html = '';
    html += '<div class="modal-header">';
    html += '<h3>Confirm Action</h3>';
    html += '<button class="modal-close" id="deployConfirmClose">&times;</button>';
    html += '</div>';
    html += '<p style="margin-bottom:1rem;color:#94a3b8">This will <strong style="color:#e0e0e0">' +
      Utils.escapeHtml(verb) + '</strong> on <strong style="color:#e0e0e0">' +
      n + ' ' + siteWord + '</strong>. Continue?</p>';
    html += '<div class="form-actions">';
    html += '<button class="btn btn-ghost" id="deployConfirmCancel">Cancel</button>';
    html += '<button class="btn btn-danger" id="deployConfirmOk">Continue</button>';
    html += '</div>';

    modal.innerHTML = html;
    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    var closeModal = function () {
      if (document.body.contains(overlay)) {
        document.body.removeChild(overlay);
      }
    };

    document.getElementById('deployConfirmClose').addEventListener('click', closeModal);
    document.getElementById('deployConfirmCancel').addEventListener('click', closeModal);
    overlay.addEventListener('click', function (e) {
      if (e.target === overlay) closeModal();
    });

    document.getElementById('deployConfirmOk').addEventListener('click', function () {
      closeModal();
      self._runActions(selected, action);
    });
  },

  /* ---------- Sequential Action Runner ---------- */

  async _runActions(sites, action) {
    var execBtn = document.getElementById('deployExecuteBtn');
    if (execBtn) {
      execBtn.disabled = true;
      execBtn.textContent = 'Running...';
    }

    for (var i = 0; i < sites.length; i++) {
      var site = sites[i];
      var actionLabel = this._actionLabel(action);
      this._logLine('>>> ' + site.name + ' \u2014 ' + actionLabel + '...');

      try {
        var result = await this._callAction(site.name, action);
        var output = (result && (result.output || result.message)) || 'OK';
        this._logOutput(output);
        this._logLine('[OK] ' + site.name + ' \u2014 done', 'ok');
      } catch (err) {
        this._logLine('[ERROR] ' + site.name + ' \u2014 ' + err.message, 'error');
      }

      this._logLine('');
    }

    if (execBtn) {
      execBtn.disabled = false;
      execBtn.textContent = 'Execute';
    }
  },

  /* ---------- API Calls ---------- */

  _callAction(siteName, action) {
    var encoded = encodeURIComponent(siteName);
    var endpoints = {
      push:    '/api/sites/' + encoded + '/push',
      setup:   '/api/sites/' + encoded + '/setup',
      restart: '/api/sites/' + encoded + '/restart',
      status:  '/api/sites/' + encoded + '/status',
      reboot:  '/api/sites/' + encoded + '/reboot',
    };
    var path = endpoints[action];
    if (!path) throw new Error('Unknown action: ' + action);
    return Api.post(path);
  },

  /* ---------- Log Helpers ---------- */

  _logLine(text, type) {
    var log = document.getElementById('deployLog');
    if (!log) return;

    var line = document.createElement('div');
    line.className = 'log-line';

    if (type === 'ok') {
      line.style.color = '#22c55e';
    } else if (type === 'error') {
      line.style.color = '#ef4444';
    }

    if (text === '') {
      line.innerHTML = '&nbsp;';
    } else {
      var ts = this._timestamp();
      line.textContent = '[' + ts + '] ' + text;
    }

    log.appendChild(line);
    log.scrollTop = log.scrollHeight;
  },

  _logOutput(text) {
    var log = document.getElementById('deployLog');
    if (!log) return;

    // Split multi-line output into individual lines
    var lines = String(text).split('\n');
    for (var i = 0; i < lines.length; i++) {
      var lineText = lines[i];
      // Skip trailing empty line from split
      if (i === lines.length - 1 && lineText === '') continue;

      var el = document.createElement('div');
      el.className = 'log-line log-line-output';
      el.style.color = '#94a3b8';
      el.textContent = '    ' + lineText;
      log.appendChild(el);
    }
    log.scrollTop = log.scrollHeight;
  },

  _timestamp() {
    var now = new Date();
    var hh = String(now.getHours()).padStart(2, '0');
    var mm = String(now.getMinutes()).padStart(2, '0');
    var ss = String(now.getSeconds()).padStart(2, '0');
    return hh + ':' + mm + ':' + ss;
  },

  /* ---------- Labels ---------- */

  _actionLabel(action) {
    var labels = {
      push:    'Push Config',
      setup:   'Run Setup',
      restart: 'Restart WireGuard',
      status:  'Check Status',
      reboot:  'Reboot',
    };
    return labels[action] || action;
  },
};
