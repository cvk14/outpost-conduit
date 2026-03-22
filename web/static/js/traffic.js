/* ==========================================================================
   Outpost Conduit — Traffic View
   ========================================================================== */

window.TrafficView = {
  _listener: null,

  render(container) {
    // Show loading state immediately
    container.innerHTML = '<div class="container"><h2>Traffic</h2><p class="subtitle">Loading...</p></div>';

    // Fetch initial data
    Api.get('/api/status')
      .then((data) => {
        if (data) {
          this._renderData(container, data);
        }
      })
      .catch(() => {
        container.innerHTML = '<div class="container"><h2>Traffic</h2><p class="subtitle">Failed to load traffic data</p></div>';
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
    const sites = data.sites || [];
    const bridgePorts = data.bridge_ports || [];

    let html = '<div class="container">';
    html += '<h2>Traffic</h2>';
    html += '<p class="subtitle">Per-site bandwidth and bridge port statistics</p>';

    // --- Per-site bandwidth section ---
    html += this._renderSiteTraffic(sites);

    // --- Bridge port stats section ---
    html += this._renderBridgePorts(bridgePorts);

    html += '</div>'; // .container

    container.innerHTML = html;
  },

  _renderSiteTraffic(sites) {
    let html = '<div class="panel">';
    html += '<div class="panel-header">';
    html += '<span class="panel-title">Site Traffic</span>';
    html += '</div>';

    if (sites.length === 0) {
      html += '<p class="text-muted text-sm">No sites configured</p>';
      html += '</div>';
      return html;
    }

    // Find max TX and RX across all sites for proportional bars
    let maxTx = 0;
    let maxRx = 0;
    for (let i = 0; i < sites.length; i++) {
      const tx = sites[i].tx_bytes || 0;
      const rx = sites[i].rx_bytes || 0;
      if (tx > maxTx) maxTx = tx;
      if (rx > maxRx) maxRx = rx;
    }

    for (let i = 0; i < sites.length; i++) {
      const site = sites[i];
      const name = Utils.escapeHtml(site.name || '');
      const tx = site.tx_bytes || 0;
      const rx = site.rx_bytes || 0;

      const txPct = maxTx > 0 ? (tx / maxTx * 100).toFixed(1) : 0;
      const rxPct = maxRx > 0 ? (rx / maxRx * 100).toFixed(1) : 0;

      const txLabel = Utils.formatBytes(tx);
      const rxLabel = Utils.formatBytes(rx);

      html += '<div style="margin-bottom:1rem">';

      // Site name row
      html += '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:0.375rem">';
      html += '<span style="font-weight:600;font-size:0.875rem">' + name + '</span>';
      html += '</div>';

      // TX bar row
      html += '<div style="display:flex;align-items:center;gap:0.75rem;margin-bottom:0.25rem">';
      html += '<span style="width:2.5rem;font-size:0.75rem;color:#60a5fa;text-align:right;flex-shrink:0">TX</span>';
      html += '<div style="flex:1;background:#2a2d3a;border-radius:3px;height:10px;overflow:hidden">';
      html += '<div style="background:#22c55e;width:' + txPct + '%;height:100%;border-radius:3px"></div>';
      html += '</div>';
      html += '<span class="traffic-stat" style="width:6rem;text-align:right;flex-shrink:0">' + txLabel + '</span>';
      html += '</div>';

      // RX bar row
      html += '<div style="display:flex;align-items:center;gap:0.75rem">';
      html += '<span style="width:2.5rem;font-size:0.75rem;color:#60a5fa;text-align:right;flex-shrink:0">RX</span>';
      html += '<div style="flex:1;background:#2a2d3a;border-radius:3px;height:10px;overflow:hidden">';
      html += '<div style="background:#60a5fa;width:' + rxPct + '%;height:100%;border-radius:3px"></div>';
      html += '</div>';
      html += '<span class="traffic-stat" style="width:6rem;text-align:right;flex-shrink:0">' + rxLabel + '</span>';
      html += '</div>';

      html += '</div>'; // site row
    }

    html += '</div>'; // .panel
    return html;
  },

  _renderBridgePorts(bridgePorts) {
    let html = '<div class="panel">';
    html += '<div class="panel-header">';
    html += '<span class="panel-title">Bridge Ports</span>';
    html += '</div>';

    if (bridgePorts.length === 0) {
      html += '<p class="text-muted text-sm">No bridge ports found</p>';
      html += '</div>';
      return html;
    }

    html += '<div class="table-wrap">';
    html += '<table>';
    html += '<thead><tr>';
    html += '<th>Port Name</th>';
    html += '<th>State</th>';
    html += '<th>RX Bytes</th>';
    html += '<th>RX Packets</th>';
    html += '<th>RX Errors</th>';
    html += '<th>TX Bytes</th>';
    html += '<th>TX Packets</th>';
    html += '<th>TX Errors</th>';
    html += '</tr></thead>';
    html += '<tbody>';

    for (let i = 0; i < bridgePorts.length; i++) {
      const port = bridgePorts[i];
      const portName = Utils.escapeHtml(port.name || '');
      const portState = (port.state || 'unknown').toUpperCase();

      const stateBadgeClass = portState === 'FORWARDING' ? 'badge-green'
        : portState === 'LEARNING' ? 'badge-yellow'
        : portState === 'DISABLED' ? 'badge-red'
        : portState === 'BLOCKING' ? 'badge-red'
        : 'badge-gray';

      const rxBytes = Utils.formatBytes(port.rx_bytes);
      const rxPackets = (port.rx_packets || 0).toLocaleString();
      const rxErrors = (port.rx_errors || 0).toLocaleString();
      const txBytes = Utils.formatBytes(port.tx_bytes);
      const txPackets = (port.tx_packets || 0).toLocaleString();
      const txErrors = (port.tx_errors || 0).toLocaleString();

      html += '<tr>';
      html += '<td class="font-mono" style="color:#60a5fa">' + portName + '</td>';
      html += '<td><span class="badge ' + stateBadgeClass + '">' + portState + '</span></td>';
      html += '<td class="traffic-stat">' + rxBytes + '</td>';
      html += '<td class="text-secondary text-sm">' + rxPackets + '</td>';
      html += '<td class="text-secondary text-sm">' + rxErrors + '</td>';
      html += '<td class="traffic-stat">' + txBytes + '</td>';
      html += '<td class="text-secondary text-sm">' + txPackets + '</td>';
      html += '<td class="text-secondary text-sm">' + txErrors + '</td>';
      html += '</tr>';
    }

    html += '</tbody></table>';
    html += '</div>'; // .table-wrap
    html += '</div>'; // .panel
    return html;
  },
};
