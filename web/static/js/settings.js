/* ==========================================================================
   Outpost Conduit — Settings View
   ========================================================================== */

window.SettingsView = {
  _container: null,

  render(container) {
    this._container = container;
    container.textContent = '';
    var wrapper = document.createElement('div');
    wrapper.className = 'container';
    var h2 = document.createElement('h2');
    h2.textContent = 'Settings';
    wrapper.appendChild(h2);
    var sub = document.createElement('p');
    sub.className = 'subtitle';
    sub.textContent = 'Loading...';
    wrapper.appendChild(sub);
    container.appendChild(wrapper);
    this._loadSettings();
  },

  async _loadSettings() {
    try {
      var config = await Api.get('/api/settings');
      var users = await Api.get('/api/users');
      this._renderForm(config, users);
    } catch (err) {
      this._container.textContent = 'Failed to load settings: ' + err.message;
    }
  },

  _renderForm(config, usersList) {
    var c = this._container;
    c.textContent = '';

    var wrapper = document.createElement('div');
    wrapper.className = 'container';

    var h2 = document.createElement('h2');
    h2.textContent = 'Settings';
    wrapper.appendChild(h2);

    var sub = document.createElement('p');
    sub.className = 'subtitle';
    sub.textContent = 'Health monitoring interval and email notification settings';
    wrapper.appendChild(sub);

    // Health check interval
    var panel1 = document.createElement('div');
    panel1.className = 'panel';
    panel1.style.marginBottom = '1.5rem';

    var hdr1 = document.createElement('div');
    hdr1.className = 'panel-header';
    var t1 = document.createElement('span');
    t1.className = 'panel-title';
    t1.textContent = 'Health Monitoring';
    hdr1.appendChild(t1);
    panel1.appendChild(hdr1);

    var body1 = document.createElement('div');
    body1.style.padding = '1rem';

    var fg1 = this._makeField('Check interval (minutes)', 'settingsInterval', 'number', config.health_check_interval_minutes || 15);
    body1.appendChild(fg1);

    var note = document.createElement('p');
    note.style.cssText = 'color:#64748b;font-size:0.8rem;margin-top:0.5rem';
    note.textContent = 'Runs ping + multicast tests on all sites at this interval. Minimum 1 minute.';
    body1.appendChild(note);

    panel1.appendChild(body1);
    wrapper.appendChild(panel1);

    // SMTP settings
    var panel2 = document.createElement('div');
    panel2.className = 'panel';
    panel2.style.marginBottom = '1.5rem';

    var hdr2 = document.createElement('div');
    hdr2.className = 'panel-header';
    var t2 = document.createElement('span');
    t2.className = 'panel-title';
    t2.textContent = 'Email Notifications';
    hdr2.appendChild(t2);
    panel2.appendChild(hdr2);

    var body2 = document.createElement('div');
    body2.style.padding = '1rem';

    // Enable toggle
    var enableRow = document.createElement('div');
    enableRow.className = 'form-group';
    enableRow.style.display = 'flex';
    enableRow.style.alignItems = 'center';
    enableRow.style.gap = '0.75rem';
    var enableCb = document.createElement('input');
    enableCb.type = 'checkbox';
    enableCb.id = 'settingsSmtpEnabled';
    enableCb.checked = config.smtp_enabled || false;
    enableRow.appendChild(enableCb);
    var enableLbl = document.createElement('label');
    enableLbl.setAttribute('for', 'settingsSmtpEnabled');
    enableLbl.textContent = 'Enable email alerts when health checks fail';
    enableLbl.style.margin = '0';
    enableRow.appendChild(enableLbl);
    body2.appendChild(enableRow);

    body2.appendChild(this._makeField('SMTP Host', 'settingsSmtpHost', 'text', config.smtp_host || '', 'smtp.gmail.com'));
    body2.appendChild(this._makeField('SMTP Port', 'settingsSmtpPort', 'number', config.smtp_port || 587));
    body2.appendChild(this._makeField('SMTP Username', 'settingsSmtpUser', 'text', config.smtp_user || ''));
    body2.appendChild(this._makeField('SMTP Password', 'settingsSmtpPass', 'password', config.smtp_password || ''));
    body2.appendChild(this._makeField('From Address', 'settingsSmtpFrom', 'email', config.smtp_from || '', 'alerts@example.com'));
    body2.appendChild(this._makeField('To Address(es)', 'settingsSmtpTo', 'text', config.smtp_to || '', 'admin@example.com, ops@example.com'));

    panel2.appendChild(body2);
    wrapper.appendChild(panel2);

    // --- Users panel ---
    var panel3 = document.createElement('div');
    panel3.className = 'panel';
    panel3.style.marginBottom = '1.5rem';

    var hdr3 = document.createElement('div');
    hdr3.className = 'panel-header';
    var t3 = document.createElement('span');
    t3.className = 'panel-title';
    t3.textContent = 'User Accounts';
    hdr3.appendChild(t3);
    var addUserBtn = document.createElement('button');
    addUserBtn.className = 'btn btn-primary btn-sm';
    addUserBtn.textContent = '+ Add User';
    addUserBtn.id = 'settingsAddUser';
    hdr3.appendChild(addUserBtn);
    panel3.appendChild(hdr3);

    var usersBody = document.createElement('div');
    usersBody.id = 'settingsUsersList';
    usersBody.style.padding = '1rem';
    this._renderUsers(usersBody, usersList || []);
    panel3.appendChild(usersBody);

    wrapper.appendChild(panel3);

    // Buttons
    var actions = document.createElement('div');
    actions.className = 'flex gap-sm';

    var saveBtn = document.createElement('button');
    saveBtn.id = 'settingsSave';
    saveBtn.className = 'btn btn-primary';
    saveBtn.textContent = 'Save Settings';
    actions.appendChild(saveBtn);

    var testBtn = document.createElement('button');
    testBtn.id = 'settingsTestEmail';
    testBtn.className = 'btn btn-ghost';
    testBtn.textContent = 'Send Test Email';
    actions.appendChild(testBtn);

    wrapper.appendChild(actions);

    // Status message
    var status = document.createElement('div');
    status.id = 'settingsStatus';
    status.style.cssText = 'margin-top:1rem';
    wrapper.appendChild(status);

    c.appendChild(wrapper);
    this._bindEvents();
    this._bindUserEvents();
  },

  _makeField(label, id, type, value, placeholder) {
    var fg = document.createElement('div');
    fg.className = 'form-group';
    var lbl = document.createElement('label');
    lbl.setAttribute('for', id);
    lbl.textContent = label;
    fg.appendChild(lbl);
    var input = document.createElement('input');
    input.type = type;
    input.id = id;
    input.value = value !== undefined ? value : '';
    if (placeholder) input.placeholder = placeholder;
    fg.appendChild(input);
    return fg;
  },

  _bindEvents() {
    var self = this;

    document.getElementById('settingsSave').addEventListener('click', function() {
      self._save();
    });

    document.getElementById('settingsTestEmail').addEventListener('click', function() {
      self._testEmail();
    });
  },

  async _save() {
    var data = {
      health_check_interval_minutes: parseInt(document.getElementById('settingsInterval').value) || 15,
      smtp_enabled: document.getElementById('settingsSmtpEnabled').checked,
      smtp_host: document.getElementById('settingsSmtpHost').value,
      smtp_port: parseInt(document.getElementById('settingsSmtpPort').value) || 587,
      smtp_user: document.getElementById('settingsSmtpUser').value,
      smtp_password: document.getElementById('settingsSmtpPass').value,
      smtp_from: document.getElementById('settingsSmtpFrom').value,
      smtp_to: document.getElementById('settingsSmtpTo').value,
    };

    var status = document.getElementById('settingsStatus');

    try {
      await Api.put('/api/settings', data);
      status.textContent = 'Settings saved successfully.';
      status.style.color = '#22c55e';
    } catch (err) {
      status.textContent = 'Failed to save: ' + err.message;
      status.style.color = '#ef4444';
    }

    setTimeout(function() { status.textContent = ''; }, 5000);
  },

  async _testEmail() {
    var status = document.getElementById('settingsStatus');
    status.textContent = 'Sending test email...';
    status.style.color = '#94a3b8';

    try {
      var r = await Api.post('/api/settings/test-email');
      if (r.sent) {
        status.textContent = 'Test email sent successfully!';
        status.style.color = '#22c55e';
      } else {
        status.textContent = 'Failed to send test email. Check SMTP settings.';
        status.style.color = '#ef4444';
      }
    } catch (err) {
      status.textContent = 'Error: ' + err.message;
      status.style.color = '#ef4444';
    }

    setTimeout(function() { status.textContent = ''; }, 8000);
  },

  // --- User Management ---
  _renderUsers(container, usersList) {
    container.textContent = '';
    if (!usersList || usersList.length === 0) {
      container.textContent = 'No users configured.';
      return;
    }

    var table = document.createElement('table');
    table.style.width = '100%';
    var thead = document.createElement('thead');
    var hRow = document.createElement('tr');
    ['Username', 'Password', 'Passkeys', 'Created', 'Actions'].forEach(function(h) {
      var th = document.createElement('th');
      th.textContent = h;
      hRow.appendChild(th);
    });
    thead.appendChild(hRow);
    table.appendChild(thead);

    var tbody = document.createElement('tbody');
    var self = this;
    for (var i = 0; i < usersList.length; i++) {
      var u = usersList[i];
      var tr = document.createElement('tr');

      var tdName = document.createElement('td');
      tdName.textContent = u.username;
      tdName.style.fontWeight = '600';
      tr.appendChild(tdName);

      var tdPw = document.createElement('td');
      var pwBadge = document.createElement('span');
      pwBadge.className = 'badge ' + (u.has_password ? 'badge-green' : 'badge-red');
      pwBadge.textContent = u.has_password ? 'Set' : 'None';
      tdPw.appendChild(pwBadge);
      tr.appendChild(tdPw);

      var tdPk = document.createElement('td');
      tdPk.textContent = u.passkey_count + ' registered';
      tr.appendChild(tdPk);

      var tdCreated = document.createElement('td');
      tdCreated.className = 'text-muted text-sm';
      tdCreated.textContent = u.created || '';
      tr.appendChild(tdCreated);

      var tdActions = document.createElement('td');
      var actionsDiv = document.createElement('div');
      actionsDiv.className = 'flex gap-sm';

      var chPwBtn = document.createElement('button');
      chPwBtn.className = 'btn btn-ghost btn-sm';
      chPwBtn.textContent = 'Password';
      chPwBtn.setAttribute('data-user', u.username);
      chPwBtn.addEventListener('click', function() {
        self._changePassword(this.getAttribute('data-user'));
      });
      actionsDiv.appendChild(chPwBtn);

      var pkBtn = document.createElement('button');
      pkBtn.className = 'btn btn-ghost btn-sm';
      pkBtn.textContent = '+ Passkey';
      pkBtn.setAttribute('data-user', u.username);
      pkBtn.addEventListener('click', function() {
        self._registerPasskey(this.getAttribute('data-user'));
      });
      if (!window.PublicKeyCredential) pkBtn.style.display = 'none';
      actionsDiv.appendChild(pkBtn);

      if (usersList.length > 1) {
        var delBtn = document.createElement('button');
        delBtn.className = 'btn btn-ghost btn-sm';
        delBtn.style.color = '#ef4444';
        delBtn.textContent = 'Delete';
        delBtn.setAttribute('data-user', u.username);
        delBtn.addEventListener('click', function() {
          self._deleteUser(this.getAttribute('data-user'));
        });
        actionsDiv.appendChild(delBtn);
      }

      tdActions.appendChild(actionsDiv);
      tr.appendChild(tdActions);
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    container.appendChild(table);
  },

  _bindUserEvents() {
    var self = this;
    var addBtn = document.getElementById('settingsAddUser');
    if (addBtn) {
      addBtn.addEventListener('click', function() { self._addUser(); });
    }
  },

  async _addUser() {
    var username = prompt('New username:');
    if (!username) return;
    var password = prompt('Password for ' + username + ':');
    if (!password) return;

    try {
      await Api.post('/api/users', { username: username, password: password });
      this._loadSettings();
    } catch (err) {
      alert('Failed: ' + err.message);
    }
  },

  async _deleteUser(username) {
    if (!confirm('Delete user "' + username + '"? This cannot be undone.')) return;
    try {
      await Api.del('/api/users/' + encodeURIComponent(username));
      this._loadSettings();
    } catch (err) {
      alert('Failed: ' + err.message);
    }
  },

  async _changePassword(username) {
    var newPw = prompt('New password for ' + username + ':');
    if (!newPw) return;
    try {
      await Api.put('/api/users/' + encodeURIComponent(username) + '/password', { password: newPw });
      alert('Password changed.');
    } catch (err) {
      alert('Failed: ' + err.message);
    }
  },

  async _registerPasskey(username) {
    try {
      // Get registration options
      var optResp = await Api.post('/api/users/' + encodeURIComponent(username) + '/passkey/register-options');

      // Convert for WebAuthn API
      optResp.challenge = _b64urlToBuffer(optResp.challenge);
      optResp.user.id = _b64urlToBuffer(optResp.user.id);
      if (optResp.excludeCredentials) {
        optResp.excludeCredentials = optResp.excludeCredentials.map(function(c) {
          return { ...c, id: _b64urlToBuffer(c.id) };
        });
      }

      // Create credential
      var credential = await navigator.credentials.create({ publicKey: optResp });

      var name = prompt('Name this passkey (e.g., "MacBook Touch ID"):') || 'Passkey';

      // Send to server
      await Api.post('/api/users/' + encodeURIComponent(username) + '/passkey/register', {
        credential: {
          id: credential.id,
          rawId: _bufferToB64url(credential.rawId),
          response: {
            attestationObject: _bufferToB64url(credential.response.attestationObject),
            clientDataJSON: _bufferToB64url(credential.response.clientDataJSON),
          },
          type: credential.type,
        },
        name: name,
      });

      alert('Passkey registered!');
      this._loadSettings();
    } catch (err) {
      if (err.name === 'NotAllowedError') return;
      alert('Passkey registration failed: ' + err.message);
    }
  },
};

function _b64urlToBuffer(b64url) {
  var b64 = b64url.replace(/-/g, '+').replace(/_/g, '/');
  var pad = b64.length % 4 === 0 ? '' : '='.repeat(4 - (b64.length % 4));
  var binary = atob(b64 + pad);
  var bytes = new Uint8Array(binary.length);
  for (var i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}

function _bufferToB64url(buffer) {
  var bytes = new Uint8Array(buffer);
  var binary = '';
  for (var i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}
