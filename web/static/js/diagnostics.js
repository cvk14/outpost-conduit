/* ==========================================================================
   Outpost Conduit — Diagnostics View
   ========================================================================== */

window.DiagnosticsView = {
  _sites: [],
  _container: null,

  render(container) {
    this._container = container;
    container.textContent = '';
    var wrapper = document.createElement('div');
    wrapper.className = 'container';
    var h2 = document.createElement('h2');
    h2.textContent = 'Diagnostics';
    wrapper.appendChild(h2);
    var sub = document.createElement('p');
    sub.className = 'subtitle';
    sub.textContent = 'Loading sites...';
    wrapper.appendChild(sub);
    container.appendChild(wrapper);
    this._loadSites();
  },

  async _loadSites() {
    try {
      this._sites = await Api.get('/api/sites') || [];
    } catch (err) {
      this._container.textContent = '';
      var d = document.createElement('div');
      d.className = 'container';
      d.textContent = 'Failed to load sites: ' + err.message;
      this._container.appendChild(d);
      return;
    }
    this._renderView();
  },

  _renderView() {
    var sites = this._sites;
    var c = this._container;
    c.textContent = '';

    var wrapper = document.createElement('div');
    wrapper.className = 'container';

    var h2 = document.createElement('h2');
    h2.textContent = 'Diagnostics';
    wrapper.appendChild(h2);

    var sub = document.createElement('p');
    sub.className = 'subtitle';
    sub.textContent = 'Network tests: latency, packet loss, MTU, and multicast verification';
    wrapper.appendChild(sub);

    // Controls panel
    var panel = document.createElement('div');
    panel.className = 'panel';
    panel.style.marginBottom = '1.5rem';

    var header = document.createElement('div');
    header.className = 'panel-header';
    var title = document.createElement('span');
    title.className = 'panel-title';
    title.textContent = 'Run Tests';
    header.appendChild(title);
    panel.appendChild(header);

    var body = document.createElement('div');
    body.style.padding = '1rem';

    // Site selector
    var fg = document.createElement('div');
    fg.className = 'form-group';
    var lbl = document.createElement('label');
    lbl.textContent = 'Select Site';
    lbl.setAttribute('for', 'diagSite');
    fg.appendChild(lbl);
    var sel = document.createElement('select');
    sel.id = 'diagSite';
    for (var i = 0; i < sites.length; i++) {
      var opt = document.createElement('option');
      opt.value = sites[i].name;
      opt.textContent = sites[i].name + ' (' + sites[i].tunnel_ip + ')';
      sel.appendChild(opt);
    }
    fg.appendChild(sel);
    body.appendChild(fg);

    // Buttons
    var btnRow = document.createElement('div');
    btnRow.className = 'flex gap-sm';
    btnRow.style.flexWrap = 'wrap';

    var buttons = [
      { id: 'diagRunAll', text: 'Run All Tests', cls: 'btn btn-primary' },
      { id: 'diagPing', text: 'Ping (10 packets)', cls: 'btn btn-ghost' },
      { id: 'diagMTU', text: 'MTU Path Test', cls: 'btn btn-ghost' },
      { id: 'diagMcastOut', text: 'Multicast Hub\u2192Site', cls: 'btn btn-ghost' },
      { id: 'diagMcastReturn', text: 'Multicast Site\u2192Hub', cls: 'btn btn-ghost' },
    ];

    for (var j = 0; j < buttons.length; j++) {
      var b = document.createElement('button');
      b.id = buttons[j].id;
      b.className = buttons[j].cls;
      b.textContent = buttons[j].text;
      btnRow.appendChild(b);
    }
    body.appendChild(btnRow);
    panel.appendChild(body);
    wrapper.appendChild(panel);

    // Results area
    var results = document.createElement('div');
    results.id = 'diagResults';
    wrapper.appendChild(results);

    c.appendChild(wrapper);
    this._bindEvents();
  },

  _bindEvents() {
    var self = this;
    var bind = function(id, fn) {
      var el = document.getElementById(id);
      if (el) el.addEventListener('click', function() { fn.call(self); });
    };
    bind('diagRunAll', self._runAll);
    bind('diagPing', self._runPing);
    bind('diagMTU', self._runMTU);
    bind('diagMcastOut', self._runMcastOut);
    bind('diagMcastReturn', self._runMcastReturn);
  },

  _getSiteName() {
    var el = document.getElementById('diagSite');
    return el ? el.value : '';
  },

  _setLoading(label) {
    var r = document.getElementById('diagResults');
    if (!r) return;
    r.textContent = '';
    var p = document.createElement('div');
    p.className = 'panel';
    var inner = document.createElement('div');
    inner.style.cssText = 'padding:1.5rem;color:#94a3b8';
    // Animated dots spinner
    var header = document.createElement('div');
    header.style.cssText = 'display:flex;align-items:center;gap:0.75rem;margin-bottom:1rem';
    var spinner = document.createElement('span');
    spinner.className = 'diag-spinner';
    spinner.textContent = '\u25CF';
    header.appendChild(spinner);
    var msg = document.createElement('span');
    msg.style.fontSize = '1rem';
    msg.textContent = label;
    header.appendChild(msg);
    inner.appendChild(header);
    // Progress log
    var log = document.createElement('div');
    log.id = 'diagProgressLog';
    log.className = 'log-output';
    log.style.cssText = 'max-height:200px;font-size:12px;min-height:60px';
    inner.appendChild(log);
    p.appendChild(inner);
    r.appendChild(p);
    // Add CSS animation if not already present
    if (!document.getElementById('diagSpinnerStyle')) {
      var style = document.createElement('style');
      style.id = 'diagSpinnerStyle';
      style.textContent = '@keyframes diagPulse{0%,100%{opacity:0.3}50%{opacity:1}}.diag-spinner{animation:diagPulse 1s infinite;color:#60a5fa;font-size:1.25rem}';
      document.head.appendChild(style);
    }
  },

  _logProgress(text) {
    var log = document.getElementById('diagProgressLog');
    if (!log) return;
    var line = document.createElement('div');
    line.style.marginBottom = '0.25rem';
    var ts = new Date();
    var time = String(ts.getHours()).padStart(2,'0') + ':' + String(ts.getMinutes()).padStart(2,'0') + ':' + String(ts.getSeconds()).padStart(2,'0');
    line.textContent = '[' + time + '] ' + text;
    log.appendChild(line);
    log.scrollTop = log.scrollHeight;
  },

  _disableButtons(disabled) {
    ['diagRunAll','diagPing','diagMTU','diagMcastOut','diagMcastReturn'].forEach(function(id) {
      var el = document.getElementById(id);
      if (el) el.disabled = disabled;
    });
  },

  // --- Ping Test ---
  async _runPing() {
    var name = this._getSiteName();
    if (!name) return;
    this._setLoading('Ping test: ' + name);
    this._logProgress('Sending 10 ICMP packets to ' + name + '...');
    this._disableButtons(true);
    try {
      var r = await Api.post('/api/diagnostics/ping/' + encodeURIComponent(name) + '?count=10');
      this._logProgress('Complete: ' + r.rtt_avg.toFixed(1) + 'ms avg, ' + r.packet_loss_pct + '% loss');
      await new Promise(function(r) { setTimeout(r, 500); });
      this._renderPing(r);
    } catch (err) {
      this._logProgress('Failed: ' + err.message);
      this._showError('Ping', err.message);
    }
    this._disableButtons(false);
  },

  _renderPing(r) {
    var el = document.getElementById('diagResults');
    if (!el) return;
    el.textContent = '';

    var panel = document.createElement('div');
    panel.className = 'panel';

    var hdr = document.createElement('div');
    hdr.className = 'panel-header';
    var t = document.createElement('span');
    t.className = 'panel-title';
    t.textContent = 'Ping Test \u2014 ' + r.site + ' (' + r.tunnel_ip + ')';
    hdr.appendChild(t);
    panel.appendChild(hdr);

    var cards = document.createElement('div');
    cards.className = 'summary-cards';
    cards.style.padding = '1rem';

    var lossColor = r.packet_loss_pct === 0 ? '#22c55e' : r.packet_loss_pct < 10 ? '#eab308' : '#ef4444';
    var latColor = (r.rtt_avg || 999) < 50 ? '#22c55e' : (r.rtt_avg || 999) < 150 ? '#eab308' : '#ef4444';

    cards.appendChild(this._makeCard('Packet Loss', r.packet_loss_pct.toFixed(1) + '%', lossColor, r.packets_received + '/' + r.packets_sent + ' received'));
    cards.appendChild(this._makeCard('Avg Latency', r.rtt_avg !== null ? r.rtt_avg.toFixed(1) + ' ms' : '\u2014', latColor, ''));
    cards.appendChild(this._makeCard('Min / Max', r.rtt_min !== null ? r.rtt_min.toFixed(1) + ' / ' + r.rtt_max.toFixed(1) + ' ms' : '\u2014', '#60a5fa', ''));
    cards.appendChild(this._makeCard('Jitter', r.rtt_mdev !== null ? r.rtt_mdev.toFixed(1) + ' ms' : '\u2014', '#a78bfa', 'std deviation'));
    panel.appendChild(cards);

    // Raw output
    if (r.raw) {
      var log = document.createElement('div');
      log.className = 'log-output';
      log.style.cssText = 'max-height:150px;margin:0 1rem 1rem;font-size:11px';
      log.textContent = r.raw;
      panel.appendChild(log);
    }

    el.appendChild(panel);
  },

  // --- MTU Test ---
  async _runMTU() {
    var name = this._getSiteName();
    if (!name) return;
    this._setLoading('MTU path test: ' + name);
    this._logProgress('Testing packet sizes 100-1420 bytes with do-not-fragment...');
    this._disableButtons(true);
    try {
      var r = await Api.post('/api/diagnostics/mtu/' + encodeURIComponent(name));
      var maxMTU = 0;
      r.results.forEach(function(t) { if (t.success) maxMTU = t.size; });
      this._logProgress('Complete: max working payload ' + maxMTU + ' bytes');
      await new Promise(function(r) { setTimeout(r, 500); });
      this._renderMTU(r);
    } catch (err) {
      this._logProgress('Failed: ' + err.message);
      this._showError('MTU', err.message);
    }
    this._disableButtons(false);
  },

  _renderMTU(r) {
    var el = document.getElementById('diagResults');
    if (!el) return;
    el.textContent = '';

    var panel = document.createElement('div');
    panel.className = 'panel';

    var hdr = document.createElement('div');
    hdr.className = 'panel-header';
    var t = document.createElement('span');
    t.className = 'panel-title';
    t.textContent = 'MTU Path Test \u2014 ' + r.site;
    hdr.appendChild(t);
    panel.appendChild(hdr);

    var body = document.createElement('div');
    body.style.padding = '1rem';

    var table = document.createElement('table');
    var thead = document.createElement('thead');
    var headRow = document.createElement('tr');
    ['Payload Size', 'Total (+ headers)', 'Result'].forEach(function(txt) {
      var th = document.createElement('th');
      th.textContent = txt;
      headRow.appendChild(th);
    });
    thead.appendChild(headRow);
    table.appendChild(thead);

    var tbody = document.createElement('tbody');
    var maxWorking = 0;
    for (var i = 0; i < r.results.length; i++) {
      var test = r.results[i];
      if (test.success) maxWorking = test.size;
      var tr = document.createElement('tr');

      var td1 = document.createElement('td');
      td1.className = 'font-mono';
      td1.textContent = test.size + ' bytes';
      tr.appendChild(td1);

      var td2 = document.createElement('td');
      td2.className = 'font-mono text-secondary';
      td2.textContent = (test.size + 28) + ' bytes';
      tr.appendChild(td2);

      var td3 = document.createElement('td');
      var badge = document.createElement('span');
      badge.className = 'badge ' + (test.success ? 'badge-green' : 'badge-red');
      badge.textContent = test.success ? 'OK' : 'FAIL';
      td3.appendChild(badge);
      tr.appendChild(td3);

      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    body.appendChild(table);

    var summary = document.createElement('p');
    summary.style.cssText = 'margin-top:1rem;color:#94a3b8';
    summary.textContent = 'Max working payload: ';
    var strong = document.createElement('strong');
    strong.style.color = '#22c55e';
    strong.textContent = maxWorking + ' bytes (' + (maxWorking + 28) + ' total)';
    summary.appendChild(strong);
    body.appendChild(summary);

    panel.appendChild(body);
    el.appendChild(panel);
  },

  // --- Multicast Tests ---
  async _runMcastOut() {
    var name = this._getSiteName();
    if (!name) return;
    this._setLoading('Multicast hub\u2192site: ' + name);
    this._logProgress('Starting SSH listener on remote device...');
    this._logProgress('Sending test packet via WireGuard tunnel...');
    this._logProgress('Waiting for response (~8 seconds)...');
    this._disableButtons(true);
    try {
      var r = await Api.post('/api/diagnostics/multicast/' + encodeURIComponent(name));
      this._logProgress('Result: ' + (r.received ? 'PASSED' : 'FAILED'));
      await new Promise(function(r) { setTimeout(r, 500); });
      this._renderMcast(r, 'Hub \u2192 Site');
    } catch (err) {
      this._logProgress('Failed: ' + err.message);
      this._showError('Multicast Hub\u2192Site', err.message);
    }
    this._disableButtons(false);
  },

  async _runMcastReturn() {
    var name = this._getSiteName();
    if (!name) return;
    this._setLoading('Multicast site\u2192hub: ' + name);
    this._logProgress('Starting hub listener...');
    this._logProgress('Sending test packet from remote site via relay...');
    this._logProgress('Waiting for response (~8 seconds)...');
    this._disableButtons(true);
    try {
      var r = await Api.post('/api/diagnostics/multicast-return/' + encodeURIComponent(name));
      this._logProgress('Result: ' + (r.received ? 'PASSED' : 'FAILED'));
      await new Promise(function(r) { setTimeout(r, 500); });
      this._renderMcast(r, 'Site \u2192 Hub');
    } catch (err) {
      this._logProgress('Failed: ' + err.message);
      this._showError('Multicast Site\u2192Hub', err.message);
    }
    this._disableButtons(false);
  },

  _renderMcast(r, direction) {
    var el = document.getElementById('diagResults');
    if (!el) return;
    el.textContent = '';

    var panel = document.createElement('div');
    panel.className = 'panel';

    var hdr = document.createElement('div');
    hdr.className = 'panel-header';
    var t = document.createElement('span');
    t.className = 'panel-title';
    t.textContent = 'Multicast Test \u2014 ' + direction + ' \u2014 ' + r.site;
    hdr.appendChild(t);
    panel.appendChild(hdr);

    var body = document.createElement('div');
    body.style.cssText = 'padding:1.5rem;text-align:center';

    var icon = document.createElement('div');
    icon.style.fontSize = '3rem';
    icon.textContent = r.received ? '\u2714' : '\u2718';
    body.appendChild(icon);

    var status = document.createElement('div');
    status.style.cssText = 'font-size:1.25rem;font-weight:600;color:' + (r.received ? '#22c55e' : '#ef4444');
    status.textContent = r.received ? 'PASSED' : 'FAILED';
    body.appendChild(status);

    var tid = document.createElement('p');
    tid.style.cssText = 'color:#94a3b8;margin-top:0.5rem';
    tid.textContent = 'Test ID: ' + (r.test_id || '');
    tid.className = 'font-mono';
    body.appendChild(tid);

    if (r.error) {
      var errP = document.createElement('p');
      errP.style.cssText = 'color:#ef4444;margin-top:0.5rem';
      errP.textContent = r.error;
      body.appendChild(errP);
    }

    panel.appendChild(body);
    el.appendChild(panel);
  },

  // --- Run All ---
  async _runAll() {
    var name = this._getSiteName();
    if (!name) return;
    this._setLoading('Running diagnostics for ' + name);
    this._disableButtons(true);

    var results = {};
    var enc = encodeURIComponent(name);

    // Ping
    this._logProgress('Starting ping test (5 packets)...');
    try {
      results.ping = await Api.post('/api/diagnostics/ping/' + enc + '?count=5');
      var p = results.ping;
      this._logProgress('Ping complete: ' + p.rtt_avg.toFixed(1) + 'ms avg, ' + p.packet_loss_pct + '% loss');
    } catch (err) {
      results.ping = { error: err.message };
      this._logProgress('Ping failed: ' + err.message);
    }

    // MTU
    this._logProgress('Starting MTU path test (8 sizes)...');
    try {
      results.mtu = await Api.post('/api/diagnostics/mtu/' + enc);
      var maxMTU = 0;
      results.mtu.results.forEach(function(t) { if (t.success) maxMTU = t.size; });
      this._logProgress('MTU complete: max working payload ' + maxMTU + ' bytes');
    } catch (err) {
      results.mtu = { error: err.message };
      this._logProgress('MTU test failed: ' + err.message);
    }

    // Multicast hub→site
    this._logProgress('Starting multicast hub\u2192site test (~8s)...');
    try {
      results.multicast_to_site = await Api.post('/api/diagnostics/multicast/' + enc);
      this._logProgress('Multicast hub\u2192site: ' + (results.multicast_to_site.received ? 'PASSED' : 'FAILED'));
    } catch (err) {
      results.multicast_to_site = { error: err.message };
      this._logProgress('Multicast hub\u2192site failed: ' + err.message);
    }

    // Multicast site→hub
    this._logProgress('Starting multicast site\u2192hub test (~8s)...');
    try {
      results.multicast_to_hub = await Api.post('/api/diagnostics/multicast-return/' + enc);
      this._logProgress('Multicast site\u2192hub: ' + (results.multicast_to_hub.received ? 'PASSED' : 'FAILED'));
    } catch (err) {
      results.multicast_to_hub = { error: err.message };
      this._logProgress('Multicast site\u2192hub failed: ' + err.message);
    }

    this._logProgress('All tests complete.');
    // Short pause so user can see the final log before rendering results
    await new Promise(function(r) { setTimeout(r, 1000); });

    this._renderAll({ site: name, results: results });
    this._disableButtons(false);
  },

  _renderAll(r) {
    var el = document.getElementById('diagResults');
    if (!el) return;
    el.textContent = '';

    var res = r.results || {};
    var grid = document.createElement('div');
    grid.style.display = 'grid';
    grid.style.gap = '1rem';

    // Ping
    var ping = res.ping || {};
    if (!ping.error) {
      var pp = this._makeResultPanel('Ping',
        ping.packet_loss_pct === 0 ? 'badge-green' : 'badge-red',
        (ping.packet_loss_pct || 0) + '% loss');
      var pcards = document.createElement('div');
      pcards.className = 'summary-cards';
      pcards.style.padding = '1rem';
      var latColor = (ping.rtt_avg || 999) < 50 ? '#22c55e' : '#eab308';
      pcards.appendChild(this._makeCard('Latency', ping.rtt_avg ? ping.rtt_avg.toFixed(1) + ' ms' : '\u2014', latColor, ''));
      pcards.appendChild(this._makeCard('Jitter', ping.rtt_mdev ? ping.rtt_mdev.toFixed(1) + ' ms' : '\u2014', '#a78bfa', ''));
      var lossColor = (ping.packet_loss_pct || 0) === 0 ? '#22c55e' : '#ef4444';
      pcards.appendChild(this._makeCard('Loss', (ping.packet_loss_pct || 0).toFixed(1) + '%', lossColor, ping.packets_received + '/' + ping.packets_sent));
      pp.appendChild(pcards);
      grid.appendChild(pp);
    } else {
      grid.appendChild(this._makeErrorPanel('Ping', ping.error));
    }

    // MTU
    var mtu = res.mtu || {};
    if (!mtu.error && mtu.results) {
      var maxMTU = 0;
      mtu.results.forEach(function(t) { if (t.success) maxMTU = t.size; });
      var mp = this._makeResultPanel('MTU Path', 'badge-green', 'Max: ' + maxMTU + ' bytes');
      var badges = document.createElement('div');
      badges.style.cssText = 'padding:1rem;display:flex;gap:0.5rem;flex-wrap:wrap';
      mtu.results.forEach(function(t) {
        var b = document.createElement('span');
        b.className = 'badge ' + (t.success ? 'badge-green' : 'badge-red');
        b.textContent = t.size;
        badges.appendChild(b);
      });
      mp.appendChild(badges);
      grid.appendChild(mp);
    } else if (mtu.error) {
      grid.appendChild(this._makeErrorPanel('MTU', mtu.error));
    }

    // Multicast hub→site
    var mout = res.multicast_to_site || {};
    grid.appendChild(this._makeResultPanel('Multicast Hub \u2192 Site',
      mout.error ? 'badge-red' : (mout.received ? 'badge-green' : 'badge-red'),
      mout.error ? 'ERROR' : (mout.received ? 'PASSED' : 'FAILED')));

    // Multicast site→hub
    var mret = res.multicast_to_hub || {};
    grid.appendChild(this._makeResultPanel('Multicast Site \u2192 Hub',
      mret.error ? 'badge-red' : (mret.received ? 'badge-green' : 'badge-red'),
      mret.error ? 'ERROR' : (mret.received ? 'PASSED' : 'FAILED')));

    el.appendChild(grid);
  },

  // --- DOM Helpers ---
  _makeCard(label, value, color, sub) {
    var card = document.createElement('div');
    card.className = 'summary-card';
    var l = document.createElement('div');
    l.className = 'stat-label';
    l.textContent = label;
    card.appendChild(l);
    var v = document.createElement('div');
    v.className = 'stat-value';
    v.style.color = color;
    v.textContent = value;
    card.appendChild(v);
    if (sub) {
      var s = document.createElement('div');
      s.className = 'stat-sub';
      s.textContent = sub;
      card.appendChild(s);
    }
    return card;
  },

  _makeResultPanel(title, badgeClass, badgeText) {
    var panel = document.createElement('div');
    panel.className = 'panel';
    var hdr = document.createElement('div');
    hdr.className = 'panel-header';
    var t = document.createElement('span');
    t.className = 'panel-title';
    t.textContent = title;
    hdr.appendChild(t);
    var badge = document.createElement('span');
    badge.className = 'badge ' + badgeClass;
    badge.textContent = badgeText;
    hdr.appendChild(badge);
    panel.appendChild(hdr);
    return panel;
  },

  _makeErrorPanel(title, msg) {
    var panel = this._makeResultPanel(title, 'badge-red', 'ERROR');
    var body = document.createElement('div');
    body.style.cssText = 'padding:1rem;color:#ef4444';
    body.textContent = msg;
    panel.appendChild(body);
    return panel;
  },

  _showError(test, msg) {
    var el = document.getElementById('diagResults');
    if (!el) return;
    el.textContent = '';
    el.appendChild(this._makeErrorPanel(test, msg));
  },
};
