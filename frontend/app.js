const $ = (id) => document.getElementById(id);
const state = { data: null, csrf: null, sessionFilter: 'all', toastTimer: null, ws: null, wsRetry: 0, lastQrUrl: null, commandIndex: 0, commandItems: [] };

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set('Accept', 'application/json');
  if (options.body) headers.set('Content-Type', 'application/json');
  if (options.method && options.method !== 'GET' && state.csrf) headers.set('X-Live-Server-CSRF', state.csrf);
  const response = await fetch(path, { ...options, headers, cache: 'no-store' });
  let data = {};
  try { data = await response.json(); } catch (_) {}
  if (!response.ok) throw new Error(data.detail || data.error || `Request failed (${response.status})`);
  return data;
}

function toast(message, error = false) {
  const el = $('toast');
  el.textContent = message;
  el.className = `toast show${error ? ' error' : ''}`;
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => { el.className = 'toast'; }, 3400);
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
}

function formatUptime(seconds) {
  if (!seconds) return '—';
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return h ? `${h}h ${m}m` : m ? `${m}m ${sec}s` : `${sec}s`;
}

function formatTime(iso) {
  try { return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }); }
  catch { return iso || '—'; }
}

function browserLabel(ua) {
  const text = String(ua || 'Unknown browser');
  if (/Edg\//i.test(text)) return 'Microsoft Edge';
  if (/Chrome\//i.test(text) && !/Edg\//i.test(text)) return 'Google Chrome';
  if (/Firefox\//i.test(text)) return 'Firefox';
  if (/Safari\//i.test(text) && !/Chrome\//i.test(text)) return 'Safari';
  if (/SamsungBrowser/i.test(text)) return 'Samsung Internet';
  if (/Android/i.test(text)) return 'Android browser';
  return 'Browser session';
}

function renderLogs(logs = []) {
  const rows = logs.slice(-30).reverse().map(item => `
    <div class="log-item">
      <time>${formatTime(item.time)}</time>
      <b class="level-${escapeHtml(item.level)}">${escapeHtml(item.level)}</b>
      <p>${escapeHtml(item.message)}</p>
    </div>`).join('');
  $('activity-log').innerHTML = rows || '<div class="log-item"><time>—</time><b>INFO</b><p>No events recorded yet.</p></div>';
  $('logs-pre').textContent = logs.map(item => `[${formatTime(item.time)}] ${String(item.level).padEnd(8)} ${item.message}`).join('\n') || 'No log entries.';
  $('log-count').textContent = `${logs.length} entries`;
}

function renderSessions(sessions = []) {
  const body = $('devices-body');
  const filter = state.sessionFilter;
  const filtered = sessions.filter(s => filter === 'all' || (filter === 'active' ? s.active : filter === 'idle' ? s.idle : s.revoked));

  if (!filtered.length) {
    body.innerHTML = `<tr><td colspan="6" class="empty-row">No ${filter === 'all' ? '' : filter + ' '}sessions to show.</td></tr>`;
    return;
  }

  body.innerHTML = filtered.map(s => {
    const statusClass = s.revoked ? 'status-revoked' : s.active ? 'status-active' : 'status-idle';
    const statusText = s.revoked ? 'Revoked' : s.active ? 'Active' : 'Idle';
    const action = s.revoked
      ? `<button class="row-action restore" data-restore="${escapeHtml(s.session_id)}">Restore</button>`
      : `<button class="row-action revoke" data-revoke="${escapeHtml(s.session_id)}">Revoke</button>`;
    return `<tr>
      <td><span class="${statusClass}">${statusText}</span><div class="session-id">${escapeHtml(s.session_id.slice(0, 12))}…</div></td>
      <td><strong>${escapeHtml(browserLabel(s.user_agent))}</strong><div class="session-id ua-cell" title="${escapeHtml(s.user_agent)}">${escapeHtml(s.user_agent || 'Unknown')}</div></td>
      <td>${escapeHtml(s.ip)}</td>
      <td>${escapeHtml(formatTime(s.last_activity))}<br><span class="session-id">${Math.round(s.age_seconds)}s ago</span></td>
      <td><div class="path-cell" title="${escapeHtml(s.current_url)}">${escapeHtml(s.current_url)}</div></td>
      <td><div class="row-actions">${action}</div></td>
    </tr>`;
  }).join('');
}

function renderInterfaces(interfaces = []) {
  const select = $('interface-select');
  select.innerHTML = interfaces.map(item => `<option value="${escapeHtml(item.ip)}">${escapeHtml(item.label)}${item.is_loopback ? ' · local only' : ''}</option>`).join('');
  if (state.data?.interface_ip) select.value = state.data.interface_ip;
}

function fillForms(data) {
  const host = data.upstream_base.split('://')[1]?.split(':')[0] || '127.0.0.1';
  $('host-input').value = host;
  $('port-input').value = data.upstream_port;
  $('share-port-input').value = data.share_port;
  $('project-input').value = data.project_root || '';
  $('debounce-input').value = data.reload_debounce_ms || 180;
  $('ignored-input').value = (data.ignored_paths || []).join(', ');
}

function render(data) {
  state.data = data;
  state.csrf = data.csrf || state.csrf;
  const shared = Boolean(data.sharing);
  const counts = data.session_counts || { total: 0, active: 0, idle: 0, revoked: 0 };
  const upstreamOk = Boolean(data.upstream?.ok);
  const watcherRunning = Boolean(data.watcher?.running);

  $('build-version').textContent = data.version || '2.1.0';
  $('about-version').textContent = `Version ${data.version || '2.1.0'}`;

  const integrity = data.integrity || {};
  const integrityStrip = $('integrity-strip');
  const integrityTitle = $('integrity-title');
  const integrityCopy = $('integrity-copy');
  integrityStrip.classList.toggle('ok', integrity.ok === true);
  integrityStrip.classList.toggle('bad', integrity.ok === false);
  integrityTitle.textContent = integrity.ok === true ? 'Release integrity verified' : 'Release integrity warning';
  integrityCopy.textContent = integrity.ok === true ? `${integrity.checked || 0} protected files match the release manifest.` : (integrity.message || 'Protected files differ from the release manifest.');

  const status = $('global-status');
  status.classList.toggle('on', shared);
  status.classList.toggle('warn', !shared && !upstreamOk);
  status.querySelector('span:last-child').textContent = shared ? 'Sharing active' : upstreamOk ? 'Dashboard ready' : 'Upstream unavailable';

  $('start-btn').disabled = shared;
  $('stop-btn').disabled = !shared;
  $('large-start').disabled = shared;
  $('large-stop').disabled = !shared;

  $('stat-preview').textContent = shared ? 'Online' : 'Offline';
  $('stat-preview-sub').textContent = shared ? `LAN :${data.share_port}` : 'Listener not started';
  $('stat-devices').textContent = counts.active;
  $('stat-device-sub').textContent = `${counts.total} total session${counts.total === 1 ? '' : 's'}`;
  $('stat-uptime').textContent = formatUptime(data.share_uptime_seconds);
  $('stat-watcher').textContent = watcherRunning ? 'Running' : data.watcher?.enabled ? 'Ready' : 'Off';
  $('stat-watcher-sub').textContent = data.project_root ? data.project_root : 'No folder selected';

  $('nav-device-count').textContent = counts.active;
  const projectParts = String(data.project_root || '').replace(/\\/g, '/').split('/').filter(Boolean);
  $('sidebar-project').textContent = projectParts.length ? projectParts[projectParts.length - 1] : 'No project';
  $('sidebar-dot').classList.toggle('on', shared);

  $('health-badge').textContent = shared ? 'Live' : upstreamOk ? 'Ready' : 'Attention';
  $('health-upstream').textContent = `${hostFromBase(data.upstream_base)}:${data.upstream_port}`;
  $('health-upstream-state').textContent = upstreamOk ? `HTTP ${data.upstream.http_status}` : 'Offline';
  $('health-interface').textContent = data.interface_ip || '—';
  $('health-interface-state').textContent = data.interface_ip ? 'Detected' : 'None';
  $('health-preview').textContent = shared ? `:${data.share_port}` : `:${data.share_port}`;
  $('health-preview-state').textContent = shared ? 'Listening' : 'Stopped';

  $('health-callout').innerHTML = upstreamOk
    ? `<strong>Upstream looks healthy.</strong><span>${escapeHtml(data.upstream.message || 'The development server answered successfully.')}</span>`
    : `<strong>VS Code Live Server is not reachable.</strong><span>${escapeHtml(data.upstream.message || 'Start Live Server and verify the configured port.')}</span>`;

  $('preview-state').textContent = shared ? 'Active' : 'Inactive';
  $('preview-url').textContent = data.preview_url || 'Start sharing to generate a real URL.';
  $('large-preview-url').textContent = data.preview_url || '—';
  $('large-preview-status').textContent = shared ? 'LAN sharing is active' : 'Sharing is off';
  $('large-preview-copy').textContent = shared ? `Listening on ${data.interface_ip}:${data.share_port}` : 'The listener is not accepting LAN traffic.';
  $('preview-page-status').textContent = shared ? 'Online' : 'Offline';
  $('copy-btn').disabled = !data.preview_url;
  $('open-btn').disabled = !data.preview_url;
  $('large-copy').disabled = !data.preview_url;

  renderLogs(data.logs || []);
  renderSessions(data.sessions || []);
  renderInterfaces(data.interfaces || []);
  fillForms(data);
  $('summary-active').textContent = counts.active;
  $('summary-idle').textContent = counts.idle;
  $('summary-revoked').textContent = counts.revoked;
  $('session-toolbar-label').textContent = `${counts.total} total`;
  if (data.preview_url && data.preview_url !== state.lastQrUrl) { state.lastQrUrl = data.preview_url; loadQr(); }
  if (!data.preview_url) state.lastQrUrl = null;
}

function hostFromBase(base) {
  try { return new URL(base).hostname; } catch (_) { return '127.0.0.1'; }
}

function readSettings() {
  return {
    upstream_host: $('host-input').value.trim(),
    upstream_port: Number($('port-input').value),
    share_port: Number($('share-port-input').value),
    interface_ip: $('interface-select').value,
    project_root: $('project-input').value.trim(),
    watcher_enabled: state.data?.watcher?.enabled ?? true,
    reload_debounce_ms: Number($('debounce-input').value),
    ignored_paths: $('ignored-input').value.split(',').map(v => v.trim()).filter(Boolean)
  };
}

async function refresh() {
  try { render(await api('/api/status')); }
  catch (err) { toast(err.message, true); }
}

function setRealtime(connected) {
  const pill = $('realtime-status');
  if (!pill) return;
  pill.classList.toggle('on', connected);
  pill.querySelector('span:last-child').textContent = connected ? 'Realtime' : 'Reconnecting';
}

function connectDashboardRealtime() {
  if (state.ws && [WebSocket.OPEN, WebSocket.CONNECTING].includes(state.ws.readyState)) return;
  const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${protocol}://${location.host}/api/ws`);
  state.ws = ws;
  ws.addEventListener('open', () => {
    state.wsRetry = 0;
    setRealtime(true);
  });
  ws.addEventListener('message', (event) => {
    if (event.data === 'pong') return;
    try { render(JSON.parse(event.data)); } catch (_) {}
  });
  ws.addEventListener('close', () => {
    setRealtime(false);
    state.ws = null;
    state.wsRetry = Math.min(state.wsRetry + 1, 6);
    setTimeout(connectDashboardRealtime, Math.min(600 * state.wsRetry, 5000));
  });
  ws.addEventListener('error', () => setRealtime(false));
}

async function loadQr() {
  try {
    const data = await api('/api/qr');
    if (!data.ok) return;
    $('qr-image').src = data.image;
    $('qr-image').hidden = false;
    $('qr-placeholder').hidden = true;
  } catch (err) { toast(`QR generation failed: ${err.message}`, true); }
}

async function startSharing() {
  try {
    const data = await api('/api/sharing/start', { method: 'POST', body: JSON.stringify(readSettings()) });
    render(data);
    toast('LAN sharing started. QR pairing is ready.');
  } catch (err) { toast(err.message, true); }
}

async function stopSharing() {
  try {
    const data = await api('/api/sharing/stop', { method: 'POST', body: '{}' });
    render(data);
    $('qr-image').hidden = true;
    $('qr-placeholder').hidden = false;
    toast('LAN sharing stopped. Existing preview tokens are no longer valid.');
  } catch (err) { toast(err.message, true); }
}

async function testUpstream() {
  try {
    const data = await api('/api/upstream/test', { method: 'POST', body: '{}' });
    toast(data.message, !data.ok);
    await refresh();
  } catch (err) { toast(err.message, true); }
}

async function discoverUpstream() {
  try {
    const result = await api('/api/upstream/discover', { method: 'POST', body: '{}' });
    if (!result.candidates.length) {
      toast('No responding local development servers found.', true);
      return;
    }
    const preferred = result.candidates.find(item => item.likely_live_server) || result.candidates[0];
    $('host-input').value = preferred.host;
    $('port-input').value = preferred.port;
    toast(`Found local server on port ${preferred.port}.`);
  } catch (err) { toast(err.message, true); }
}

async function saveSettings() {
  try {
    const data = await api('/api/settings', { method: 'POST', body: JSON.stringify(readSettings()) });
    render(data);
    toast('Settings saved.');
  } catch (err) { toast(err.message, true); }
}

async function revokeSession(id) {
  try {
    await api(`/api/sessions/${encodeURIComponent(id)}/revoke`, { method: 'POST', body: '{}' });
    await refresh();
    toast('Session revoked and active sockets closed.');
  } catch (err) { toast(err.message, true); }
}

async function restoreSession(id) {
  try {
    await api(`/api/sessions/${encodeURIComponent(id)}/restore`, { method: 'POST', body: '{}' });
    await refresh();
    toast('Session restored. The browser can pair again using its existing session cookie.');
  } catch (err) { toast(err.message, true); }
}

async function revokeAll() {
  if (!confirm('Revoke every browser session? Active live connections will be closed.')) return;
  try {
    const result = await api('/api/sessions/revoke-all', { method: 'POST', body: '{}' });
    await refresh();
    toast(`${result.changed} session${result.changed === 1 ? '' : 's'} revoked.`);
  } catch (err) { toast(err.message, true); }
}

async function restoreAll() {
  if (!confirm('Restore every revoked browser session?')) return;
  try {
    const result = await api('/api/sessions/restore-all', { method: 'POST', body: '{}' });
    await refresh();
    toast(`${result.changed} session${result.changed === 1 ? '' : 's'} restored.`);
  } catch (err) { toast(err.message, true); }
}

async function toggleWatcher() {
  const current = state.data?.watcher?.enabled ?? true;
  try {
    const data = await api('/api/settings', { method: 'POST', body: JSON.stringify({ ...readSettings(), watcher_enabled: !current }) });
    render(data);
    toast(`Watcher ${!current ? 'enabled' : 'disabled'}.`);
  } catch (err) { toast(err.message, true); }
}

async function copyUrl(url = state.data?.preview_url) {
  if (!url) return;
  try { await navigator.clipboard.writeText(url); toast('Preview URL copied.'); }
  catch { toast('Clipboard access failed.', true); }
}

function openUrl() {
  if (state.data?.preview_url) window.open(state.data.preview_url, '_blank', 'noopener,noreferrer');
}

function switchView(view) {
  document.querySelectorAll('.view').forEach(el => el.classList.toggle('active', el.id === `view-${view}`));
  document.querySelectorAll('.nav-item').forEach(el => el.classList.toggle('active', el.dataset.view === view));
  $('view-title').textContent = ({ dashboard:'Dashboard', preview:'Live Preview', devices:'Connected Devices', projects:'Projects', settings:'Settings', logs:'Diagnostics', about:'About' })[view] || 'Dashboard';
}

function commandItems() {
  return [
    { label: 'Start LAN sharing', hint: 'Start the authenticated preview listener', action: startSharing, when: () => !state.data?.sharing },
    { label: 'Stop LAN sharing', hint: 'Stop the preview listener', action: stopSharing, when: () => Boolean(state.data?.sharing) },
    { label: 'Test upstream', hint: 'Check the configured VS Code server', action: testUpstream },
    { label: 'Discover local servers', hint: 'Scan common development ports', action: discoverUpstream },
    { label: 'Open Live Preview', hint: 'Switch to preview controls', action: () => switchView('preview') },
    { label: 'Open Connected Devices', hint: 'Manage browser sessions', action: () => switchView('devices') },
    { label: 'Open Projects', hint: 'Configure the file watcher', action: () => switchView('projects') },
    { label: 'Open Settings', hint: 'Adjust network and reload settings', action: () => switchView('settings') },
    { label: 'Open Diagnostics', hint: 'Review logs and runtime checks', action: () => switchView('logs') },
    { label: 'Open About', hint: 'JNR Corporations release information', action: () => switchView('about') },
    { label: 'Refresh status', hint: 'Fetch the latest runtime state', action: refresh },
  ];
}

function renderCommands(query = '') {
  const list = $('command-list');
  const q = query.trim().toLowerCase();
  const items = commandItems().filter(item => item.when ? item.when() : true).filter(item => !q || `${item.label} ${item.hint}`.toLowerCase().includes(q));
  state.commandItems = items;
  state.commandIndex = Math.max(0, Math.min(state.commandIndex, Math.max(items.length - 1, 0)));
  list.innerHTML = items.length ? items.map((item, index) => `<button class="command-item${index === state.commandIndex ? ' active' : ''}" data-command-index="${index}"><span><strong>${escapeHtml(item.label)}</strong><small>${escapeHtml(item.hint)}</small></span><kbd>${index + 1}</kbd></button>`).join('') : '<div class="command-empty">No matching commands.</div>';
}

function closeCommandPalette() { $('command-palette').hidden = true; }
function openCommandPalette() { $('command-palette').hidden = false; $('command-input').value = ''; state.commandIndex = 0; renderCommands(); requestAnimationFrame(() => $('command-input').focus()); }
function runSelectedCommand() { const item = state.commandItems[state.commandIndex]; if (!item) return; closeCommandPalette(); Promise.resolve(item.action()).catch(err => toast(err.message || 'Command failed.', true)); }

function setupCommandPalette() {
  $('command-btn').addEventListener('click', openCommandPalette);
  document.querySelectorAll('[data-command-close]').forEach(el => el.addEventListener('click', closeCommandPalette));
  $('command-input').addEventListener('input', event => { state.commandIndex = 0; renderCommands(event.target.value); });
  $('command-list').addEventListener('click', event => { const target = event.target.closest('[data-command-index]'); if (!target) return; state.commandIndex = Number(target.dataset.commandIndex); runSelectedCommand(); });
  document.addEventListener('keydown', event => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); openCommandPalette(); return; }
    if ($('command-palette').hidden) return;
    if (event.key === 'Escape') closeCommandPalette();
    if (event.key === 'ArrowDown') { event.preventDefault(); state.commandIndex = Math.min(state.commandIndex + 1, Math.max(state.commandItems.length - 1, 0)); renderCommands($('command-input').value); }
    if (event.key === 'ArrowUp') { event.preventDefault(); state.commandIndex = Math.max(state.commandIndex - 1, 0); renderCommands($('command-input').value); }
    if (event.key === 'Enter') { event.preventDefault(); runSelectedCommand(); }
  });
}

function setupFilters() {
  document.querySelectorAll('.filter').forEach(btn => btn.addEventListener('click', () => {
    state.sessionFilter = btn.dataset.filter;
    document.querySelectorAll('.filter').forEach(item => item.classList.toggle('active', item === btn));
    renderSessions(state.data?.sessions || []);
  }));
}

function setup() {
  document.querySelectorAll('.nav-item').forEach(btn => btn.addEventListener('click', () => switchView(btn.dataset.view)));
  document.querySelectorAll('[data-go]').forEach(btn => btn.addEventListener('click', () => switchView(btn.dataset.go)));
  $('refresh-btn').addEventListener('click', refresh);
  $('start-btn').addEventListener('click', startSharing);
  $('stop-btn').addEventListener('click', stopSharing);
  $('large-start').addEventListener('click', startSharing);
  $('large-stop').addEventListener('click', stopSharing);
  $('test-btn').addEventListener('click', testUpstream);
  $('settings-test').addEventListener('click', testUpstream);
  $('discover-upstream').addEventListener('click', discoverUpstream);
  $('copy-btn').addEventListener('click', () => copyUrl());
  $('large-copy').addEventListener('click', () => copyUrl());
  $('open-btn').addEventListener('click', openUrl);
  $('save-settings').addEventListener('click', saveSettings);
  $('save-project').addEventListener('click', saveSettings);
  $('toggle-watcher').addEventListener('click', toggleWatcher);
  $('reload-logs').addEventListener('click', async () => { try { renderLogs((await api('/api/logs')).logs); } catch (err) { toast(err.message, true); } });
  $('revoke-all').addEventListener('click', revokeAll);
  $('restore-all').addEventListener('click', restoreAll);
  $('devices-body').addEventListener('click', (event) => {
    const revoke = event.target.closest('[data-revoke]');
    const restore = event.target.closest('[data-restore]');
    if (revoke) revokeSession(revoke.dataset.revoke);
    if (restore) restoreSession(restore.dataset.restore);
  });
  setupFilters();
  setupCommandPalette();
  setInterval(refresh, 30000);
  connectDashboardRealtime();
}

document.addEventListener('DOMContentLoaded', async () => {
  setup();
  try { render(await api('/api/bootstrap')); }
  catch (err) { toast(err.message, true); }
});
