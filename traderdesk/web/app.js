/* TraderDesk — interface temps réel (vanilla JS, aucune dépendance externe) */
'use strict';

let S = null;
let VIEW = 'overview';
let MODAL_AGENT = null;
let MODAL_TAB = 'fiche';
let DOC_SEL = 'readme';
let DOC_CACHE = {};
let ARTIFACT_SEL = null;
let FORM_READY = false;

const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));
const esc = (v) => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num = (v, d = 2) => (Number(v) || 0).toLocaleString('fr-FR', {minimumFractionDigits: d, maximumFractionDigits: d});
const money = (v) => '$' + num(v, 2);
const hhmm = (ts) => (ts || '').slice(11, 19) || '—';
const short = (s, n = 90) => { const t = String(s || ''); return t.length > n ? t.slice(0, n) + '…' : t; };

async function api(path, method = 'GET', body) {
  const opt = {method, headers: {'Content-Type': 'application/json'}};
  if (body !== undefined) opt.body = JSON.stringify(body);
  const r = await fetch(path, opt);
  return r.json();
}
function toast(msg, kind = '') {
  const el = document.createElement('div');
  el.className = 'toast ' + kind;
  el.textContent = msg;
  $('#toasts').appendChild(el);
  setTimeout(() => el.remove(), 4200);
}
function levelLabel(l) {
  return {info:'INFO', success:'OK', warn:'ALERTE', error:'ERREUR', trade:'TRADE'}[l] || l.toUpperCase();
}

/* ------------------------------------------------------------------- navigation */
const PAGE_META = {
  overview: ['Vue d’ensemble', 'État du desk, des 11 agents et du compte MetaTrader 5'],
  agents: ['Les 11 agents', 'Chaque spécialiste, son rôle, ses commandes, ses fichiers et ses règles'],
  pipeline: ['Pipeline & fichiers', 'Les 4 chaînes du pack et tous les fichiers trader/'],
  orders: ['Ordres & trades', 'Tickets, contrôle du risque, exécution MetaTrader 5 et positions'],
  mt5: ['Connexion MT5', 'Adresse, clé API, reconnexion automatique et exécution des trades'],
  log: ['Journal temps réel', 'Tout ce que font les agents, seconde par seconde'],
  docs: ['Documentation', 'README et SKILL.md d’origine du dépôt trader-skill'],
};
function setView(v) {
  VIEW = v;
  $$('.nav-item').forEach(b => b.classList.toggle('active', b.dataset.view === v));
  $$('.view').forEach(s => s.classList.toggle('active', s.id === 'view-' + v));
  $('#pageTitle').textContent = PAGE_META[v][0];
  $('#pageSub').textContent = PAGE_META[v][1];
  window.scrollTo({top: 0, behavior: 'smooth'});
  if (v === 'docs') loadDoc(DOC_SEL);
}
$$('.nav-item').forEach(b => b.addEventListener('click', () => setView(b.dataset.view)));

/* ------------------------------------------------------------------- état */
async function poll() {
  try {
    S = await api('/api/state');
    render();
  } catch (e) { /* serveur momentanément indisponible */ }
}
setInterval(poll, 1600);
setInterval(() => { $('#clock').textContent = new Date().toLocaleTimeString('fr-FR'); }, 1000);
poll();

function render() {
  if (!S) return;
  renderTop();
  renderKpis();
  renderChart();
  renderOverview();
  renderAgents();
  renderPipeline();
  renderOrders();
  renderMt5();
  renderLog();
  fillForms();
}

function renderTop() {
  const c = S.connection || {}, st = S.settings || {}, tr = st.trading || {}, mt = st.mt5 || {};
  const connected = c.state === 'connected';
  const pill = $('#connPill');
  pill.className = 'conn-pill ' + (connected ? 'ok' : c.state === 'error' ? 'warn' : '');
  pill.innerHTML = '<i></i><span><b>' + esc((mt.mode_label || '—')) + '</b> · ' +
    (connected ? 'connecté' : c.state === 'error' ? 'erreur' : 'hors ligne') +
    (c.server ? ' · ' + esc(short(c.server, 22)) : '') + '</span>';
  $('#navDot').className = 'dot' + (connected ? ' ok' : '');
  $('#sideMode').textContent = connected ? (mt.mode === 'simulation' ? 'Simulation' : mt.mode.toUpperCase()) : '—';
  $('#sideAuto').textContent = tr.auto_execute ? 'ON' : 'OFF';
  $('#sideKill').textContent = tr.kill_switch ? 'ACTIF ⛔' : 'OFF';
  $('#sideKill').style.color = tr.kill_switch ? 'var(--red)' : 'var(--txt)';
  $('#sideKillBtn').textContent = tr.kill_switch ? '✅ Réactiver les ordres' : '⛔ Arrêter les ordres';
  $('#btnCycle').disabled = !!S.pipeline_running;
  $('#btnCycle').textContent = S.pipeline_running ? '⟳ Cycle en cours…' : '▶ Lancer un cycle';
}

function renderKpis() {
  const a = S.account || {}, k = S.counters || {}, tr = S.settings.trading || {};
  const profit = Number(a.profit || 0);
  const kpis = [
    {label:'Agents actifs', value: Object.values(S.agents || {}).filter(x => x.enabled).length + '/11', sub: (S.counters.cycles || 0) + ' cycles exécutés', c:'#8b7cff'},
    {label:'Équité compte', value: money(a.equity || 0), sub: 'solde ' + money(a.balance || 0), c:'#37e2b0', good:true},
    {label:'P/L ouvert', value: (profit >= 0 ? '+' : '') + money(profit), sub: (S.positions || []).length + ' positions', c: profit >= 0 ? '#37e2b0' : '#ff6b7d', good: profit >= 0, bad: profit < 0},
    {label:'Ordres MT5', value: k.executions || 0, sub: (k.blocks || 0) + ' blocages risque', c:'#4aa8ff'},
    {label:'Signaux / alertes', value: (k.signals || 0) + (k.alerts || 0), sub: 'news, 13F, PTR, prix', c:'#ffc35c'},
    {label:'Sécurité', value: tr.kill_switch ? 'GELÉE' : (tr.live_trading ? 'RÉEL' : 'PAPER'), sub: tr.auto_execute ? 'auto-exécution ON' : 'approbation requise', c: tr.kill_switch ? '#ff6b7d' : '#37e2b0', bad: !!tr.kill_switch},
  ];
  $('#kpis').innerHTML = kpis.map(x =>
    `<div class="kpi ${x.good?'good':''} ${x.bad?'bad':''}" style="--c:${x.c}"><div class="kpi-label">${esc(x.label)}</div><div class="kpi-value">${esc(x.value)}</div><div class="kpi-sub">${esc(x.sub)}</div></div>`
  ).join('');
}

function renderChart() {
  const pts = (S.equity_curve || []).map(p => Number(p.v)).slice(-90);
  const el = $('#equityChart');
  if (pts.length < 2) { el.innerHTML = '<div class="empty">Collecte de l’équité en cours…</div>'; }
  else {
    const lo = Math.min(...pts), hi = Math.max(...pts), span = Math.max(hi - lo, 1);
    const W = 600, H = 170, pad = 8;
    const xy = pts.map((v, i) => [pad + i * (W - 2 * pad) / (pts.length - 1), H - pad - (v - lo) / span * (H - 2 * pad)]);
    const line = xy.map(p => p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(' ');
    const area = `M${xy[0][0]},${H} L` + xy.map(p => p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(' L') + ` L${xy[xy.length-1][0]},${H} Z`;
    const up = pts[pts.length - 1] >= pts[0];
    el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
      <defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${up?'#37e2b0':'#ff6b7d'}" stop-opacity=".28"/><stop offset="1" stop-color="${up?'#37e2b0':'#ff6b7d'}" stop-opacity="0"/></linearGradient></defs>
      ${[0,1,2,3].map(i=>`<line x1="0" y1="${20+i*42}" x2="${W}" y2="${20+i*42}" stroke="#1c2940" stroke-width="1"/>`).join('')}
      <path d="${area}" fill="url(#g)"/>
      <polyline points="${line}" fill="none" stroke="${up?'#37e2b0':'#ff6b7d'}" stroke-width="2.2" stroke-linejoin="round"/>
      <circle cx="${xy[xy.length-1][0]}" cy="${xy[xy.length-1][1]}" r="4" fill="${up?'#37e2b0':'#ff6b7d'}"/>
    </svg>`;
  }
  const a = S.account || {}, last = pts[pts.length - 1] || 0, first = pts[0] || last;
  $('#equityLabel').textContent = pts.length > 1 ? ((last - first) >= 0 ? '+' : '') + money(last - first) + ' sur la période' : '';
  $('#accountStrip').innerHTML = [
    ['SOLDE', money(a.balance || 0)], ['ÉQUITÉ', money(a.equity || 0)],
    ['MARGE LIBRE', money(a.free_margin || 0)], ['COMPTE', a.login || '—'],
  ].map(x => `<div class="acc-cell"><span>${x[0]}</span><b>${esc(x[1])}</b></div>`).join('');
}

function feedHtml(events, limit = 14) {
  return (events || []).slice(-limit).reverse().map(e =>
    `<div class="feed-row ${esc(e.level)}"><span class="ts">${esc(hhmm(e.ts))}</span><span class="tag">${esc(levelLabel(e.level))}</span><span class="msg">${esc(e.message)}</span></div>`
  ).join('') || '<div class="empty">Aucun événement</div>';
}
function renderOverview() {
  $('#overviewFeed').innerHTML = feedHtml(S.events, 14);
  const specs = S.agents_spec || [];
  $('#overviewAgents').innerHTML = specs.map(sp => {
    const a = (S.agents || {})[sp.id] || {};
    return `<div class="mini-agent" data-agent="${esc(sp.id)}"><span class="ic" style="color:${esc(sp.color)}">${esc(sp.icon)}</span><span class="nm">${esc(sp.role)}</span><span class="st ${esc(a.status||'idle')}"></span></div>`;
  }).join('');
  $$('#overviewAgents .mini-agent').forEach(el => el.onclick = () => openModal(el.dataset.agent));
  const runs = Object.values(S.agents || {}).reduce((n, a) => n + (a.runs || 0), 0);
  $('#agentRunInfo').textContent = runs + ' exécutions au total';
  const flows = S.pipelines || [];
  $('#overviewPipelines').innerHTML = flows.map(f => flowHtml(f)).join('');
  bindFlowSteps('#overviewPipelines');
  $('#overviewPositions').innerHTML = positionsTable(S.positions);
  $('#posCount').textContent = (S.positions || []).length + ' position(s)';
}
function flowHtml(f) {
  return `<div class="flow-item"><div class="fn">${esc(f.name)}</div><div class="flow-steps">${f.flow.map((id,i) =>
    `${i?'<span class="flow-arrow">→</span>':''}<span class="flow-step" data-agent="${esc(id)}">${esc(id.replace('trader-',''))}</span>`
  ).join('')}</div><div class="fd">${esc(f.detail)}</div></div>`;
}
function bindFlowSteps(sel) {
  $$(sel + ' .flow-step').forEach(el => el.onclick = () => openModal(el.dataset.agent));
}

/* ------------------------------------------------------------------- agents */
function renderAgents() {
  const specs = S.agents_spec || [];
  $('#agentGrid').innerHTML = specs.map(sp => {
    const a = (S.agents || {})[sp.id] || {};
    return `<div class="agent-card" data-agent="${esc(sp.id)}" style="--c:${esc(sp.color)}">
      <div class="agent-top"><div class="agent-icon">${esc(sp.icon)}</div>
        <div><h3>${esc(sp.role)}</h3><div class="agent-cmd">${esc(sp.command)}</div></div>
        <span class="agent-role">${esc(sp.stage)}</span></div>
      <p>${esc(sp.tagline)}</p>
      <div class="agent-summary">${esc(a.summary || 'Pas encore exécuté')}</div>
      <div class="agent-status"><span class="st ${esc(a.status||'idle')}"></span>
        <span>${a.status==='running'?'En cours':a.status==='error'?'Erreur':a.status==='ok'?'Dernier run OK':'En attente'}</span>
        <span class="runs">${a.runs||0} runs · ${a.duration_ms||0} ms</span></div>
    </div>`;
  }).join('');
  $$('#agentGrid .agent-card').forEach(el => el.onclick = () => openModal(el.dataset.agent));
  $('#navAgents').textContent = Object.values(S.agents || {}).filter(a => a.enabled).length;
}

function openModal(id) {
  MODAL_AGENT = id; MODAL_TAB = 'fiche';
  $$('#modalTabs button').forEach(b => b.classList.toggle('active', b.dataset.tab === 'fiche'));
  const sp = (S.agents_spec || []).find(a => a.id === id);
  if (!sp) return;
  $('#modalCommand').textContent = sp.command;
  $('#modalTitle').textContent = sp.role;
  $('#modalRole').textContent = sp.stage + ' · ' + sp.schedule;
  $('#modal').classList.add('open');
  renderModal();
}
function closeModal() { $('#modal').classList.remove('open'); MODAL_AGENT = null; }
$('#modalClose').onclick = closeModal;
$('#modal').addEventListener('click', e => { if (e.target.id === 'modal') closeModal(); });
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });
$$('#modalTabs button').forEach(b => b.onclick = () => {
  MODAL_TAB = b.dataset.tab;
  $$('#modalTabs button').forEach(x => x.classList.toggle('active', x === b));
  renderModal();
});
$('#modalRun').onclick = async () => {
  if (!MODAL_AGENT) return;
  const r = await api('/api/agents/' + MODAL_AGENT + '/run', 'POST', {});
  toast(r.ok ? 'Agent lancé : ' + MODAL_AGENT : r.error, r.ok ? 'ok' : 'err');
  setTimeout(poll, 600);
};
$('#modalToggle').onclick = async () => {
  if (!MODAL_AGENT) return;
  await api('/api/agents/' + MODAL_AGENT + '/toggle', 'POST', {});
  setTimeout(poll, 400);
};

async function renderModal() {
  if (!MODAL_AGENT || !S) return;
  const sp = (S.agents_spec || []).find(a => a.id === MODAL_AGENT) || {};
  const a = (S.agents || {})[MODAL_AGENT] || {};
  const body = $('#modalBody');
  $('#modalToggle').textContent = a.enabled === false ? 'Activer l’agent' : 'Désactiver l’agent';
  if (MODAL_TAB === 'fiche') {
    const list = (arr, cls = 'spec-list') => `<div class="${cls}">${(arr||[]).map(x => `<div>${esc(x)}</div>`).join('') || '<div>—</div>'}</div>`;
    body.innerHTML = `
      <div class="spec-block"><h4>Rôle · ${esc(sp.command)}</h4><p>${esc(sp.detail)}</p></div>
      <div class="spec-block"><h4>Déclencheurs (phrases utilisateur)</h4><div class="spec-chips">${(sp.triggers||[]).map(x=>`<span>${esc(x)}</span>`).join('')}</div></div>
      <div class="spec-block"><h4>Commandes de l'outil Python</h4>${list(sp.commands)}</div>
      <div class="grid-2">
        <div class="spec-block"><h4>Lit</h4>${list(sp.reads)}</div>
        <div class="spec-block"><h4>Écrit</h4>${list(sp.writes)}</div>
      </div>
      <div class="spec-block"><h4>Règles appliquées</h4>${list(sp.rules)}</div>
      <div class="spec-block"><h4>Exemple concret</h4><p>${esc(sp.example)}</p></div>
      <div class="spec-block"><h4>Ne fait jamais</h4>${list(sp.never)}</div>
      <div class="spec-block"><h4>État dans TraderDesk</h4><div class="spec-kv">
        <b>Statut</b><span>${esc(a.status||'idle')}</span><b>Exécutions</b><span>${a.runs||0}</span>
        <b>Dernier run</b><span>${esc(a.last_run||'—')}</span><b>Durée</b><span>${a.duration_ms||0} ms</span>
        <b>Résumé</b><span>${esc(a.summary||'—')}</span><b>Activé</b><span>${a.enabled===false?'Non':'Oui'}</span>
      </div></div>`;
  } else if (MODAL_TAB === 'sortie') {
    body.innerHTML = `<div class="spec-block"><h4>Dernière sortie de ${esc(sp.command)}</h4></div><pre class="code-block tall">${esc(a.output || 'Aucune sortie pour le moment — lancez l’agent.')}</pre>`;
  } else if (MODAL_TAB === 'journal') {
    body.innerHTML = `<div class="spec-block"><h4>Journal de ${esc(sp.command)}</h4></div><div class="feed">${feedHtml(a.logs || [], 60)}</div>`;
  } else {
    body.innerHTML = '<div class="empty">Chargement du SKILL.md…</div>';
    if (!DOC_CACHE[MODAL_AGENT]) {
      const r = await fetch('/api/docs/' + MODAL_AGENT);
      DOC_CACHE[MODAL_AGENT] = await r.text();
    }
    body.innerHTML = `<pre class="code-block tall">${esc(DOC_CACHE[MODAL_AGENT])}</pre>`;
  }
}

/* ------------------------------------------------------------------- pipeline / artefacts */
function renderPipeline() {
  $('#pipelineFlows').innerHTML = (S.pipelines || []).map(f =>
    `<div class="pipeline-card"><h3>${esc(f.name)}</h3><div class="pd">${esc(f.detail)}</div>
     <div class="flow-steps">${f.flow.map((id,i)=>`${i?'<span class="flow-arrow">→</span>':''}<span class="flow-step" data-agent="${esc(id)}">${esc(id.replace('trader-',''))}</span>`).join('')}</div></div>`
  ).join('');
  bindFlowSteps('#pipelineFlows');
  $('#artifactList').innerHTML = (S.artifact_list || []).map(a =>
    `<div class="artifact-row ${ARTIFACT_SEL===a.file?'sel':''}" data-file="${esc(a.file)}">${esc(a.file)}
      <small>${esc(a.what)} · produit par ${esc(a.by)}</small></div>`
  ).join('');
  $$('#artifactList .artifact-row').forEach(el => el.onclick = () => selectArtifact(el.dataset.file));
}
async function selectArtifact(file) {
  ARTIFACT_SEL = file;
  $$('#artifactList .artifact-row').forEach(el => el.classList.toggle('sel', el.dataset.file === file));
  $('#artifactName').textContent = file;
  $('#artifactContent').textContent = 'Chargement…';
  const r = await fetch('/api/artifact?name=' + encodeURIComponent(file));
  const j = await r.json();
  $('#artifactContent').textContent = j.error ? ('— ' + j.error) : (typeof j === 'string' ? j : JSON.stringify(j, null, 2));
}

/* ------------------------------------------------------------------- ordres */
function positionsTable(rows) {
  if (!rows || !rows.length) return '<div class="empty">Aucune position ouverte</div>';
  return `<table><thead><tr><th>Ticket</th><th>Symbole</th><th>Sens</th><th class="mono">Volume</th><th class="mono">Ouverture</th><th class="mono">Actuel</th><th class="mono">P/L</th><th class="mono">SL / TP</th></tr></thead><tbody>` +
    rows.map(p => `<tr><td class="mono">${esc(p.ticket)}</td><td><b>${esc(p.symbol)}</b></td><td><span class="pill ${p.side==='buy'?'green':'red'}">${esc((p.side||'').toUpperCase())}</span></td>
      <td class="mono">${num(p.volume,2)}</td><td class="mono">${num(p.price_open,4)}</td><td class="mono">${num(p.price_current,4)}</td>
      <td class="mono ${Number(p.profit)>=0?'pos':'neg'}">${Number(p.profit)>=0?'+':''}${money(p.profit)}</td>
      <td class="mono">${p.sl?num(p.sl,2):'—'} / ${p.tp?num(p.tp,2):'—'}</td></tr>`).join('') + '</tbody></table>';
}
function renderOrders() {
  const tr = S.settings.trading || {}, c = S.connection || {};
  const gates = [
    ['Kill switch', !tr.kill_switch, tr.kill_switch ? 'GELÉ' : 'Libre'],
    ['Auto-exécution', !!tr.auto_execute, tr.auto_execute ? 'Activée' : 'Désactivée'],
    ['Approbation manuelle', !!tr.require_approval, tr.require_approval ? 'Par ordre' : 'Non requise'],
    ['Trading réel', !!tr.live_trading, tr.live_trading ? 'Autorisé' : 'Paper uniquement'],
    ['Connexion MT5', c.state === 'connected', c.state === 'connected' ? 'Connecté' : 'Hors ligne'],
    ['Ordres / jour', true, (S.trades||[]).length + ' / ' + (tr.max_daily_orders||10)],
    ['Volume max', true, (tr.max_lot||0) + ' lots'],
    ['Cycle', true, (tr.cycle_seconds||90) + ' s'],
  ];
  $('#execGates').innerHTML = gates.map(g => `<div class="gate ${g[1]?'on':'off'}"><div class="gl">${esc(g[0]).toUpperCase()}</div><div class="gv">${esc(g[2])}</div></div>`).join('');

  const tickets = ((S.artifacts || {})['trader/state/tickets.json'] || {}).tickets || [];
  $('#ticketCount').textContent = tickets.length + ' ticket(s) · ' + tickets.filter(t=>t.ready).length + ' READY';
  $('#ticketTable').innerHTML = tickets.length ? `<table><thead><tr><th>#</th><th>Symbole</th><th>Sens</th><th class="mono">Montant</th><th>Type</th><th>Statut</th><th>Fingerprint</th><th>Action</th></tr></thead><tbody>` +
    tickets.map(t => {
      const o = t.tool_input || {};
      return `<tr><td class="mono">${esc(t.index)}</td><td><b>${esc(o.symbol||'—')}</b></td><td><span class="pill ${o.side==='buy'?'green':'red'}">${esc(o.side||'')}</span></td>
        <td class="mono">${o.notional?money(o.notional):(o.qty||'—')}</td><td class="mono">${esc(o.type||'market')} / ${esc(o.time_in_force||'day')}</td>
        <td><span class="pill ${t.ready?'green':'amber'}">${esc(short(t.status,52))}</span></td><td class="mono">${esc(t.fingerprint||'—')}</td>
        <td>${t.ready?`<button class="btn btn-primary btn-approve" data-fp="${esc(t.fingerprint)}" style="padding:5px 9px">✓ Exécuter</button> <button class="btn btn-ghost btn-reject" data-fp="${esc(t.fingerprint)}" style="padding:5px 9px">✕ Refuser</button>`:'—'}</td></tr>`;
    }).join('') + '</tbody></table>' : '<div class="empty">Aucun ticket. Lancez un cycle (budget → risk → broker).</div>';
  $$('#ticketTable .btn-approve').forEach(b => b.onclick = async () => {
    const r = await api('/api/orders/' + b.dataset.fp + '/approve', 'POST', {});
    toast(r.ok ? 'Ordre envoyé à MT5' : r.error, r.ok ? 'ok' : 'err'); setTimeout(poll, 900);
  });
  $$('#ticketTable .btn-reject').forEach(b => b.onclick = async () => {
    await api('/api/orders/' + b.dataset.fp + '/reject', 'POST', {}); toast('Ordre refusé'); setTimeout(poll, 600);
  });

  const trades = (S.trades || []).slice().reverse();
  $('#tradeCount').textContent = trades.length + ' ordre(s)';
  $('#tradeTable').innerHTML = trades.length ? `<table><thead><tr><th>Heure</th><th>Ticket MT5</th><th>Symbole</th><th>Sens</th><th class="mono">Volume</th><th class="mono">Prix</th><th class="mono">Montant</th><th class="mono">SL/TP</th><th>Mode</th><th>Statut</th></tr></thead><tbody>` +
    trades.map(t => `<tr><td class="mono">${esc(hhmm(t.time))}</td><td class="mono">${esc(t.ticket||'—')}</td><td><b>${esc(t.mt5_symbol||t.symbol||'—')}</b></td>
      <td><span class="pill ${t.side==='buy'?'green':'red'}">${esc((t.side||'').toUpperCase())}</span></td><td class="mono">${num(t.volume,2)}</td>
      <td class="mono">${num(t.price,4)}</td><td class="mono">${money(t.notional||0)}</td><td class="mono">${t.sl?num(t.sl,2):'—'}/${t.tp?num(t.tp,2):'—'}</td>
      <td>${esc(t.mode||'—')}</td><td><span class="pill ${t.status==='filled'?'green':'red'}">${esc(t.status||'')}</span></td></tr>`).join('') + '</tbody></table>'
    : '<div class="empty">Aucun ordre envoyé. En mode simulation, le premier cycle place automatiquement les ordres approuvés par le risque.</div>';
  $('#positionsTable').innerHTML = positionsTable(S.positions);
}

/* ------------------------------------------------------------------- MT5 */
const TOGGLES = [
  {section:'mt5', key:'auto_connect', label:'Reconnexion automatique'},
  {section:'trading', key:'auto_execute', label:'Exécution automatique des trades'},
  {section:'trading', key:'require_approval', label:'Approuver chaque ordre'},
  {section:'trading', key:'kill_switch', label:'⛔ Kill switch (gel total)', danger:true},
  {section:'trading', key:'live_trading', label:'Autoriser le trading RÉEL', danger:true},
  {section:'trading', key:'paper', label:'Compte paper / démo'},
  {section:'trading', key:'live_data', label:'Données SEC / news en direct'},
];
function renderMt5() {
  const c = S.connection || {}, mt = S.settings.mt5 || {};
  $('#connDetails').innerHTML = [
    ['État', c.state === 'connected' ? '✅ Connecté' : c.state === 'error' ? '⚠ Erreur' : '○ Hors ligne'],
    ['Mode', mt.mode_label || '—'],
    ['Adresse', c.address || mt.address || '—'],
    ['Serveur', c.server || '—'],
    ['Compte', c.account || '—'],
    ['Dernier check', c.last_check || '—'],
    ['Latence', (c.latency_ms || 0) + ' ms'],
    ['Tentatives', c.attempts || 0],
    ['Dernière erreur', c.last_error || 'aucune'],
    ['Message', c.message || '—'],
  ].map(r => `<div class="conn-row"><span>${esc(r[0])}</span><b>${esc(r[1])}</b></div>`).join('');
  $('#toggles').innerHTML = TOGGLES.map(t => {
    const on = !!(S.settings[t.section] || {})[t.key];
    return `<label class="toggle ${t.danger?'danger':''}"><span>${esc(t.label)}</span><input type="checkbox" data-section="${t.section}" data-key="${t.key}" ${on?'checked':''}><span class="sw"></span></label>`;
  }).join('');
  $$('#toggles input').forEach(inp => inp.onchange = async () => {
    await api('/api/toggle', 'POST', {section: inp.dataset.section, key: inp.dataset.key});
    toast('Réglage mis à jour'); setTimeout(poll, 500);
  });
  $('#cfgMode').value = mt.mode || 'simulation';
  $('#restFields').classList.toggle('hidden', (mt.mode || 'simulation') !== 'rest');
  $('#localFields').classList.toggle('hidden', (mt.mode || 'simulation') !== 'local');
  if (!$('#bridgeSteps').dataset.done) {
    $('#bridgeSteps').dataset.done = '1';
    $('#bridgeSteps').innerHTML = `
      <div class="step"><div class="sn">01 · WINDOWS</div><h4>Lancer la passerelle MT5</h4>
        <p>Sur le PC où le terminal MetaTrader 5 est installé, démarrez le pont REST fourni (le package MetaTrader5 est détecté automatiquement).</p>
        <pre>TraderDesk.exe --bridge --api-key MA_CLE --port 8765
# ou : python run.py --bridge --api-key MA_CLE</pre></div>
      <div class="step"><div class="sn">02 · DASHBOARD</div><h4>Renseigner adresse + clé API</h4>
        <p>Dans l'onglet Connexion MT5 : mode « Passerelle REST », adresse du pont, puis la même clé API. La connexion se fait automatiquement et se relance toute seule si elle tombe.</p>
        <pre>http://127.0.0.1:8765
X-API-Key: MA_CLE</pre></div>
      <div class="step"><div class="sn">03 · TRADING</div><h4>Activer l'exécution</h4>
        <p>Les 11 agents produisent les ordres, trader-risk les valide, trader-broker crée les tickets, puis le moteur convertit chaque montant en volume MT5 et envoie l'ordre avec SL/TP.</p>
        <pre>volume = notional / prix
copycat → budget → risk → broker → MT5</pre></div>`;
  }
}

function fillForms() {
  if (!S) return;
  const mt = S.settings.mt5 || {}, tr = S.settings.trading || {}, rk = S.settings.risk || {};
  const f = $('#mt5Form');
  const setVal = (el, val) => { if (el && document.activeElement !== el && el.value !== String(val)) el.value = val; };
  ['address','account','server','terminal_path','timeout','magic','deviation','symbol_prefix','symbol_suffix'].forEach(k => setVal(f.elements[k], mt[k] ?? ''));
  setVal(f.elements.mode, mt.mode || 'simulation');
  const mapEl = f.elements.symbol_map;
  const mapVal = JSON.stringify(mt.symbol_map || {}, null, 2);
  if (document.activeElement !== mapEl && mapEl.value !== mapVal) mapEl.value = mapVal;
  const tf = $('#tradingForm');
  ['budget','cycle_seconds','max_orders_per_cycle','max_daily_orders','max_lot','default_sl_pct','default_tp_pct'].forEach(k => setVal(tf.elements[k], tr[k] ?? ''));
  setVal(tf.elements.rebalance_band_pct, rk.rebalance_band_pct ?? 5);
  setVal(tf.elements.max_position_pct, rk.max_position_pct ?? 25);
  FORM_READY = true;
}
$('#cfgMode').addEventListener('change', e => {
  $('#restFields').classList.toggle('hidden', e.target.value !== 'rest');
  $('#localFields').classList.toggle('hidden', e.target.value !== 'local');
});
$('#mt5Form').addEventListener('submit', async e => {
  e.preventDefault();
  const f = e.target;
  let map = {};
  try { map = JSON.parse(f.elements.symbol_map.value || '{}'); }
  catch (err) { return toast('Correspondance des symboles : JSON invalide', 'err'); }
  const payload = {mt5: {
    mode: f.elements.mode.value, address: f.elements.address.value,
    account: f.elements.account.value, server: f.elements.server.value,
    terminal_path: f.elements.terminal_path.value,
    timeout: Number(f.elements.timeout.value || 8),
    magic: Number(f.elements.magic.value || 240611),
    deviation: Number(f.elements.deviation.value || 20),
    symbol_prefix: f.elements.symbol_prefix.value,
    symbol_suffix: f.elements.symbol_suffix.value,
    symbol_map: map,
  }};
  for (const k of ['api_key','password']) {
    if (f.elements[k].value.trim()) payload.mt5[k] = f.elements[k].value.trim();
  }
  const r = await api('/api/settings', 'POST', payload);
  toast(r.ok ? 'Configuration enregistrée — reconnexion automatique en cours' : r.error, r.ok ? 'ok' : 'err');
  f.elements.api_key.value = ''; f.elements.password.value = '';
  setTimeout(poll, 800);
});
$('#btnTest').onclick = async () => {
  const f = $('#mt5Form');
  const cfg = {mode: f.elements.mode.value, address: f.elements.address.value,
    account: f.elements.account.value, server: f.elements.server.value,
    terminal_path: f.elements.terminal_path.value, timeout: Number(f.elements.timeout.value||8)};
  if (f.elements.api_key.value.trim()) cfg.api_key = f.elements.api_key.value.trim();
  if (f.elements.password.value.trim()) cfg.password = f.elements.password.value.trim();
  toast('Test de connexion en cours…');
  const r = await api('/api/mt5/test', 'POST', {mt5: cfg});
  toast(r.ok ? `✅ ${r.message} — ${r.server||''} (${r.latency_ms} ms)` : '❌ ' + (r.error||'échec'), r.ok ? 'ok' : 'err');
  setTimeout(poll, 500);
};
$('#tradingForm').addEventListener('submit', async e => {
  e.preventDefault();
  const f = e.target, n = k => Number(f.elements[k].value);
  const r = await api('/api/settings', 'POST', {
    trading: {budget:n('budget'), cycle_seconds:n('cycle_seconds'),
      max_orders_per_cycle:n('max_orders_per_cycle'), max_daily_orders:n('max_daily_orders'),
      max_lot:n('max_lot'), default_sl_pct:n('default_sl_pct'), default_tp_pct:n('default_tp_pct')},
    risk: {rebalance_band_pct:n('rebalance_band_pct'), max_position_pct:n('max_position_pct')},
  });
  toast(r.ok ? 'Paramètres de trading enregistrés' : r.error, r.ok ? 'ok' : 'err');
  setTimeout(poll, 500);
});

/* ------------------------------------------------------------------- journal */
function renderLog() {
  const q = ($('#logSearch').value || '').toLowerCase();
  const lvl = $('#logLevel').value;
  const rows = (S.events || []).slice().reverse().filter(e =>
    (!lvl || e.level === lvl) && (!q || (e.message + e.agent + e.detail).toLowerCase().includes(q)));
  $('#fullLog').innerHTML = rows.slice(0, 400).map(e =>
    `<div class="log-row ${esc(e.level)}"><span class="lt">${esc(hhmm(e.ts))}</span><span class="tag pill ${e.level==='error'?'red':e.level==='warn'?'amber':e.level==='trade'?'blue':''}">${esc(levelLabel(e.level))}</span><span class="la">${esc(e.agent)}</span><span class="lm">${esc(e.message)}</span></div>`
  ).join('') || '<div class="empty">Aucun événement pour ce filtre</div>';
}
$('#logSearch').addEventListener('input', () => S && renderLog());
$('#logLevel').addEventListener('change', () => S && renderLog());
$('#btnExport').onclick = () => window.open('/api/export/events.csv', '_blank');

/* ------------------------------------------------------------------- docs */
const DOC_LIST = [{id:'readme', name:'README.md', sub:'Vue d’ensemble du pack trader-skill'}];
function renderDocsList() {
  const specs = S.agents_spec || [];
  const list = DOC_LIST.concat(specs.map(a => ({id:a.id, name:a.id + '/SKILL.md', sub:a.role})));
  $('#docList').innerHTML = list.map(d =>
    `<div class="doc-row ${DOC_SEL===d.id?'sel':''}" data-doc="${esc(d.id)}">${esc(d.name)}<small>${esc(d.sub)}</small></div>`).join('');
  $$('#docList .doc-row').forEach(el => el.onclick = () => loadDoc(el.dataset.doc));
}
async function loadDoc(id) {
  DOC_SEL = id;
  $('#docTitle').textContent = id === 'readme' ? 'README.md' : id + '/SKILL.md';
  $('#docContent').textContent = 'Chargement…';
  if (!DOC_CACHE[id]) {
    const r = await fetch('/api/docs/' + id);
    DOC_CACHE[id] = await r.text();
  }
  $('#docContent').textContent = DOC_CACHE[id];
  renderDocsList();
}

/* ------------------------------------------------------------------- actions */
$('#btnCycle').onclick = async () => {
  const r = await api('/api/pipeline/run', 'POST', {});
  toast(r.ok ? r.message : r.error, r.ok ? 'ok' : 'err');
  setTimeout(poll, 900);
};
$('#btnConnect').onclick = async () => {
  toast('Reconnexion MT5 en cours…');
  await api('/api/mt5/connect', 'POST', {});
  setTimeout(poll, 1200);
};
$('#sideKillBtn').onclick = async () => {
  const r = await api('/api/kill', 'POST', {});
  toast(r.kill_switch ? '⛔ Exécution gelée' : '✅ Exécution réactivée', r.kill_switch ? 'err' : 'ok');
  setTimeout(poll, 500);
};
