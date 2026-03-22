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
      this._renderForm(config);
    } catch (err) {
      this._container.textContent = 'Failed to load settings: ' + err.message;
    }
  },

  _renderForm(config) {
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
};
