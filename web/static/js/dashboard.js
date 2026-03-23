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

    // --- Live multicast capture ---
    html += '<div class="panel" style="margin-top:1.5rem">';
    html += '<div class="panel-header">';
    html += '<span class="panel-title">Live Multicast Traffic</span>';
    html += '<div class="flex items-center gap-sm">';
    html += '<button class="btn btn-primary btn-sm" id="dashCaptureToggle">Start Capture</button>';
    html += '<button class="btn btn-ghost btn-sm" id="dashCaptureClear">Clear</button>';
    html += '<span class="text-muted text-xs" id="dashCaptureCount">0 packets</span>';
    html += '</div>';
    html += '</div>';
    html += '<div id="dashCaptureLog" class="log-output" style="max-height:300px;font-size:11px;min-height:80px"></div>';
    html += '</div>';

    html += '</div>'; // .container

    container.innerHTML = html;

    // Load existing health data
    this._loadHealth();

    // Bind capture buttons
    this._capturePacketCount = 0;
    this._captureWs = null;
    var toggleBtn = document.getElementById('dashCaptureToggle');
    if (toggleBtn) {
      toggleBtn.addEventListener('click', () => this._toggleCapture());
    }
    var clearBtn = document.getElementById('dashCaptureClear');
    if (clearBtn) {
      clearBtn.addEventListener('click', () => {
        var log = document.getElementById('dashCaptureLog');
        if (log) log.textContent = '';
        this._capturePacketCount = 0;
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

  _toggleCapture() {
    var btn = document.getElementById('dashCaptureToggle');
    if (this._captureWs) {
      // Stop capture
      this._captureWs.close();
      this._captureWs = null;
      if (btn) {
        btn.textContent = 'Start Capture';
        btn.className = 'btn btn-primary btn-sm';
      }
      return;
    }

    // Start capture
    if (btn) {
      btn.textContent = 'Stop Capture';
      btn.className = 'btn btn-danger btn-sm';
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

        self._capturePacketCount++;
        var cnt = document.getElementById('dashCaptureCount');
        if (cnt) cnt.textContent = self._capturePacketCount + ' packets';

        var log = document.getElementById('dashCaptureLog');
        if (!log) return;

        var line = document.createElement('div');
        line.style.cssText = 'display:flex;gap:0.75rem;white-space:nowrap';

        // Timestamp
        var ts = document.createElement('span');
        ts.style.color = '#64748b';
        ts.textContent = pkt.timestamp || '';
        line.appendChild(ts);

        // Protocol badge
        var proto = document.createElement('span');
        proto.style.cssText = 'min-width:50px';
        var pcolor = pkt.protocol === 'mDNS' ? '#22c55e' : pkt.protocol === 'SSDP' ? '#eab308' : pkt.protocol === 'Relay' ? '#a78bfa' : '#60a5fa';
        proto.style.color = pcolor;
        proto.textContent = pkt.protocol || 'UDP';
        line.appendChild(proto);

        // Source → Dest
        var flow = document.createElement('span');
        flow.style.color = '#e0e0e0';
        var srcIp = pkt.src_ip || '?';
        var dstIp = pkt.dst_ip || '?';
        var srcPort = pkt.src_port || '';
        var dstPort = pkt.dst_port || '';
        flow.textContent = srcIp + ':' + srcPort + ' \u2192 ' + dstIp + ':' + dstPort;
        line.appendChild(flow);

        // Size
        if (pkt.length) {
          var sz = document.createElement('span');
          sz.style.color = '#64748b';
          sz.textContent = pkt.length + 'B';
          line.appendChild(sz);
        }

        log.appendChild(line);

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
