/* ==========================================================================
   Outpost Conduit — Dashboard View
   ========================================================================== */

window.DashboardView = {
  _listener: null,

  render(container) {
    // Show loading state immediately
    container.innerHTML = '<div class="container"><h2>Dashboard</h2><p class="subtitle">Loading...</p></div>';

    // Fetch initial data
    Api.get('/api/status')
      .then((data) => {
        if (data) {
          this._renderData(container, data);
        }
      })
      .catch(() => {
        container.innerHTML = '<div class="container"><h2>Dashboard</h2><p class="subtitle">Failed to load status</p></div>';
      });

    // Remove any previous listener
    if (this._listener) {
      window.removeEventListener('stats-update', this._listener);
    }

    // Listen for live updates
    this._listener = (e) => {
      this._renderData(container, e.detail);
    };
    window.addEventListener('stats-update', this._listener);
  },

  cleanup() {
    if (this._listener) {
      window.removeEventListener('stats-update', this._listener);
      this._listener = null;
    }
    if (this._captureWs) {
      this._captureWs.close();
      this._captureWs = null;
    }
  },

  _renderData(container, data) {
    const summary = data.summary || {};
    const sites = data.sites || [];
    const bridgePorts = data.bridge_ports || [];

    const total = summary.total || 0;
    const online = summary.online || 0;
    const stale = summary.stale || 0;
    const offline = summary.offline || 0;

    // Count site types
    let glinetCount = 0;
    let cradlepointCount = 0;
    for (let i = 0; i < sites.length; i++) {
      if (sites[i].type === 'cradlepoint') {
        cradlepointCount++;
      } else {
        glinetCount++;
      }
    }

    // Find worst offenders (oldest handshake) for stale and offline
    const staleWorst = this._worstOffender(sites, 'stale');
    const offlineWorst = this._worstOffender(sites, 'offline');

    // Build HTML
    let html = '<div class="container">';
    html += '<h2>Dashboard</h2>';
    html += '<p class="subtitle">Real-time VPN health overview</p>';

    // --- Summary cards ---
    html += '<div class="summary-cards">';

    // Total Sites (blue)
    html += '<div class="summary-card">';
    html += '<div class="card-label">Total Sites</div>';
    html += '<div class="card-value" style="color:#60a5fa">' + total + '</div>';
    html += '<div class="card-sub">' + glinetCount + ' GL.iNet &bull; ' + cradlepointCount + ' Cradlepoint</div>';
    html += '</div>';

    // Online (green)
    html += '<div class="summary-card">';
    html += '<div class="card-label">Online</div>';
    html += '<div class="card-value" style="color:#22c55e">' + online + '</div>';
    html += '<div class="card-sub">Handshake &lt; 5 min</div>';
    html += '</div>';

    // Stale (yellow)
    html += '<div class="summary-card">';
    html += '<div class="card-label">Stale</div>';
    html += '<div class="card-value" style="color:#eab308">' + stale + '</div>';
    html += '<div class="card-sub">' + (staleWorst ? Utils.escapeHtml(staleWorst) : 'None') + '</div>';
    html += '</div>';

    // Offline (red)
    html += '<div class="summary-card">';
    html += '<div class="card-label">Offline</div>';
    html += '<div class="card-value" style="color:#ef4444">' + offline + '</div>';
    html += '<div class="card-sub">' + (offlineWorst ? Utils.escapeHtml(offlineWorst) : 'None') + '</div>';
    html += '</div>';

    html += '</div>'; // .summary-cards

    // --- Sites table panel ---
    html += '<div class="panel">';
    html += '<div class="panel-header">';
    html += '<span class="panel-title">Sites</span>';
    html += '<div class="flex items-center gap-sm">';
    html += '<button class="btn btn-ghost btn-sm" onclick="DashboardView._exportAll()">&#8615; Export All</button>';
    html += '<button class="btn btn-primary btn-sm" onclick="location.hash=\'#sites\'">+ Add Site</button>';
    html += '</div>';
    html += '</div>';

    html += '<div class="table-wrap">';
    html += '<table>';
    html += '<thead><tr>';
    html += '<th>Name</th><th>Type</th><th>Status</th><th>Tunnel IP</th><th>Endpoint</th><th>Traffic</th><th>Last Seen</th><th>Actions</th>';
    html += '</tr></thead>';
    html += '<tbody>';

    if (sites.length === 0) {
      html += '<tr><td colspan="8" style="text-align:center;color:#64748b">No sites configured</td></tr>';
    }

    for (let i = 0; i < sites.length; i++) {
      const site = sites[i];
      const name = Utils.escapeHtml(site.name || '');
      const siteType = site.type || 'glinet';
      const status = site.status || 'offline';
      const tunnelIp = Utils.escapeHtml(site.tunnel_ip || '—');
      const endpoint = Utils.escapeHtml(site.endpoint || '—');
      const txBytes = Utils.formatBytes(site.tx_bytes);
      const rxBytes = Utils.formatBytes(site.rx_bytes);
      const lastSeen = site.last_handshake ? Utils.formatAge(site.last_handshake) : '—';

      // Type badge
      const typeClass = siteType === 'cradlepoint' ? 'type-cradlepoint' : 'type-glinet';
      const typeLabel = siteType === 'cradlepoint' ? 'Cradlepoint' : 'GL.iNet';

      // Status badge
      const statusBadge = this._statusBadge(status);

      // Last seen color
      const lastSeenColor = status === 'online' ? '#22c55e' : status === 'stale' ? '#eab308' : '#ef4444';

      html += '<tr>';
      html += '<td><strong>' + name + '</strong></td>';
      html += '<td><span class="type-tag ' + typeClass + '">' + typeLabel + '</span></td>';
      html += '<td>' + statusBadge + '</td>';
      html += '<td class="font-mono text-sm">' + tunnelIp + '</td>';
      html += '<td class="font-mono text-sm">' + endpoint + '</td>';
      html += '<td><span class="traffic-stat"><span class="tx">&uarr; ' + txBytes + '</span> <span class="rx">&darr; ' + rxBytes + '</span></span></td>';
      html += '<td style="color:' + lastSeenColor + '">' + lastSeen + '</td>';
      html += '<td>';
      html += '<div class="flex gap-sm">';
      html += '<button class="icon-btn" title="Terminal" onclick="location.hash=\'#deploy?site=' + encodeURIComponent(site.name || '') + '\'">&#9002;</button>';
      html += '<button class="icon-btn" title="Restart" onclick="DashboardView._restartSite(\'' + this._jsEscape(site.name || '') + '\')">&#8635;</button>';
      html += '<button class="icon-btn" title="Download config" onclick="window.open(\'/api/sites/' + encodeURIComponent(site.name || '') + '/download?token=\' + encodeURIComponent(Auth.getToken()),\'_blank\')">&#8615;</button>';
      html += '</div>';
      html += '</td>';
      html += '</tr>';
    }

    html += '</tbody></table>';
    html += '</div>'; // .table-wrap
    html += '</div>'; // .panel

    // --- Health status panel ---
    html += this._renderHealth(sites);

    // --- Radio log panel ---
    html += '<div class="panel" style="margin-top:1.5rem">';
    html += '<div class="panel-header">';
    html += '<span class="panel-title">\ud83d\udce1 Radio Traffic Log</span>';
    html += '<div class="flex items-center gap-sm">';
    html += '<button class="btn btn-ghost btn-sm" id="dashRadioRefresh">Refresh</button>';
    html += '<button class="btn btn-ghost btn-sm" id="dashRadioClear">Clear Log</button>';
    html += '</div>';
    html += '</div>';
    html += '<div id="dashRadioLog" style="padding:1rem;color:#94a3b8;font-size:0.85rem">Loading...</div>';
    html += '</div>';

    // --- Live multicast capture ---
    html += '<div class="panel" style="margin-top:1.5rem">';
    html += '<div class="panel-header">';
    html += '<span class="panel-title">Live Multicast Traffic</span>';
    html += '<div class="flex items-center gap-sm">';
    html += '<button class="btn btn-primary btn-sm" id="dashCaptureToggle">Start Capture</button>';
    html += '<button class="btn btn-ghost btn-sm" id="dashCapturePause" style="display:none">Pause</button>';
    html += '<button class="btn btn-ghost btn-sm" id="dashCaptureExport">Export .md</button>';
    html += '<button class="btn btn-ghost btn-sm" id="dashCaptureClear">Clear</button>';
    html += '<span class="text-muted text-xs" id="dashCaptureCount">0 packets</span>';
    html += '</div>';
    html += '</div>';
    html += '<div id="dashCaptureLog" class="log-output" style="max-height:1200px;font-size:11px;min-height:300px"></div>';
    html += '</div>';

    html += '</div>'; // .container

    container.innerHTML = html;

    // Load existing health data and radio log
    this._loadHealth();
    this._loadRadioLog();

    // Bind capture buttons
    this._capturePacketCount = 0;
    this._captureWs = null;
    this._capturePaused = false;
    this._captureData = [];
    var toggleBtn = document.getElementById('dashCaptureToggle');
    if (toggleBtn) {
      toggleBtn.addEventListener('click', () => this._toggleCapture());
    }
    var pauseBtn = document.getElementById('dashCapturePause');
    if (pauseBtn) {
      pauseBtn.addEventListener('click', () => {
        this._capturePaused = !this._capturePaused;
        pauseBtn.textContent = this._capturePaused ? 'Resume' : 'Pause';
        pauseBtn.className = this._capturePaused ? 'btn btn-primary btn-sm' : 'btn btn-ghost btn-sm';
      });
    }
    var exportBtn = document.getElementById('dashCaptureExport');
    if (exportBtn) {
      exportBtn.addEventListener('click', () => this._exportCapture());
    }
    var radioRefresh = document.getElementById('dashRadioRefresh');
    if (radioRefresh) {
      radioRefresh.addEventListener('click', () => this._loadRadioLog());
    }
    var radioClear = document.getElementById('dashRadioClear');
    if (radioClear) {
      radioClear.addEventListener('click', async () => {
        await Api.del('/api/radio-log');
        this._loadRadioLog();
      });
    }
    var clearBtn = document.getElementById('dashCaptureClear');
    if (clearBtn) {
      clearBtn.addEventListener('click', () => {
        var log = document.getElementById('dashCaptureLog');
        if (log) log.textContent = '';
        this._capturePacketCount = 0;
        this._captureData = [];
        var cnt = document.getElementById('dashCaptureCount');
        if (cnt) cnt.textContent = '0 packets';
      });
    }

    // Bind "Run All Tests Now" button
    var runBtn = document.getElementById('dashRunHealth');
    if (runBtn) {
      runBtn.addEventListener('click', () => this._runHealthNow());
    }
  },

  async _loadHealth() {
    try {
      var health = await Api.get('/api/settings/health');
      if (health && health.sites) {
        this._renderHealthData(health);
      }
    } catch (err) {
      // Health data not available yet
    }
  },

  async _runHealthNow() {
    var btn = document.getElementById('dashRunHealth');
    if (btn) {
      btn.disabled = true;
      btn.textContent = 'Testing all sites...';
    }

    // Show progress in the health grid
    var grid = document.getElementById('dashHealthGrid');
    if (grid) {
      var progressDiv = document.createElement('div');
      progressDiv.style.cssText = 'grid-column:1/-1;padding:1rem;color:#94a3b8;text-align:center';
      progressDiv.textContent = 'Running ping + multicast tests on all sites... this may take a few minutes.';
      grid.insertBefore(progressDiv, grid.firstChild);
    }

    try {
      var health = await Api.post('/api/settings/health/run');
      if (health && health.sites) {
        this._renderHealthData(health);
      }
    } catch (err) {
      if (grid) {
        grid.textContent = 'Health check failed: ' + err.message;
        grid.style.color = '#ef4444';
      }
    }

    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Run All Tests Now';
    }
  },

  _renderHealth(sites) {
    let html = '<div class="panel">';
    html += '<div class="panel-header">';
    html += '<span class="panel-title">Health Monitor</span>';
    html += '<div class="flex items-center gap-sm">';
    html += '<button class="btn btn-primary btn-sm" id="dashRunHealth">Run All Tests Now</button>';
    html += '<a href="#settings" class="btn btn-ghost btn-sm">Configure</a>';
    html += '</div>';
    html += '</div>';
    html += '<div id="dashHealthGrid" class="bridge-grid">';
    // Placeholder — filled by _renderHealthData
    for (let i = 0; i < sites.length; i++) {
      const name = Utils.escapeHtml(sites[i].name || '');
      html += '<div class="bridge-card">';
      html += '<div class="bridge-card-header">';
      html += '<span class="bridge-card-name font-mono" style="color:#60a5fa">' + name + '</span>';
      html += '<span class="badge badge-gray">Pending</span>';
      html += '</div>';
      html += '<div class="bridge-card-detail">';
      html += '<span class="text-muted text-sm">Waiting for health check...</span>';
      html += '</div>';
      html += '</div>';
    }
    html += '</div>';
    html += '</div>';
    return html;
  },

  _renderHealthData(health) {
    const grid = document.getElementById('dashHealthGrid');
    if (!grid) return;

    const sites = health.sites || {};
    let cards = '';

    for (const name in sites) {
      const s = sites[name];
      const ping = s.ping || {};
      const mcastOut = s.multicast_out || {};
      const mcastIn = s.multicast_in || {};

      const pingOk = ping.packet_loss_pct !== undefined && ping.packet_loss_pct < 50;
      const mcastOutOk = mcastOut.received === true;
      const mcastInOk = mcastIn.received === true;
      const allOk = pingOk && mcastOutOk && mcastInOk;

      const overallBadge = allOk ? 'badge-green' : 'badge-red';
      const overallText = allOk ? 'Healthy' : 'Issues';

      const latency = ping.rtt_avg ? ping.rtt_avg.toFixed(1) + 'ms' : '\u2014';
      const loss = ping.packet_loss_pct !== undefined ? ping.packet_loss_pct + '%' : '\u2014';

      const age = s.timestamp ? Utils.formatAge(s.timestamp) : '';

      cards += '<div class="bridge-card">';
      cards += '<div class="bridge-card-header">';
      cards += '<span class="bridge-card-name font-mono" style="color:#60a5fa">' + Utils.escapeHtml(name) + '</span>';
      cards += '<span class="badge ' + overallBadge + '">' + overallText + '</span>';
      cards += '</div>';
      cards += '<div class="bridge-card-detail" style="display:flex;gap:1rem;flex-wrap:wrap">';
      cards += '<span class="text-sm">Ping: <strong style="color:' + (pingOk ? '#22c55e' : '#ef4444') + '">' + latency + '</strong> (' + loss + ' loss)</span>';
      cards += '<span class="text-sm">Mcast \u2192: <strong style="color:' + (mcastOutOk ? '#22c55e' : '#ef4444') + '">' + (mcastOutOk ? 'OK' : 'FAIL') + '</strong></span>';
      cards += '<span class="text-sm">Mcast \u2190: <strong style="color:' + (mcastInOk ? '#22c55e' : '#ef4444') + '">' + (mcastInOk ? 'OK' : 'FAIL') + '</strong></span>';
      if (age) cards += '<span class="text-muted text-xs">' + age + '</span>';
      cards += '</div>';
      cards += '</div>';
    }

    grid.innerHTML = cards;
  },

  _statusBadge(status) {
    const cls = status === 'online' ? 'badge-green'
      : status === 'stale' ? 'badge-yellow'
      : 'badge-red';
    const label = status.charAt(0).toUpperCase() + status.slice(1);
    return '<span class="badge ' + cls + '">' + label + '</span>';
  },

  _worstOffender(sites, status) {
    let worst = null;
    let worstAge = -1;
    for (let i = 0; i < sites.length; i++) {
      if (sites[i].status === status) {
        const hs = sites[i].last_handshake || 0;
        // For offline, handshake is 0 (never). For stale, oldest = smallest non-zero handshake.
        if (status === 'offline') {
          // Any offline site — just pick the first one
          if (!worst) worst = sites[i].name;
        } else {
          // Stale: oldest handshake = smallest timestamp
          if (hs > 0 && (worstAge < 0 || hs < worstAge)) {
            worstAge = hs;
            worst = sites[i].name;
          }
        }
      }
    }
    return worst;
  },

  _jsEscape(str) {
    return str.replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/"/g, '\\"');
  },

  async _restartSite(name) {
    if (!confirm('Restart WireGuard + GRETAP on "' + name + '"?')) {
      return;
    }
    try {
      const result = await Api.post('/api/sites/' + encodeURIComponent(name) + '/restart');
      alert('Restart successful:\n' + (result.output || result.message || 'OK'));
    } catch (err) {
      alert('Restart failed: ' + err.message);
    }
  },

  async _loadRadioLog() {
    var container = document.getElementById('dashRadioLog');
    if (!container) return;

    try {
      var entries = await Api.get('/api/radio-log');
      if (!entries || entries.length === 0) {
        container.textContent = 'No radio traffic detected yet. Start a capture to begin monitoring.';
        return;
      }

      container.textContent = '';
      var table = document.createElement('table');
      table.style.width = '100%';
      var thead = document.createElement('thead');
      var hRow = document.createElement('tr');
      ['Time', 'Source IP', 'MAC', 'Device', 'Services', 'Hostnames'].forEach(function(h) {
        var th = document.createElement('th');
        th.textContent = h;
        hRow.appendChild(th);
      });
      thead.appendChild(hRow);
      table.appendChild(thead);

      var tbody = document.createElement('tbody');
      // Show newest first
      for (var i = entries.length - 1; i >= Math.max(0, entries.length - 50); i--) {
        var e = entries[i];
        var tr = document.createElement('tr');
        tr.style.background = '#22c55e08';

        var tdTime = document.createElement('td');
        tdTime.className = 'font-mono text-sm';
        tdTime.textContent = e.logged_at || e.timestamp || '';
        tr.appendChild(tdTime);

        var tdSrc = document.createElement('td');
        tdSrc.className = 'font-mono text-sm';
        tdSrc.textContent = e.src_ip || '';
        tr.appendChild(tdSrc);

        var tdMac = document.createElement('td');
        tdMac.className = 'font-mono text-sm text-muted';
        tdMac.textContent = e.src_mac || '';
        tr.appendChild(tdMac);

        var tdDevice = document.createElement('td');
        tdDevice.className = 'text-sm';
        tdDevice.style.color = '#22c55e';
        tdDevice.textContent = e.device_info || '';
        tr.appendChild(tdDevice);

        var tdSvc = document.createElement('td');
        tdSvc.className = 'text-sm text-secondary';
        tdSvc.textContent = (e.services || []).join(', ');
        tr.appendChild(tdSvc);

        var tdHost = document.createElement('td');
        tdHost.className = 'text-sm';
        tdHost.textContent = (e.hostnames || []).join(', ');
        tr.appendChild(tdHost);

        tbody.appendChild(tr);
      }
      table.appendChild(tbody);
      container.appendChild(table);

      var count = document.createElement('p');
      count.className = 'text-muted text-xs';
      count.style.marginTop = '0.5rem';
      count.textContent = entries.length + ' total entries (showing last 50)';
      container.appendChild(count);

    } catch (err) {
      container.textContent = 'Failed to load radio log: ' + err.message;
    }
  },

  _toggleCapture() {
    var btn = document.getElementById('dashCaptureToggle');
    var pauseBtn = document.getElementById('dashCapturePause');
    if (this._captureWs) {
      // Stop capture
      try { this._captureWs.close(); } catch(e) {}
      this._captureWs = null;
      if (btn) {
        btn.textContent = 'Start Capture';
        btn.className = 'btn btn-primary btn-sm';
      }
      if (pauseBtn) pauseBtn.style.display = 'none';
      return;
    }

    // Start capture
    if (btn) {
      btn.textContent = 'Stop Capture';
      btn.className = 'btn btn-danger btn-sm';
    }
    if (pauseBtn) {
      pauseBtn.style.display = '';
      pauseBtn.textContent = 'Pause';
      this._capturePaused = false;
    }

    var proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    var url = proto + '//' + window.location.host + '/api/ws/multicast?token=' + encodeURIComponent(Auth.getToken());
    var ws = new WebSocket(url);
    this._captureWs = ws;
    var self = this;

    ws.onmessage = function(event) {
      try {
        var pkt = JSON.parse(event.data);
        if (pkt.type === 'keepalive') return;
        if (pkt.type !== 'packet') return;

        // Store for export
        self._captureData.push(pkt);
        if (self._captureData.length > 1000) self._captureData.shift();

        // Skip rendering if paused
        if (self._capturePaused) return;

        self._capturePacketCount++;
        var cnt = document.getElementById('dashCaptureCount');
        if (cnt) cnt.textContent = self._capturePacketCount + ' packets';

        var log = document.getElementById('dashCaptureLog');
        if (!log) return;

        // Detect if this packet might be from a Motorola/APX radio
        var isRadio = self._detectRadio(pkt);

        var entry = document.createElement('div');
        entry.style.cssText = 'border-bottom:1px solid #1e2130;padding:3px 0';
        if (isRadio) {
          entry.style.cssText += ';background:#22c55e11;border-left:3px solid #22c55e;padding-left:8px';
        }

        // Line 1: timestamp, protocol, flow, size
        var line1 = document.createElement('div');
        line1.style.cssText = 'display:flex;gap:0.75rem;white-space:nowrap';

        var ts = document.createElement('span');
        ts.style.color = '#64748b';
        ts.textContent = pkt.timestamp || '';
        line1.appendChild(ts);

        var proto = document.createElement('span');
        proto.style.cssText = 'min-width:50px;font-weight:600';
        var pcolor = pkt.protocol === 'mDNS' ? '#22c55e' : pkt.protocol === 'SSDP' ? '#eab308' : pkt.protocol === 'Relay' ? '#a78bfa' : '#60a5fa';
        proto.style.color = pcolor;
        var qtype = pkt.query_type === 'query' ? ' Q' : pkt.query_type === 'response' ? ' R' : '';
        proto.textContent = (pkt.protocol || 'UDP') + qtype;
        line1.appendChild(proto);

        var flow = document.createElement('span');
        flow.style.color = '#e0e0e0';
        flow.textContent = (pkt.src_ip || '?') + ' \u2192 ' + (pkt.dst_ip || '?');
        line1.appendChild(flow);

        if (pkt.src_mac) {
          var mac = document.createElement('span');
          mac.style.color = '#475569';
          mac.textContent = pkt.src_mac;
          line1.appendChild(mac);
        }

        if (pkt.length) {
          var sz = document.createElement('span');
          sz.style.color = '#64748b';
          sz.textContent = pkt.length + 'B';
          line1.appendChild(sz);
        }

        if (isRadio) {
          var badge = document.createElement('span');
          badge.style.cssText = 'background:#22c55e33;color:#22c55e;padding:1px 6px;border-radius:3px;font-size:10px;font-weight:700';
          badge.textContent = '\ud83d\udce1 RADIO';
          line1.appendChild(badge);
        }

        entry.appendChild(line1);

        // Line 2: mDNS details (services, hostnames, device info, txt records)
        var details = [];

        if (pkt.hostnames && pkt.hostnames.length) {
          details.push('\ud83c\udff7\ufe0f ' + pkt.hostnames.join(', '));
        }
        if (pkt.device_info) {
          details.push('\ud83d\udcf1 ' + pkt.device_info);
        }
        if (pkt.services && pkt.services.length) {
          details.push('\ud83d\udd0c ' + pkt.services.join(', '));
        }
        if (pkt.addresses && pkt.addresses.length) {
          details.push('IP: ' + pkt.addresses.join(', '));
        }
        if (pkt.srvs && pkt.srvs.length) {
          details.push('SRV: ' + pkt.srvs.map(function(s) { return s.host + ':' + s.port; }).join(', '));
        }
        if (pkt.ptrs && pkt.ptrs.length) {
          // Show PTR records but truncate if too many
          var ptrList = pkt.ptrs.slice(0, 4).join(', ');
          if (pkt.ptrs.length > 4) ptrList += ' +' + (pkt.ptrs.length - 4) + ' more';
          details.push('PTR: ' + ptrList);
        }
        if (pkt.txt && pkt.txt.length) {
          // Show interesting TXT key=value pairs (filter noise)
          var interesting = pkt.txt.filter(function(t) {
            var k = t.split('=')[0].toLowerCase();
            return ['manufacturer', 'model', 'md', 'serialnumber', 'deviceid', 'name', 'id', 'fn'].indexOf(k) >= 0;
          });
          if (interesting.length) {
            details.push('TXT: ' + interesting.join(', '));
          }
        }

        if (details.length > 0) {
          var line2 = document.createElement('div');
          line2.style.cssText = 'padding-left:4rem;color:#94a3b8;font-size:10px;white-space:normal;word-break:break-all';
          line2.textContent = details.join('  |  ');
          entry.appendChild(line2);
        }

        log.appendChild(entry);

        // Auto-scroll and limit to 200 lines
        log.scrollTop = log.scrollHeight;
        while (log.childNodes.length > 200) {
          log.removeChild(log.firstChild);
        }
      } catch (e) {
        // ignore parse errors
      }
    };

    ws.onclose = function() {
      self._captureWs = null;
      if (btn) {
        btn.textContent = 'Start Capture';
        btn.className = 'btn btn-primary btn-sm';
      }
    };
  },

  _exportCapture() {
    var data = this._captureData || [];
    if (data.length === 0) {
      alert('No capture data to export.');
      return;
    }

    var lines = [];
    lines.push('# Outpost Conduit — Multicast Capture');
    lines.push('');
    lines.push('**Exported:** ' + new Date().toISOString());
    lines.push('**Packets:** ' + data.length);
    lines.push('');
    lines.push('---');
    lines.push('');

    // Summary — count by protocol
    var protoCounts = {};
    var radioPkts = [];
    for (var i = 0; i < data.length; i++) {
      var p = data[i];
      var proto = p.protocol || 'unknown';
      protoCounts[proto] = (protoCounts[proto] || 0) + 1;
      if (this._detectRadio(p)) radioPkts.push(p);
    }

    lines.push('## Summary');
    lines.push('');
    lines.push('| Protocol | Count |');
    lines.push('|---|---|');
    for (var proto in protoCounts) {
      lines.push('| ' + proto + ' | ' + protoCounts[proto] + ' |');
    }
    lines.push('');

    if (radioPkts.length > 0) {
      lines.push('## Radio Traffic Detected (' + radioPkts.length + ' packets)');
      lines.push('');
      for (var r = 0; r < radioPkts.length; r++) {
        var rp = radioPkts[r];
        lines.push('- **' + (rp.timestamp || '') + '** ' + (rp.src_ip || '?') + ' → ' + (rp.dst_ip || '?'));
        if (rp.hostnames) lines.push('  - Hostnames: ' + rp.hostnames.join(', '));
        if (rp.device_info) lines.push('  - Device: ' + rp.device_info);
        if (rp.services) lines.push('  - Services: ' + rp.services.join(', '));
        if (rp.txt) lines.push('  - TXT: ' + rp.txt.join(', '));
      }
      lines.push('');
    }

    lines.push('## All Packets');
    lines.push('');
    lines.push('| # | Time | Proto | Source | Dest | Size | Details |');
    lines.push('|---|---|---|---|---|---|---|');
    for (var j = 0; j < data.length; j++) {
      var pk = data[j];
      var isR = this._detectRadio(pk) ? ' **RADIO**' : '';
      var details = [];
      if (pk.hostnames) details.push(pk.hostnames.join(', '));
      if (pk.services) details.push(pk.services.join(', '));
      if (pk.device_info) details.push(pk.device_info);
      lines.push('| ' + (j + 1) + ' | ' + (pk.timestamp || '') + ' | ' + (pk.protocol || '') + ' | ' + (pk.src_ip || '?') + ' | ' + (pk.dst_ip || '?') + ' | ' + (pk.length || '') + ' | ' + details.join('; ') + isR + ' |');
    }

    var md = lines.join('\n');
    var blob = new Blob([md], {type: 'text/markdown'});
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = 'multicast-capture-' + new Date().toISOString().slice(0, 19).replace(/:/g, '') + '.md';
    a.click();
    URL.revokeObjectURL(url);
  },

  _detectRadio(pkt) {
    // Look for Motorola/APX radio indicators in the packet data
    var raw = (pkt.raw || '').toLowerCase();
    var checks = [
      // Manufacturer/model identifiers
      pkt.device_info && /motorola|apx|astro|mototrbo/i.test(pkt.device_info),
      // Service names specific to Motorola radio management
      pkt.services && pkt.services.some(function(s) {
        return /motorola|moto|apx|astro|trbo|p25|issi|cssi|dfsi|xcmp|xnl/i.test(s);
      }),
      // Hostnames
      pkt.hostnames && pkt.hostnames.some(function(h) {
        return /motorola|apx|astro|trbo|moto/i.test(h);
      }),
      // PTR records
      pkt.ptrs && pkt.ptrs.some(function(p) {
        return /motorola|apx|astro|trbo|moto|xcmp|xnl/i.test(p);
      }),
      // TXT records mentioning Motorola
      pkt.txt && pkt.txt.some(function(t) {
        return /motorola|apx|astro|trbo/i.test(t);
      }),
      // Raw packet data
      /motorola|apx\d|astro|mototrbo|xcmp|xnl/i.test(raw),
    ];
    return checks.some(function(c) { return c; });
  },

  _exportAll() {
    // Open the sites list endpoint or download all configs — just trigger download for each
    // For simplicity, navigate to sites view where export can be managed
    const sites = (window._latestStats && window._latestStats.sites) || [];
    if (sites.length === 0) {
      alert('No sites to export');
      return;
    }
    // Download each site config as a zip
    for (let i = 0; i < sites.length; i++) {
      window.open('/api/sites/' + encodeURIComponent(sites[i].name) + '/download?token=' + encodeURIComponent(Auth.getToken()), '_blank');
    }
  },
};
