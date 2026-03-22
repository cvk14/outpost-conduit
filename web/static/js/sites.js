/* ==========================================================================
   Outpost Conduit — Sites CRUD View
   ========================================================================== */

window.SitesView = {
  _sites: [],

  render(container) {
    container.innerHTML =
      '<div class="container">' +
        '<h2>Sites</h2>' +
        '<p class="subtitle">Loading...</p>' +
      '</div>';
    this._container = container;
    this._loadSites();
  },

  /* ---------- Data Loading ---------- */

  async _loadSites() {
    try {
      this._sites = await Api.get('/api/sites') || [];
      this._renderView();
    } catch (err) {
      this._container.innerHTML =
        '<div class="container">' +
          '<h2>Site Management</h2>' +
          '<p class="subtitle" style="color:#ef4444">Failed to load sites: ' + Utils.escapeHtml(err.message) + '</p>' +
        '</div>';
    }
  },

  /* ---------- Main View ---------- */

  _renderView() {
    var sites = this._sites;
    var html = '<div class="container">';

    // Header row
    html += '<div class="flex items-center justify-between mb-2">';
    html += '<div>';
    html += '<h2>Site Management</h2>';
    html += '<p class="subtitle">Manage VPN site inventory (' + sites.length + ' site' + (sites.length !== 1 ? 's' : '') + ')</p>';
    html += '</div>';
    html += '<div class="flex items-center gap-sm">';
    html += '<button class="btn btn-primary" id="addSiteBtn">+ Add Site</button>';
    html += '<button class="btn btn-danger" id="applyHubBtn">Apply to Hub</button>';
    html += '</div>';
    html += '</div>';

    // Sites table panel
    html += '<div class="panel">';
    html += '<div class="panel-header">';
    html += '<span class="panel-title">Sites</span>';
    html += '</div>';
    html += '<div class="table-wrap">';
    html += '<table>';
    html += '<thead><tr>';
    html += '<th>Name</th><th>Type</th><th>Tunnel IP</th><th>WAN IP</th><th>Description</th><th>SSH Host</th><th>Actions</th>';
    html += '</tr></thead>';
    html += '<tbody>';

    if (sites.length === 0) {
      html += '<tr><td colspan="7" style="text-align:center;color:#64748b">No sites configured</td></tr>';
    }

    for (var i = 0; i < sites.length; i++) {
      var site = sites[i];
      var name = Utils.escapeHtml(site.name || '');
      var siteType = site.type || 'glinet';
      var tunnelIp = Utils.escapeHtml(site.tunnel_ip || '');
      var wanIp = Utils.escapeHtml(site.wan_ip || 'dynamic');
      var desc = Utils.escapeHtml(site.description || '');
      var sshHost = Utils.escapeHtml((site.ssh && site.ssh.host) || '');

      var typeClass = siteType === 'cradlepoint' ? 'type-cradlepoint' : 'type-glinet';
      var typeLabel = siteType === 'cradlepoint' ? 'Cradlepoint' : 'GL.iNet';

      html += '<tr>';
      html += '<td><strong>' + name + '</strong></td>';
      html += '<td><span class="type-tag ' + typeClass + '">' + typeLabel + '</span></td>';
      html += '<td class="font-mono text-sm">' + tunnelIp + '</td>';
      html += '<td class="font-mono text-sm">' + wanIp + '</td>';
      html += '<td class="text-secondary">' + desc + '</td>';
      html += '<td class="font-mono text-sm">' + (sshHost || '<span class="text-muted">&mdash;</span>') + '</td>';
      html += '<td>';
      html += '<div class="flex gap-sm">';
      html += '<button class="icon-btn" title="Download config" data-download="' + encodeURIComponent(site.name || '') + '">&#8615;</button>';
      html += '<button class="icon-btn" title="Edit" data-edit="' + i + '">&#9998;</button>';
      html += '<button class="icon-btn danger" title="Delete" data-delete="' + i + '">&#10005;</button>';
      html += '</div>';
      html += '</td>';
      html += '</tr>';
    }

    html += '</tbody></table>';
    html += '</div>'; // .table-wrap
    html += '</div>'; // .panel
    html += '</div>'; // .container

    this._container.innerHTML = html;
    this._bindEvents();
  },

  /* ---------- Event Binding ---------- */

  _bindEvents() {
    var self = this;

    // Add Site button
    var addBtn = document.getElementById('addSiteBtn');
    if (addBtn) {
      addBtn.addEventListener('click', function () {
        self._showForm(null);
      });
    }

    // Apply to Hub button
    var applyBtn = document.getElementById('applyHubBtn');
    if (applyBtn) {
      applyBtn.addEventListener('click', function () {
        self._applyToHub();
      });
    }

    // Edit buttons
    var editBtns = this._container.querySelectorAll('[data-edit]');
    for (var i = 0; i < editBtns.length; i++) {
      (function (btn) {
        btn.addEventListener('click', function () {
          var idx = parseInt(btn.getAttribute('data-edit'), 10);
          self._showForm(self._sites[idx]);
        });
      })(editBtns[i]);
    }

    // Delete buttons
    var delBtns = this._container.querySelectorAll('[data-delete]');
    for (var i = 0; i < delBtns.length; i++) {
      (function (btn) {
        btn.addEventListener('click', function () {
          var idx = parseInt(btn.getAttribute('data-delete'), 10);
          self._showDeleteConfirm(self._sites[idx]);
        });
      })(delBtns[i]);
    }

    // Download buttons
    var dlBtns = this._container.querySelectorAll('[data-download]');
    for (var i = 0; i < dlBtns.length; i++) {
      (function (btn) {
        btn.addEventListener('click', function () {
          var siteName = decodeURIComponent(btn.getAttribute('data-download'));
          window.open('/api/sites/' + encodeURIComponent(siteName) + '/download?token=' + encodeURIComponent(Auth.getToken()), '_blank');
        });
      })(dlBtns[i]);
    }
  },

  /* ---------- Add/Edit Form Modal ---------- */

  async _showForm(site) {
    var isEdit = !!site;
    var nextIp = '';

    // Pre-fill tunnel IP for new sites
    if (!isEdit) {
      try {
        var ipData = await Api.get('/api/sites/next-ip');
        nextIp = (ipData && ipData.tunnel_ip) || '';
      } catch (err) {
        nextIp = '';
      }
    }

    var overlay = document.createElement('div');
    overlay.className = 'modal-overlay';

    var modal = document.createElement('div');
    modal.className = 'modal';

    var html = '';
    html += '<div class="modal-header">';
    html += '<h3>' + (isEdit ? 'Edit Site' : 'Add Site') + '</h3>';
    html += '<button class="modal-close" id="modalCloseBtn">&times;</button>';
    html += '</div>';

    // Name field
    html += '<div class="form-group">';
    html += '<label for="siteFormName">Name</label>';
    html += '<input type="text" id="siteFormName" placeholder="site-name"' +
      ' value="' + (isEdit ? this._attrEscape(site.name || '') : '') + '"' +
      (isEdit ? ' disabled' : '') + '>';
    html += '</div>';

    // Type + Tunnel IP row
    html += '<div class="form-row">';

    html += '<div class="form-group">';
    html += '<label for="siteFormType">Type</label>';
    html += '<select id="siteFormType">';
    html += '<option value="glinet"' + (isEdit && site.type === 'glinet' ? ' selected' : (!isEdit ? ' selected' : '')) + '>GL.iNet</option>';
    html += '<option value="cradlepoint"' + (isEdit && site.type === 'cradlepoint' ? ' selected' : '') + '>Cradlepoint</option>';
    html += '</select>';
    html += '</div>';

    html += '<div class="form-group">';
    html += '<label for="siteFormTunnelIp">Tunnel IP</label>';
    html += '<input type="text" id="siteFormTunnelIp" placeholder="172.27.X.1"' +
      ' value="' + this._attrEscape(isEdit ? (site.tunnel_ip || '') : nextIp) + '">';
    html += '</div>';

    html += '</div>'; // .form-row

    // WAN IP + Description row
    html += '<div class="form-row">';

    html += '<div class="form-group">';
    html += '<label for="siteFormWanIp">WAN IP</label>';
    html += '<input type="text" id="siteFormWanIp" placeholder="dynamic"' +
      ' value="' + this._attrEscape(isEdit ? (site.wan_ip || 'dynamic') : 'dynamic') + '">';
    html += '</div>';

    html += '<div class="form-group">';
    html += '<label for="siteFormDesc">Description</label>';
    html += '<input type="text" id="siteFormDesc" placeholder="Site description"' +
      ' value="' + this._attrEscape(isEdit ? (site.description || '') : '') + '">';
    html += '</div>';

    html += '</div>'; // .form-row

    // SSH fields
    var sshData = (isEdit && site.ssh) || {};

    html += '<div class="form-group">';
    html += '<label for="siteFormSshHost">SSH Host <span class="text-muted text-xs">(optional)</span></label>';
    html += '<input type="text" id="siteFormSshHost" placeholder="192.168.x.x or hostname"' +
      ' value="' + this._attrEscape(sshData.host || '') + '">';
    html += '</div>';

    html += '<div class="form-row">';

    html += '<div class="form-group">';
    html += '<label for="siteFormSshUser">SSH User <span class="text-muted text-xs">(optional)</span></label>';
    html += '<input type="text" id="siteFormSshUser" placeholder="root"' +
      ' value="' + this._attrEscape(sshData.user || '') + '">';
    html += '</div>';

    html += '<div class="form-group">';
    html += '<label for="siteFormSshKey">SSH Key Path <span class="text-muted text-xs">(optional)</span></label>';
    html += '<input type="text" id="siteFormSshKey" placeholder="/path/to/key"' +
      ' value="' + this._attrEscape(sshData.key || '') + '">';
    html += '</div>';

    html += '</div>'; // .form-row

    // Error message area
    html += '<div id="siteFormError" style="color:#ef4444;font-size:0.8125rem;min-height:1.25rem;margin-top:0.5rem"></div>';

    // Actions
    html += '<div class="form-actions">';
    html += '<button class="btn btn-ghost" id="siteFormCancel">Cancel</button>';
    html += '<button class="btn btn-primary" id="siteFormSave">' + (isEdit ? 'Save Changes' : 'Add Site') + '</button>';
    html += '</div>';

    modal.innerHTML = html;
    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    var self = this;

    // Close handlers
    var closeModal = function () {
      if (document.body.contains(overlay)) {
        document.body.removeChild(overlay);
      }
    };

    document.getElementById('modalCloseBtn').addEventListener('click', closeModal);
    document.getElementById('siteFormCancel').addEventListener('click', closeModal);
    overlay.addEventListener('click', function (e) {
      if (e.target === overlay) closeModal();
    });

    // Save handler
    document.getElementById('siteFormSave').addEventListener('click', function () {
      self._handleSave(isEdit, site, closeModal);
    });
  },

  async _handleSave(isEdit, originalSite, closeModal) {
    var errorEl = document.getElementById('siteFormError');
    var saveBtn = document.getElementById('siteFormSave');

    var name = document.getElementById('siteFormName').value.trim();
    var type = document.getElementById('siteFormType').value;
    var tunnelIp = document.getElementById('siteFormTunnelIp').value.trim();
    var wanIp = document.getElementById('siteFormWanIp').value.trim() || 'dynamic';
    var desc = document.getElementById('siteFormDesc').value.trim();
    var sshHost = document.getElementById('siteFormSshHost').value.trim();
    var sshUser = document.getElementById('siteFormSshUser').value.trim();
    var sshKey = document.getElementById('siteFormSshKey').value.trim();

    // Validation
    if (!name) {
      errorEl.textContent = 'Name is required.';
      return;
    }

    if (!tunnelIp) {
      errorEl.textContent = 'Tunnel IP is required.';
      return;
    }

    // Build request body
    var body = {
      name: name,
      type: type,
      tunnel_ip: tunnelIp,
      wan_ip: wanIp,
      description: desc,
    };

    // Only include SSH dict if at least one SSH field is provided
    if (sshHost || sshUser || sshKey) {
      body.ssh = {};
      if (sshHost) body.ssh.host = sshHost;
      if (sshUser) body.ssh.user = sshUser;
      if (sshKey) body.ssh.key = sshKey;
    }

    errorEl.textContent = '';
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving...';

    try {
      if (isEdit) {
        // PUT - send only updatable fields (no name)
        var updateBody = {
          type: type,
          tunnel_ip: tunnelIp,
          wan_ip: wanIp,
          description: desc,
        };
        if (sshHost || sshUser || sshKey) {
          updateBody.ssh = {};
          if (sshHost) updateBody.ssh.host = sshHost;
          if (sshUser) updateBody.ssh.user = sshUser;
          if (sshKey) updateBody.ssh.key = sshKey;
        }
        await Api.put('/api/sites/' + encodeURIComponent(originalSite.name), updateBody);
      } else {
        await Api.post('/api/sites', body);
      }
      closeModal();
      this._showNotice(isEdit ? 'Site updated successfully.' : 'Site added successfully.', 'ok');
      this._loadSites();
    } catch (err) {
      errorEl.textContent = err.message || 'Save failed.';
      saveBtn.disabled = false;
      saveBtn.textContent = isEdit ? 'Save Changes' : 'Add Site';
    }
  },

  /* ---------- Delete Confirmation Modal ---------- */

  _showDeleteConfirm(site) {
    var overlay = document.createElement('div');
    overlay.className = 'modal-overlay';

    var modal = document.createElement('div');
    modal.className = 'modal';

    var html = '';
    html += '<div class="modal-header">';
    html += '<h3>Delete Site</h3>';
    html += '<button class="modal-close" id="delCloseBtn">&times;</button>';
    html += '</div>';

    html += '<p style="margin-bottom:1rem;color:#94a3b8">Are you sure you want to delete site <strong style="color:#e0e0e0">' +
      Utils.escapeHtml(site.name) + '</strong>? This action cannot be undone.</p>';

    html += '<div id="delError" style="color:#ef4444;font-size:0.8125rem;min-height:1.25rem"></div>';

    html += '<div class="form-actions">';
    html += '<button class="btn btn-ghost" id="delCancelBtn">Cancel</button>';
    html += '<button class="btn btn-danger" id="delConfirmBtn">Delete</button>';
    html += '</div>';

    modal.innerHTML = html;
    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    var self = this;

    var closeModal = function () {
      if (document.body.contains(overlay)) {
        document.body.removeChild(overlay);
      }
    };

    document.getElementById('delCloseBtn').addEventListener('click', closeModal);
    document.getElementById('delCancelBtn').addEventListener('click', closeModal);
    overlay.addEventListener('click', function (e) {
      if (e.target === overlay) closeModal();
    });

    document.getElementById('delConfirmBtn').addEventListener('click', async function () {
      var confirmBtn = document.getElementById('delConfirmBtn');
      var errorEl = document.getElementById('delError');
      confirmBtn.disabled = true;
      confirmBtn.textContent = 'Deleting...';

      try {
        await Api.del('/api/sites/' + encodeURIComponent(site.name));
        closeModal();
        self._showNotice('Site "' + site.name + '" deleted.', 'ok');
        self._loadSites();
      } catch (err) {
        errorEl.textContent = err.message || 'Delete failed.';
        confirmBtn.disabled = false;
        confirmBtn.textContent = 'Delete';
      }
    });
  },

  /* ---------- Apply to Hub ---------- */

  async _applyToHub() {
    if (!confirm('Regenerate all configs and restart hub services?\n\nThis will briefly interrupt VPN tunnels.')) {
      return;
    }

    var applyBtn = document.getElementById('applyHubBtn');
    if (applyBtn) {
      applyBtn.disabled = true;
      applyBtn.textContent = 'Applying...';
    }

    try {
      var result = await Api.post('/api/hub/regenerate');
      var msg = (result && result.message) || 'Done';
      if (result && result.status === 'partial') {
        this._showNotice('Warning: ' + msg + (result.error ? ' (' + result.error + ')' : ''), 'warn');
      } else {
        this._showNotice(msg, 'ok');
      }
    } catch (err) {
      this._showNotice('Apply failed: ' + err.message, 'error');
    } finally {
      if (applyBtn) {
        applyBtn.disabled = false;
        applyBtn.textContent = 'Apply to Hub';
      }
    }
  },

  /* ---------- Feedback Notice ---------- */

  _showNotice(message, type) {
    // Remove any existing notice
    var existing = document.getElementById('sitesNotice');
    if (existing) existing.remove();

    var color = type === 'ok' ? '#22c55e' : type === 'warn' ? '#eab308' : '#ef4444';
    var bgColor = type === 'ok' ? 'rgba(34,197,94,0.1)' : type === 'warn' ? 'rgba(234,179,8,0.1)' : 'rgba(239,68,68,0.1)';

    var notice = document.createElement('div');
    notice.id = 'sitesNotice';
    notice.style.cssText =
      'padding:0.75rem 1rem;border-radius:8px;font-size:0.8125rem;font-weight:500;margin-bottom:1rem;' +
      'color:' + color + ';background:' + bgColor + ';border:1px solid ' + color + '33;';
    notice.textContent = message;

    // Insert after the header (first child of .container)
    var container = this._container.querySelector('.container');
    if (container) {
      var firstPanel = container.querySelector('.panel');
      if (firstPanel) {
        container.insertBefore(notice, firstPanel);
      } else {
        container.appendChild(notice);
      }
    }

    // Auto-dismiss after 5 seconds
    setTimeout(function () {
      if (notice.parentNode) notice.remove();
    }, 5000);
  },

  /* ---------- Helpers ---------- */

  _attrEscape(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/"/g, '&quot;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  },
};
