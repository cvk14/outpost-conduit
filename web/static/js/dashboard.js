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
      html += '<button class="icon-btn" title="Download config" onclick="window.open(\'/api/sites/' + encodeURIComponent(site.name || '') + '/download\',\'_blank\')">&#8615;</button>';
      html += '</div>';
      html += '</td>';
      html += '</tr>';
    }

    html += '</tbody></table>';
    html += '</div>'; // .table-wrap
    html += '</div>'; // .panel

    // --- Bridge status panel ---
    html += this._renderBridge(bridgePorts);

    html += '</div>'; // .container

    container.innerHTML = html;
  },

  _renderBridge(bridgePorts) {
    if (!bridgePorts || bridgePorts.length === 0) {
      return '';
    }

    // Determine overall STP state — use the most common or first port state
    let stpState = 'unknown';
    const stateCounts = {};
    for (let i = 0; i < bridgePorts.length; i++) {
      const s = (bridgePorts[i].state || 'unknown').toUpperCase();
      stateCounts[s] = (stateCounts[s] || 0) + 1;
      if (i === 0) stpState = s;
    }

    // STP badge color
    const stpBadgeClass = stpState === 'FORWARDING' ? 'badge-green'
      : stpState === 'LEARNING' ? 'badge-yellow'
      : stpState === 'DISABLED' ? 'badge-red'
      : 'badge-gray';

    let html = '<div class="panel">';
    html += '<div class="panel-header">';
    html += '<span class="panel-title">Bridge: br-mcast</span>';
    html += '<div class="flex items-center gap-sm">';
    html += '<span class="badge ' + stpBadgeClass + '">' + Utils.escapeHtml(stpState) + '</span>';
    html += '</div>';
    html += '</div>';

    html += '<div class="bridge-grid">';

    for (let i = 0; i < bridgePorts.length; i++) {
      const port = bridgePorts[i];
      const portName = Utils.escapeHtml(port.name || '');
      const portState = (port.state || 'unknown').toUpperCase();

      // Determine if this is the physical multicast NIC (typically eth1 or similar, not a gretap/wg port)
      const isPhysicalNic = !portName.startsWith('gretap') && !portName.startsWith('wg') && portName !== 'br-mcast';
      const labelSuffix = isPhysicalNic ? ' <span class="text-muted text-xs">(multicast NIC)</span>' : '';

      // State badge
      const portBadgeClass = portState === 'FORWARDING' ? 'badge-green'
        : portState === 'LEARNING' ? 'badge-yellow'
        : portState === 'DISABLED' ? 'badge-red'
        : portState === 'BLOCKING' ? 'badge-red'
        : 'badge-gray';

      html += '<div class="bridge-card">';
      html += '<div class="bridge-card-header">';
      html += '<span class="bridge-card-name font-mono" style="color:#60a5fa">' + portName + labelSuffix + '</span>';
      html += '<span class="badge ' + portBadgeClass + '">' + portState + '</span>';
      html += '</div>';

      html += '<div class="bridge-card-detail">';
      html += '<span class="traffic-stat">';
      html += '<span class="tx">&uarr; TX ' + Utils.formatBytes(port.tx_bytes) + '</span>';
      html += ' &middot; ';
      html += '<span class="rx">&darr; RX ' + Utils.formatBytes(port.rx_bytes) + '</span>';
      html += ' &middot; ';
      html += 'Err ' + ((port.rx_errors || 0) + (port.tx_errors || 0));
      html += '</span>';
      html += '</div>';

      html += '</div>'; // .bridge-card
    }

    html += '</div>'; // .bridge-grid
    html += '</div>'; // .panel

    return html;
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
      window.open('/api/sites/' + encodeURIComponent(sites[i].name) + '/download', '_blank');
    }
  },
};
