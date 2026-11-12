/* ALKAN Bid Engine — unified app (Inicio, Nuevo estimado, Entregas, Administrador). */
(() => {
'use strict';
const $ = id => document.getElementById(id);
const view = $('view');
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const money = v => v ? '$' + Number(String(v).replace(/,/g, '')).toLocaleString('en-US', {minimumFractionDigits: 2}) : '—';
const when = iso => iso ? new Date(iso).toLocaleString('es-MX', {day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit'}) : '—';
const size = b => b > 1048576 ? (b / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(b / 1024)) + ' KB';
let token = '', timer = null, status = null, uploads = [];

/* ───────── API ───────── */
function actor() {
  const name = $('actor').value.trim();
  if (!name) { $('actor').focus(); throw Error('Escribe tu nombre en «Responsable de esta sesión» (abajo a la izquierda).'); }
  localStorage.setItem('alkan.actor', name);
  return name;
}
async function api(path, data) {
  const opt = data === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json', 'X-ALKAN-Token': token},
    body: JSON.stringify({actor: actor(), ...data})};
  const r = await fetch(path, opt);
  const out = await r.json().catch(() => ({error: 'Respuesta inválida del motor'}));
  if (!r.ok) throw Error(out.error || 'Error ' + r.status);
  return out;
}
function toast(msg, kind = '') {
  $('toast').innerHTML = `<div class="notice ${kind}">${esc(msg)}</div>`;
  clearTimeout(toast.t); toast.t = setTimeout(() => { $('toast').innerHTML = ''; }, kind === 'error' ? 9000 : 4000);
}
const safe = fn => async (...a) => { try { return await fn(...a); } catch (e) { toast(e.message, 'error'); } };

/* ───────── helpers ───────── */
const STATUS = {lista: ['ok', 'Lista para revisión'], autorizada: ['ok', 'Autorizada'], 'no-go': ['warn', 'NO-GO'], incompleta: ['warn', 'Incompleta'],
  error: ['bad', 'Error'], cancelada: ['bad', 'Cancelada'], interrumpida: ['bad', 'Interrumpida'], 'en cola': ['live', 'En cola'],
  indexando: ['live', 'Leyendo documentos'], estimando: ['live', 'Estimando']};
const pill = s => { const [c, t] = STATUS[s] || ['', s]; return `<span class="pill ${c}">${esc(t)}</span>`; };
const isLive = s => ['en cola', 'indexando', 'estimando'].includes(s);
function field(label, id, value, {type = 'text', hint = '', cls = '', attrs = ''} = {}) {
  return `<label class="f ${cls}">${esc(label)}${hint ? ` <small>${esc(hint)}</small>` : ''}<input type="${type}" id="${id}" value="${esc(value)}" ${attrs}></label>`;
}
const area = (label, id, value, hint = '', cls = 'wide') => `<label class="f ${cls}">${esc(label)}${hint ? ` <small>${esc(hint)}</small>` : ''}<textarea id="${id}">${esc(value)}</textarea></label>`;
const check = (label, id, on, hint = '') => `<label class="c"><input type="checkbox" id="${id}" ${on ? 'checked' : ''}><span>${esc(label)}${hint ? `<br><small class="muted">${esc(hint)}</small>` : ''}</span></label>`;
const select = (label, id, options, value, hint = '') => `<label class="f">${esc(label)}${hint ? ` <small>${esc(hint)}</small>` : ''}<select id="${id}">${options.map(([v, t]) => `<option value="${esc(v)}" ${v === value ? 'selected' : ''}>${esc(t)}</option>`).join('')}</select></label>`;
function md(text) {            // report markdown → HTML (headings, bullets, bold)
  let html = '', list = false;
  const inline = s => esc(s).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/_\((.+?)\)_/g, '<span class="muted">($1)</span>');
  for (const line of text.split('\n')) {
    if (line.startsWith('- ')) { if (!list) { html += '<ul>'; list = true; } html += `<li>${inline(line.slice(2))}</li>`; continue; }
    if (list) { html += '</ul>'; list = false; }
    if (line.startsWith('## ')) html += `<h2>${inline(line.slice(3))}</h2>`;
    else if (line.startsWith('# ')) continue;
    else if (line.trim()) html += `<p>${inline(line.replace(/^> /, ''))}</p>`;
  }
  return html + (list ? '</ul>' : '');
}
function runsTable(runs) {
  if (!runs.length) return '<p class="muted">Todavía no hay entregas. Empieza con «Nuevo estimado».</p>';
  return `<table><thead><tr><th>Proyecto</th><th>Contratista</th><th>Estado</th><th class="num">Precio de venta</th><th>Inicio</th><th>Responsable</th></tr></thead><tbody>${
    runs.map(r => `<tr class="click" data-run="${esc(r.id)}"><td><b>${esc(r.key)}</b></td><td>${esc(r.contractor)}${r.generic ? ' <span class="pill">sin marca</span>' : ''}</td><td>${pill(r.status)}</td><td class="num">${money(r.price)}</td><td>${when(r.started_at)}</td><td>${esc(r.actor)}</td></tr>`).join('')}</tbody></table>`;
}

/* ───────── Inicio ───────── */
async function inicio() {
  const [st, runs] = await Promise.all([api('/api/app/status'), api('/api/app/runs')]);
  status = st;
  const missing = st.checks.filter(c => !c.ok && !c.optional);
  const live = runs.runs.find(r => isLive(r.status));
  view.innerHTML = `<h1>Inicio</h1><p class="sub">Sube los documentos del bid, elige para quién y recibe el paquete de 3 documentos con su reporte.</p>
  ${live ? `<div class="card"><div class="row"><div class="grow"><b>${esc(live.key)}</b> ${pill(live.status)}<div class="muted">${esc(live.stage)}</div></div><a class="btn primary" href="#corrida/${esc(live.id)}">Ver avance</a></div></div>` : ''}
  <div class="card"><div class="row"><div class="grow"><h2>Nuevo estimado</h2><div class="muted">Planos, specs y addenda (PDF o ZIP) → 01 Cost Analysis, 02 Material List, 03 Proposal y reporte.</div></div>
    <a class="btn primary" href="#nuevo">Empezar</a></div>
    ${st.ready ? '' : '<div class="notice error" style="margin:14px 0 0">Antes de estimar falta conectar lo marcado abajo.</div>'}</div>
  <div class="card"><h2>${missing.length ? `Falta conectar (${missing.length})` : 'Todo conectado'}</h2>
    ${st.checks.map(c => `<div class="check"><span class="ic ${c.ok ? '' : c.optional ? 'opt' : 'no'}">${c.ok ? '✓' : c.optional ? '·' : '!'}</span><div class="grow"><b>${esc(c.label)}</b><div class="d">${esc(c.detail)}</div></div>${c.ok ? '' : `<a class="btn" href="#admin/${esc(c.go)}">${c.optional ? 'Configurar' : 'Resolver'}</a>`}</div>`).join('')}
    <p class="muted" style="margin:12px 0 0">Modelo del motor: <b>${esc(st.model)}</b> · <a href="#admin/motor">cambiar</a></p></div>
  <div class="card"><div class="row"><h2 class="grow">Últimas entregas</h2><a href="#entregas">Ver todas</a></div>${runsTable(runs.runs.slice(0, 5))}</div>`;
}

/* ───────── Nuevo estimado ───────── */
async function nuevo() {
  const [st, profs] = await Promise.all([api('/api/app/status'), api('/api/app/profiles')]);
  status = st; uploads = [];
  const def = st.default_profile || (profs.profiles.find(p => !p.generic) || profs.profiles[0] || {}).name || '';
  view.innerHTML = `<h1>Nuevo estimado</h1><p class="sub">Tres datos y el motor hace el resto. La propuesta siempre sale como borrador hasta que una persona la autoriza.</p>
  ${st.ready ? '' : `<div class="notice error">Falta la clave de la API o un perfil de contratista. <a href="#admin/conexiones">Ir a Administrador</a></div>`}
  ${st.active_run ? `<div class="notice">Hay una corrida en curso (<a href="#corrida/${esc(st.active_run)}">ver avance</a>). El motor corre una a la vez.</div>` : ''}
  <div class="card"><h2>1 · Documentos del bid</h2>
    <div class="drop" id="drop"><input type="file" id="files" multiple accept=".pdf,.zip"><b>Arrastra aquí los PDF o un ZIP</b><br><span class="muted">Planos, specs, addenda, bid form e invitación. Sin límite práctico: se suben por partes.</span></div>
    <div class="chips" id="chips"></div>
    <details style="margin-top:12px"><summary class="muted">O usar una carpeta o ZIP que ya está en esta PC</summary>
      ${field('Ruta local', 'path', '', {hint: 'p. ej. C:\\Users\\…\\Gonyea Playfield.zip — útil para juegos muy grandes', attrs: 'placeholder="C:\\ruta\\al\\proyecto"'})}</details></div>
  <div class="card"><h2>2 · Para quién</h2><div class="grid">
    ${select('Contratista', 'profile', profs.profiles.map(p => [p.name, p.label + (p.generic ? ' — sin logo ni datos' : '')]), def, '')}
    <div class="muted" id="profInfo" style="align-self:end"></div>
    ${area('Oficio y alcance a estimar', 'trade', '', 'déjalo vacío para usar el del perfil')}</div></div>
  <div class="card"><h2>3 · Proyecto</h2><div class="grid">
    ${field('Clave corta', 'key', '', {hint: 'nombra los archivos: GONYEA, MERIDIAN…', attrs: 'maxlength="24" placeholder="GONYEA" style="text-transform:uppercase"'})}
    ${area('Instrucciones para esta corrida', 'notes', '', 'opcional — p. ej. «incluir bancas y mesas de picnic»')}</div></div>
  <div class="row"><button class="primary big" id="go" ${st.active_run ? 'disabled' : ''}>Estimar</button><span class="muted" id="goInfo">Modelo: ${esc(st.model)}</span></div>
  <div class="bar hidden" id="upBar" style="margin-top:14px"><i></i></div>`;
  const info = () => {
    const p = profs.profiles.find(x => x.name === $('profile').value) || {};
    $('profInfo').innerHTML = p.generic ? 'Preestimado sin marca: los campos del contratista quedan en blanco. Cuando caiga un contratista, se le aplica desde la entrega sin repetir el takeoff.'
      : `Markups: contingencia ${esc(p.markups?.contingency_pct)}% · overhead ${esc(p.markups?.overhead_pct)}% · utilidad ${esc(p.markups?.profit_pct)}%`;
    $('trade').placeholder = p.trade || 'Obligatorio con este perfil. Ej.: Metal fabrication: handrails, guardrails, bollards, chain-link fence and gates. Base bid only.';
  };
  $('profile').onchange = info; info();
  const chips = () => { $('chips').innerHTML = uploads.map((f, i) => `<span class="chip">${esc(f.name)} · ${size(f.size)}<b data-rm="${i}" title="Quitar">×</b></span>`).join(''); };
  const add = list => { for (const f of list) { if (/\.(pdf|zip)$/i.test(f.name) && !uploads.some(u => u.name === f.name)) uploads.push(f); else if (!/\.(pdf|zip)$/i.test(f.name)) toast(`${f.name}: solo PDF o ZIP`, 'error'); } chips(); };
  $('files').onchange = e => { add(e.target.files); e.target.value = ''; };
  const drop = $('drop');
  drop.ondragover = e => { e.preventDefault(); drop.classList.add('over'); };
  drop.ondragleave = () => drop.classList.remove('over');
  drop.ondrop = e => { e.preventDefault(); drop.classList.remove('over'); add(e.dataTransfer.files); };
  $('chips').onclick = e => { if (e.target.dataset.rm) { uploads.splice(+e.target.dataset.rm, 1); chips(); } };
  $('go').onclick = safe(async () => {
    const spec = {key: $('key').value.trim().toUpperCase(), profile: $('profile').value, trade_scope: $('trade').value.trim(), notes: $('notes').value.trim()};
    if (!/^[A-Z0-9][A-Z0-9_-]{1,23}$/.test(spec.key)) { $('key').focus(); throw Error('Clave corta: 2 a 24 letras o números, sin espacios.'); }
    const path = $('path').value.trim();
    if (!uploads.length && !path) throw Error('Sube los documentos del bid o indica una ruta local.');
    actor(); $('go').disabled = true;
    try {
      if (uploads.length) { spec.upload_id = crypto.randomUUID(); await sendFiles(spec.upload_id); } else spec.path = path;
      $('goInfo').textContent = 'Iniciando…';
      const run = await api('/api/app/run/start', {spec});
      location.hash = '#corrida/' + run.id;
    } finally { if ($('go')) { $('go').disabled = false; $('goInfo').textContent = 'Modelo: ' + status.model; } }
  });
}
async function sendFiles(uploadId) {
  const CHUNK = 6 * 1024 * 1024, total = uploads.reduce((a, f) => a + f.size, 0) || 1;
  let sent = 0; $('upBar').classList.remove('hidden');
  for (const f of uploads) {
    for (let i = 0, off = 0; off < f.size || i === 0; i++, off += CHUNK) {
      const bytes = new Uint8Array(await f.slice(off, off + CHUNK).arrayBuffer());
      let bin = ''; for (let j = 0; j < bytes.length; j += 32768) bin += String.fromCharCode.apply(null, bytes.subarray(j, j + 32768));
      await api('/api/app/upload', {upload_id: uploadId, name: f.name, index: i, content: btoa(bin)});
      sent += bytes.length;
      $('upBar').firstElementChild.style.width = (sent / total * 100).toFixed(1) + '%';
      $('goInfo').textContent = `Subiendo ${f.name} — ${Math.round(sent / total * 100)}%`;
    }
  }
}

/* ───────── Entregas ───────── */
async function entregas() {
  const runs = await api('/api/app/runs');
  view.innerHTML = `<h1>Entregas</h1><p class="sub">Cada corrida guarda sus PDFs, el reporte, el paquete y la bitácora en su propia carpeta.</p><div class="card">${runsTable(runs.runs)}</div>`;
}

/* ───────── Corrida ───────── */
async function corrida(id) {
  const r = await api('/api/app/run?id=' + encodeURIComponent(id));
  const live = isLive(r.status), f = n => `/api/app/run/file?id=${encodeURIComponent(r.id)}&name=${encodeURIComponent(n)}`;
  const keep = live && $('logBox') ? $('logBox').scrollTop : null;
  const pct = live ? Math.max(r.turn / r.max_turns, r.tokens / r.budget_tokens) * 100 : 100;
  let body = '';
  if (live) {
    body = `<div class="card"><div class="row"><div class="grow"><h2>${esc(r.stage)}</h2><div class="muted">Paso ${r.turn} de máx. ${r.max_turns} · ${Number(r.tokens).toLocaleString('es-MX')} tokens equivalentes de ${Number(r.budget_tokens).toLocaleString('es-MX')}${r.pages ? ` · ${r.documents} documentos, ${r.pages} páginas` : ''}</div></div>
      <button class="danger" id="cancel">Cancelar</button></div><div class="bar" style="margin:12px 0"><i style="width:${pct.toFixed(1)}%"></i></div>
      <p class="muted">Puedes cerrar esta ventana: la corrida sigue mientras el motor esté abierto. Un juego de planos mediano tarda de 15 a 45 minutos.</p></div>`;
  } else {
    const banner = r.status === 'no-go' ? ['', 'NO-GO: el agente encontró un requisito que ya no se puede cumplir y no gastó en estimar. Lee el reporte.']
      : r.status === 'lista' ? ['ok', r.decision === 'GO_WITH_CONDITIONS' ? 'Paquete verificado, con condiciones: lee «Verificar antes de enviar».' : 'Paquete verificado. La propuesta es un borrador hasta que la autorices.']
      : r.status === 'autorizada' ? ['ok', `Propuesta autorizada por ${r.authorized_by}.`]
      : ['error', r.error || r.stage];
    body = `<div class="notice ${banner[0]}">${esc(banner[1])}</div>`;
    if (r.price) body += `<div class="card"><div class="row" style="gap:28px">
      <div class="stat"><div class="k">Precio de venta</div><div class="v">${money(r.price)}</div></div>
      <div class="stat"><div class="k">Costo directo</div><div class="v">${money(r.direct)}</div></div>
      <div class="stat"><div class="k">Verificación cruzada</div><div class="v">${esc(r.qa || '—')}</div></div>
      <div class="stat"><div class="k">Revisión independiente</div><div class="v">${esc(r.review || '—')}</div></div>
      <div class="stat"><div class="k">Propuesta</div><div><span class="pill ${r.authorized_by ? 'ok' : 'warn'}">${esc(r.proposal || '—')}</span></div></div></div></div>`;
    if (r.files.length) body += `<div class="card"><div class="row"><h2 class="grow">Documentos</h2>${r.zip ? `<a class="btn primary" href="${f(r.zip)}&download=1">Descargar ZIP de entrega</a>` : ''}</div>
      <div class="files">${r.files.map(x => `<a href="${f(x.name)}" target="_blank" rel="noopener"><b>${esc(x.name)}</b><span class="sz">${size(x.bytes)}</span></a>`).join('')}</div></div>`;
    if (['lista', 'autorizada'].includes(r.status)) body += `<div class="card"><h2>Siguiente paso</h2><div class="grid">
      ${r.status === 'lista' ? `<div><h3>Autorizar la propuesta</h3><p class="muted">Quita el sello DRAFT del documento 03 y vuelve a verificar. Queda registrado quién autorizó${r.generic ? '. Este paquete no tiene marca: primero aplícale un contratista.' : '.'}</p>
        ${field('Nota de autorización', 'authNote', '', {hint: 'opcional'})}<p><button class="primary" id="authorize" ${r.generic ? 'disabled' : ''}>Autorizar como ${esc($('actor').value || '…')}</button></p></div>` : ''}
      <div><h3>Aplicar a otro contratista</h3><p class="muted">Mismo takeoff, recalculado con las tarifas, markups, datos y logo de ese perfil. Crea una entrega nueva; esta no cambia.</p>
        <label class="f">Perfil<select id="rbProfile"></select></label><p><button id="rebrand">Generar para este contratista</button></p></div></div></div>`;
    if (r.report_md) body += `<div class="card report"><h2>Reporte del agente</h2>${md(r.report_md)}</div>`;
  }
  view.innerHTML = `<p class="muted"><a href="#entregas">← Entregas</a></p><div class="row"><h1 class="grow">${esc(r.key)}</h1>${pill(r.status)}</div>
    <p class="sub">${esc(r.contractor)}${r.generic ? ' (sin marca)' : ''} · ${esc(r.model)} · inició ${when(r.started_at)}${r.finished_at ? ' · terminó ' + when(r.finished_at) : ''} · ${esc(r.actor)}${r.source_run ? ` · a partir de <a href="#corrida/${esc(r.source_run)}">${esc(r.source_run)}</a>` : ''}</p>
    ${body}
    <div class="card"><h2>${live ? 'Avance en vivo' : 'Bitácora'}</h2><div class="log" id="logBox">${r.events.length ? r.events.slice().reverse().map(e => `<div><span class="st">${esc(e.stage || 'Trabajando')}</span>${e.turn ? ` <span class="tl">paso ${e.turn}</span>` : ''}${e.tools?.length ? ` <span class="tl">· ${esc(e.tools.join(', '))}</span>` : ''}${e.text ? `<br>${esc(e.text)}` : ''}</div>`).join('') : '<p class="muted">Sin eventos todavía.</p>'}</div>
    <p class="muted" style="margin:10px 0 0">Documentos: ${esc(r.docs)}${r.trade_scope ? ' · Alcance: ' + esc(r.trade_scope) : ''}${r.notes ? ' · Instrucciones: ' + esc(r.notes) : ''}</p></div>`;
  if (keep !== null) $('logBox').scrollTop = keep;
  $('liveDot').classList.toggle('hidden', !live);
  if ($('cancel')) $('cancel').onclick = safe(async () => { if (confirm('¿Cancelar esta corrida? Lo gastado hasta ahora no se recupera.')) { await api('/api/app/run/cancel', {id: r.id}); toast('Cancelando al terminar el paso actual…'); } });
  if ($('authorize')) $('authorize').onclick = safe(async () => {
    if (!confirm(`Vas a autorizar la propuesta de ${r.key} por ${money(r.price)} a nombre de ${actor()}. ¿Revisaste el reporte y los tres PDFs?`)) return;
    await api('/api/app/run/authorize', {id: r.id, note: $('authNote').value}); toast('Propuesta autorizada y regenerada.', 'ok'); route();
  });
  if ($('rebrand')) {
    const profs = await api('/api/app/profiles');
    $('rbProfile').innerHTML = profs.profiles.filter(p => p.name !== r.profile).map(p => `<option value="${esc(p.name)}">${esc(p.label)}</option>`).join('');
    $('rebrand').onclick = safe(async () => { const out = await api('/api/app/run/rebrand', {id: r.id, profile: $('rbProfile').value}); toast('Entrega generada.', 'ok'); location.hash = '#corrida/' + out.id; });
  }
  if (live) timer = setTimeout(() => route(true), 3000);
}

/* ───────── Administrador ───────── */
const TABS = [['conexiones', 'Conexiones'], ['motor', 'Motor'], ['entrega', 'Entrega'], ['contratistas', 'Contratistas'], ['tarifas', 'Tarifas L&I'], ['precios', 'Libro de precios'], ['productividad', 'Productividad']];
async function admin(tab, arg = '') {
  tab = tab || 'conexiones';
  const head = `<h1>Administrador</h1><p class="sub">Conecta lo que falte y ajusta cómo estima y cómo entrega el motor. Los cambios aplican a la siguiente corrida.</p>
    <div class="tabs">${TABS.map(([k, t]) => `<a href="#admin/${k}" class="${k === tab ? 'on' : ''}">${t}</a>`).join('')}</div>`;
  const fn = {conexiones: aConexiones, motor: aMotor, entrega: aEntrega, contratistas: aContratistas, tarifas: () => aTabla('wages'), precios: () => aTabla('price_book'), productividad: () => aTabla('productivity')}[tab] || aConexiones;
  view.innerHTML = head + '<div id="tab"></div>';
  await fn(arg);
}
const tabEl = () => $('tab');
async function saveSettings(patch) { await api('/api/app/settings', {settings: patch}); toast('Ajustes guardados.', 'ok'); }

async function aConexiones() {
  const [st, cfg] = await Promise.all([api('/api/app/status'), api('/api/app/settings')]);
  const k = st.key, lg = cfg.settings.legacy, t = st.checks.find(c => c.id === 'test');
  tabEl().innerHTML = `<div class="card"><h2>API de Anthropic (Claude)</h2>
    <p class="muted">Es lo que lee planos, specs y addenda. La clave se saca en console.anthropic.com → API Keys y necesita saldo en Billing.</p>
    <p>${k.configured ? `<span class="pill ok">Conectada</span> ${esc(k.source)} ${esc(k.hint)}` : '<span class="pill bad">Falta la clave</span>'}</p>
    <div class="grid">${field('Clave nueva', 'akey', '', {type: 'password', attrs: 'autocomplete="off" placeholder="sk-ant-…"'})}
      <div style="align-self:end">${check('Recordar en esta PC', 'aremember', false, 'Se guarda en tu perfil de Windows, fuera de la carpeta del motor. Sin marcar, dura hasta cerrar el motor.')}</div></div>
    <p class="row"><button class="primary" id="ksave">Guardar clave</button><button id="ktest" ${k.configured ? '' : 'disabled'}>Probar conexión</button><button id="kmodels" ${k.configured ? '' : 'disabled'}>Ver modelos de mi cuenta</button>${k.configured ? '<button class="danger" id="kclear">Quitar clave</button>' : ''}</p>
    <div id="ktestOut" class="muted">${esc(t.detail)}</div></div>
  <div class="card"><h2>Proveedor para fases IA de medición <span class="pill">opcional</span></h2>
    <p class="muted">Solo lo usa la pantalla «Medición en planos» (orquestador por fases, API compatible con OpenAI). El agente estimador no lo necesita.</p>
    <div class="grid">${field('URL base', 'lbase', lg.api_base, {attrs: 'placeholder="https://proveedor/v1"'})}${field('Modelo', 'lmodel', lg.model)}${field('Modelo auditor', 'laudit', lg.audit_model, {hint: 'opcional'})}
      ${field('Clave', 'lkey', '', {type: 'password', hint: st.legacy_key.configured ? 'ya hay una guardada ' + st.legacy_key.hint : '', attrs: 'autocomplete="off"'})}</div>
    <p>${check('El modelo acepta imágenes', 'lvision', lg.vision)}</p><p><button id="lsave">Guardar proveedor</button></p></div>`;
  $('ksave').onclick = safe(async () => { await api('/api/app/key', {name: 'anthropic', key: $('akey').value, remember: $('aremember').checked}); toast('Clave guardada. Pruébala.', 'ok'); route(); });
  $('ktest').onclick = safe(async () => { $('ktestOut').textContent = 'Probando…'; const r = await api('/api/app/test', {}); $('ktestOut').innerHTML = r.ok ? `<span class="pill ok">OK</span> Respondió ${esc(r.model)}` : `<span class="pill bad">Falló</span> ${esc(r.error)}`; });
  $('kmodels').onclick = safe(async () => { const r = await api('/api/app/models', {}); $('ktestOut').innerHTML = 'Modelos disponibles con tu clave: ' + r.models.map(m => `<code>${esc(m.id)}</code>`).join(', '); });
  if ($('kclear')) $('kclear').onclick = safe(async () => { if (confirm('¿Quitar la clave de esta PC?')) { await api('/api/app/key/clear', {name: 'anthropic'}); route(); } });
  $('lsave').onclick = safe(async () => {
    if ($('lkey').value.trim()) await api('/api/app/key', {name: 'legacy', key: $('lkey').value, remember: true});
    await saveSettings({legacy: {api_base: $('lbase').value, model: $('lmodel').value, audit_model: $('laudit').value, vision: $('lvision').checked}});
  });
}

async function aMotor() {
  const cfg = await api('/api/app/settings'), e = cfg.settings.engine, ids = cfg.models.map(m => m.id);
  const models = cfg.models.map(m => [m.id, m.label]).concat(ids.includes(e.model) ? [] : [[e.model, e.model + ' (personalizado)']]);
  tabEl().innerHTML = `<div class="card"><h2>Modelo y razonamiento</h2><div class="grid">
      ${select('Modelo del estimador', 'model', models, e.model)}${field('…u otro ID de modelo', 'modelCustom', '', {hint: 'opcional', attrs: 'placeholder="claude-…"'})}
      ${select('Profundidad de razonamiento', 'effort', cfg.efforts.map(x => [x, {low: 'Baja', medium: 'Media', high: 'Alta (recomendada)', xhigh: 'Muy alta', max: 'Máxima'}[x] || x]), e.effort, 'más alta = más cuidado y más costo')}
      ${field('Modelo del revisor', 'review_model', e.review_model, {hint: 'vacío = el mismo, con contexto nuevo'})}</div></div>
  <div class="card"><h2>Método</h2>
    ${check('Detenerse si un requisito obligatorio ya no se puede cumplir', 'preflight_stop', e.preflight_stop, 'Pre-bid o visita obligatoria ya pasada, fecha vencida sin extensión: reporta NO-GO antes de gastar en takeoff.')}
    ${check('Revisión independiente antes de entregar', 'independent_review', e.independent_review, 'Otra conversación revisa el paquete en frío (fechas, alcance, las 3 cantidades más grandes, ensambles completos) y regresa los bloqueadores al estimador.')}
    ${check('Buscar en internet precios y tarifas que falten', 'web_search', e.web_search, 'Lo que salga de internet se marca BUDGET con su fuente; nunca como cotización.')}
    ${check('Caché de prompt', 'prompt_cache', e.prompt_cache, 'Reutiliza lo ya leído entre pasos; baja el costo de corridas largas.')}
    <div class="grid" style="margin-top:12px">
      ${field('Rondas de corrección tras la revisión', 'review_fix_rounds', e.review_fix_rounds, {type: 'number', attrs: 'min="0" max="3"'})}
      ${field('Alerta de precio vs. libro de precios (%)', 'price_deviation_pct', e.price_deviation_pct, {type: 'number', attrs: 'min="5" max="300"'})}
      ${field('Búsquedas web por corrida', 'web_search_uses', e.web_search_uses, {type: 'number', attrs: 'min="0" max="60"'})}
      ${area('Instrucciones permanentes de la oficina', 'extra_instructions', e.extra_instructions, 'se agregan a todas las corridas; p. ej. «siempre cotizar galvanizado en caliente»')}</div></div>
  <div class="card"><h2>Límites de gasto</h2><div class="grid">
      ${field('Máximo de pasos', 'max_turns', e.max_turns, {type: 'number', attrs: 'min="10" max="400"'})}
      ${field('Presupuesto de tokens equivalentes', 'budget_tokens', e.budget_tokens, {type: 'number', hint: 'al llegar, cierra con lo que tiene', attrs: 'min="200000" step="100000"'})}
      ${field('Imágenes de planos en memoria', 'keep_images', e.keep_images, {type: 'number', attrs: 'min="2" max="40"'})}
      ${field('Versión de la herramienta de búsqueda', 'web_search_tool', e.web_search_tool, {hint: 'avanzado'})}</div></div>
  <p class="row"><button class="primary" id="save">Guardar ajustes del motor</button><button id="reset">Restaurar valores de fábrica</button></p>`;
  const num = id => Number($(id).value);
  $('save').onclick = safe(() => saveSettings({engine: {model: $('modelCustom').value.trim() || $('model').value, effort: $('effort').value, review_model: $('review_model').value,
    preflight_stop: $('preflight_stop').checked, independent_review: $('independent_review').checked, web_search: $('web_search').checked, prompt_cache: $('prompt_cache').checked,
    review_fix_rounds: num('review_fix_rounds'), price_deviation_pct: num('price_deviation_pct'), web_search_uses: num('web_search_uses'), extra_instructions: $('extra_instructions').value,
    max_turns: num('max_turns'), budget_tokens: num('budget_tokens'), keep_images: num('keep_images'), web_search_tool: $('web_search_tool').value}}).then(route));
  $('reset').onclick = safe(async () => { if (confirm('¿Restaurar todos los ajustes del motor?')) { await saveSettings({engine: cfg.defaults.engine}); route(); } });
}

async function aEntrega() {
  const [cfg, profs] = await Promise.all([api('/api/app/settings'), api('/api/app/profiles')]), d = cfg.settings.delivery;
  tabEl().innerHTML = `<div class="card"><h2>Cómo se entrega</h2>
    <p class="muted">Siempre: 01 Cost Analysis, 02 Material List y 03 Proposal salen del mismo cálculo y se verifican entre sí; la propuesta es DRAFT hasta que una persona la autoriza desde la entrega.</p>
    <div class="grid">${field('Carpeta de entregas', 'output_dir', d.output_dir, {hint: 'relativa a la carpeta del motor, o ruta completa'})}
      ${select('Contratista por defecto', 'default_profile', [['', '(el primero con marca)']].concat(profs.profiles.map(p => [p.name, p.label])), d.default_profile)}
      ${field('Etiqueta de tu hora local en fechas clave', 'local_time_label', d.local_time_label)}
      ${field('Diferencia contra hora del Pacífico (h)', 'tz', d.local_time_offset_from_pacific_h, {type: 'number', attrs: 'min="-12" max="12"'})}</div>
    <h3>Contenido</h3>
    ${check('Reporte del agente también en PDF', 'report_pdf', d.report_pdf)}
    ${check('Incluir en el ZIP el paquete JSON y el manifiesto de verificación', 'zip_json', d.zip_include_package_json, 'Sirve para regenerar o auditar los números.')}
    ${check('Incluir en el ZIP la bitácora paso a paso', 'zip_log', d.zip_include_log)}
    <p><button class="primary" id="save">Guardar ajustes de entrega</button></p></div>`;
  $('save').onclick = safe(() => saveSettings({delivery: {output_dir: $('output_dir').value, default_profile: $('default_profile').value, local_time_label: $('local_time_label').value,
    local_time_offset_from_pacific_h: Number($('tz').value), report_pdf: $('report_pdf').checked, zip_include_package_json: $('zip_json').checked, zip_include_log: $('zip_log').checked}}));
}

async function aContratistas(name) {
  const [profs, cfg] = await Promise.all([api('/api/app/profiles'), api('/api/app/settings')]);
  if (!name) {
    tabEl().innerHTML = `<div class="card"><div class="row"><h2 class="grow">Perfiles de contratista</h2><a class="btn primary" href="#admin/contratistas/_nuevo">Nuevo perfil</a></div>
      <table><thead><tr><th>Perfil</th><th>Markups (cont./OH/util.)</th><th>Logo</th><th>Oficio</th></tr></thead><tbody>${profs.profiles.map(p => `<tr class="click" data-prof="${esc(p.name)}"><td><b>${esc(p.label)}</b>${p.generic ? ' <span class="pill">sin marca</span>' : ''}</td><td>${esc(p.markups.contingency_pct)}% / ${esc(p.markups.overhead_pct)}% / ${esc(p.markups.profit_pct)}%</td><td>${p.has_logo ? 'Sí' : '—'}</td><td class="muted">${esc(p.trade) || '— se pide en cada estimado'}</td></tr>`).join('')}</tbody></table>
      <p class="muted" style="margin-bottom:0">El modelo no puede cambiar markups, carga laboral, impuesto ni comisión: salen de aquí.</p></div>`;
    return;
  }
  const isNew = name === '_nuevo';
  const base = isNew ? (await api('/api/app/profile?name=generico_sin_marca').catch(() => ({profile: {contractor: {}, markups: {}, labor_rates: {}}}))).profile : (await api('/api/app/profile?name=' + encodeURIComponent(name))).profile;
  const p = JSON.parse(JSON.stringify(base));
  if (isNew) { p.generic = false; p.profile = ''; p.estimate_prefix = ''; p.contractor = {name: '', tag: '', address: '', license: '', phone: '', email: '', contact: ''}; }
  const c = p.contractor, m = p.markups || {}, com = p.alkan_commission || {};
  const rates = Object.entries(p.labor_rates || {});
  tabEl().innerHTML = `<p class="muted"><a href="#admin/contratistas">← Perfiles</a></p>
  <div class="card"><h2>${isNew ? 'Nuevo perfil' : esc(p.profile || c.name)}</h2><div class="grid">
    ${field('Nombre del perfil', 'p_profile', p.profile || '', {hint: 'como lo verás en la lista'})}${field('Prefijo de folio', 'p_prefix', p.estimate_prefix || '', {attrs: 'placeholder="SS-EST-2026"'})}
    ${field('Razón social', 'c_name', c.name)}${field('Giro (línea bajo el nombre)', 'c_tag', c.tag || '', {hint: 'opcional'})}
    ${field('Dirección', 'c_address', c.address, {cls: 'wide'})}${field('Licencia WA · UBI', 'c_license', c.license)}${field('Teléfono', 'c_phone', c.phone)}
    ${field('Correo', 'c_email', c.email || '', {hint: 'opcional'})}${field('Contacto que firma', 'c_contact', c.contact)}
    <label class="f">Logo <small>PNG o JPG${c.logo ? ' — ya tiene uno; sube otro para cambiarlo' : ''}</small><input type="file" id="c_logo" accept=".png,.jpg,.jpeg"></label>
    <div style="align-self:end">${check('Perfil sin marca (preestimado genérico)', 'p_generic', !!p.generic)}</div></div></div>
  <div class="card"><h2>Números del contratista</h2><div class="grid">
    ${field('Contingencia %', 'm_cont', m.contingency_pct ?? '5')}${field('Overhead %', 'm_oh', m.overhead_pct ?? '10')}${field('Utilidad %', 'm_profit', m.profit_pct ?? '10')}${field('Redondeo del precio ($)', 'm_round', m.rounding ?? '50')}
    ${field('Carga sobre prevailing wage %', 'p_burden', p.burden_pct ?? '15', {hint: 'impuestos de nómina, L&I, liability'})}${field('Vigencia de la propuesta (días)', 'p_validity', p.validity_days ?? 30, {type: 'number'})}
    ${select('Relación contractual', 'p_rel', Object.entries(cfg.relationships), p.relationship || 'sub_to_gc')}${select('Nivel del estimado', 'p_tier', Object.entries(cfg.tiers), p.tier || 'competitive')}
    ${field('Comisión Alkan: encontrar y estimar %', 'k_find', com.find_estimate_pct ?? '3')}${field('Comisión Alkan: coordinación %', 'k_coord', com.coordination_pct ?? '3')}
    <div class="wide">${check('La coordinación va incluida en la comisión', 'k_inc', !!com.coordination_included, 'La comisión es informativa en el Cost Analysis; no cambia el precio de venta.')}</div></div>
    <h3>Tarifas cargadas de taller y oficina</h3>
    <div class="kb"><table><thead><tr><th>Clave</th><th>Etiqueta</th><th>$/h</th><th>Fuente</th><th></th></tr></thead><tbody id="rates">${rates.map(([k, r]) => rateRow(k, r)).join('')}</tbody></table></div>
    <p><button id="addRate">Agregar tarifa</button> <span class="muted">Las de campo (prevailing wage) las pone el agente por condado desde «Tarifas L&I».</span></p></div>
  <div class="card"><h2>Oficio y alcance</h2><div class="grid">
    ${area('Política de alcance', 'p_scope', (p.scope_policy || []).join('\n'), 'una idea por renglón, en inglés: qué incluye y qué excluye siempre este contratista')}
    ${field('Secciones de spec del oficio', 'p_sections', (p.spec_sections || []).join(', '), {cls: 'wide', hint: 'opcional — p. ej. 05 50 00, 05 52 00, 32 31 13'})}</div></div>
  <p><button class="primary" id="psave">Guardar perfil</button></p>`;
  $('addRate').onclick = () => $('rates').insertAdjacentHTML('beforeend', rateRow('', {label: '', rate: '', source: ''}));
  $('rates').onclick = e => { if (e.target.dataset.del !== undefined) e.target.closest('tr').remove(); };
  $('psave').onclick = safe(async () => {
    const v = id => $(id).value.trim();
    Object.assign(p, {profile: v('p_profile') || v('c_name'), estimate_prefix: v('p_prefix'), generic: $('p_generic').checked, burden_pct: v('p_burden'), validity_days: Number(v('p_validity')) || 30,
      relationship: $('p_rel').value, tier: $('p_tier').value, scope_policy: $('p_scope').value.split('\n').map(s => s.trim()).filter(Boolean),
      spec_sections: v('p_sections').split(',').map(s => s.trim()).filter(Boolean)});
    p.contractor = {...c, name: v('c_name'), tag: v('c_tag'), address: v('c_address'), license: v('c_license'), phone: v('c_phone'), email: v('c_email'), contact: v('c_contact')};
    p.markups = {...m, contingency_pct: v('m_cont'), overhead_pct: v('m_oh'), profit_pct: v('m_profit'), rounding: v('m_round')};
    p.alkan_commission = {...com, find_estimate_pct: v('k_find'), coordination_pct: v('k_coord'), coordination_included: $('k_inc').checked};
    p.labor_rates = {};
    for (const tr of $('rates').rows) { const [k, l, r, s] = [...tr.querySelectorAll('input')].map(i => i.value.trim()); if (k) p.labor_rates[k.toUpperCase()] = {label: l, kind: 'loaded', rate: r, source: s}; }
    let logo = null; const file = $('c_logo').files[0];
    if (file) { const b = new Uint8Array(await file.arrayBuffer()); let bin = ''; for (let j = 0; j < b.length; j += 32768) bin += String.fromCharCode.apply(null, b.subarray(j, j + 32768)); logo = {content: btoa(bin)}; }
    const out = await api('/api/app/profile/save', {name: isNew ? (v('p_profile') || v('c_name')) : name, profile: p, logo});
    toast('Perfil guardado.', 'ok'); location.hash = '#admin/contratistas/' + out.name; if (!isNew) route();
  });
}
const rateRow = (k, r) => `<tr><td><input type="text" value="${esc(k)}" placeholder="SHOP" style="text-transform:uppercase;min-width:70px"></td><td><input type="text" value="${esc(r.label)}"></td><td><input type="text" value="${esc(r.rate)}" style="min-width:70px"></td><td class="w"><input type="text" value="${esc(r.source || '')}"></td><td><button class="link" data-del>Quitar</button></td></tr>`;

const TABLES = {
  wages: {title: 'Tarifas de prevailing wage (L&I)', help: 'Tarifa journey-level total (salario + fringe) por condado y oficio, con fuente y fecha. L&I publica normalmente en marzo y agosto. Una fila sin verificar obliga al agente a confirmarla en internet.',
    cols: {county: 'Condado', trade: 'Oficio', classification: 'Clasificación', rate: '$/h', effective: 'Vigente desde', source: 'Fuente', verified: 'Verificada'}, wide: ['source']},
  price_book: {title: 'Libro de precios', help: 'El agente busca aquí antes que en internet y prefiere QUOTE > CATALOG > BUDGET. Cada cotización real que cargues como QUOTE vuelve más preciso el siguiente estimado.',
    cols: {item: 'Artículo', spec: 'Especificación', unit: 'Unidad', unit_price: 'Precio unitario', price_basis: 'Base', source: 'Fuente', date: 'Fecha', county: 'Condado'}, wide: ['item', 'spec', 'source']},
  productivity: {title: 'Productividad', help: 'Horas por unidad por tarea. Ajústalas con las horas reales de obra.',
    cols: {task: 'Tarea', rate: 'Horas', unit: 'Unidad', trade: 'Oficio', source: 'Fuente'}, wide: ['task', 'source']},
};
async function aTabla(table) {
  const T = TABLES[table], data = await api('/api/app/knowledge?table=' + table);
  let rows = data.rows.map(r => ({...r})), dirty = false;
  const fields = Object.keys(T.cols);
  tabEl().innerHTML = `<div class="card"><div class="row"><h2 class="grow">${T.title} <span class="pill">${rows.length} filas</span> ${data.edited ? '<span class="pill warn">editada</span>' : '<span class="pill">de fábrica</span>'}</h2>
      <input type="text" id="kq" placeholder="Filtrar…" style="max-width:220px"></div><p class="muted">${T.help}</p>
    <div class="kb"><table><thead><tr>${fields.map(f => `<th>${T.cols[f]}</th>`).join('')}<th></th></tr></thead><tbody id="kbody"></tbody></table></div>
    <p class="row" style="margin-top:12px"><button class="primary" id="ksave" disabled>Guardar cambios</button><button id="kadd">Agregar fila</button>${data.edited ? '<button class="danger" id="kreset">Volver a la tabla de fábrica</button>' : ''}<span class="muted">Cada guardado deja una copia de la versión anterior en data/knowledge/_historial.</span></p></div>`;
  const draw = () => {
    const q = $('kq').value.trim().toLowerCase();
    $('kbody').innerHTML = rows.map((r, i) => (q && !fields.some(f => String(r[f] ?? '').toLowerCase().includes(q))) ? '' : `<tr>${fields.map(f => f === 'verified'
      ? `<td style="text-align:center"><input type="checkbox" data-i="${i}" data-f="${f}" ${r[f] ? 'checked' : ''}></td>`
      : `<td class="${T.wide.includes(f) ? 'w' : ''}"><input type="text" data-i="${i}" data-f="${f}" value="${esc(r[f])}"></td>`).join('')}<td><button class="link" data-del="${i}">Quitar</button></td></tr>`).join('');
  };
  const touch = () => { dirty = true; $('ksave').disabled = false; };
  draw();
  $('kq').oninput = draw;
  $('kbody').oninput = e => { const {i, f} = e.target.dataset; if (i === undefined) return; rows[i][f] = e.target.type === 'checkbox' ? e.target.checked : e.target.value; touch(); };
  $('kbody').onclick = e => { if (e.target.dataset.del !== undefined) { rows.splice(+e.target.dataset.del, 1); touch(); draw(); } };
  $('kadd').onclick = () => { rows.unshift(Object.fromEntries(fields.map(f => [f, f === 'verified' ? false : f === 'price_basis' ? 'QUOTE' : f === 'date' || f === 'effective' ? new Date().toISOString().slice(0, 10) : '']))); $('kq').value = ''; touch(); draw(); $('kbody').querySelector('input').focus(); };
  $('ksave').onclick = safe(async () => { await api('/api/app/knowledge/save', {table, rows}); dirty = false; toast('Tabla guardada.', 'ok'); route(); });
  if ($('kreset')) $('kreset').onclick = safe(async () => { if (confirm('¿Volver a la tabla de fábrica? Tu versión queda guardada en el historial.')) { await api('/api/app/knowledge/reset', {table}); route(); } });
  window.onbeforeunload = () => dirty ? true : undefined;
}

/* ───────── router ───────── */
async function route(refresh = false) {
  clearTimeout(timer); window.onbeforeunload = null;
  const [name, a, b] = decodeURIComponent(location.hash.slice(1) || 'inicio').split('/');
  for (const el of document.querySelectorAll('#nav a[data-v]')) el.classList.toggle('on', el.dataset.v === (name === 'corrida' ? 'entregas' : name));
  if (!refresh) { view.innerHTML = '<p class="muted">Cargando…</p>'; window.scrollTo(0, 0); }
  try {
    if (name === 'nuevo') await nuevo();
    else if (name === 'entregas') await entregas();
    else if (name === 'corrida') await corrida(a);
    else if (name === 'admin') await admin(a, b);
    else await inicio();
  } catch (e) {
    if (refresh) timer = setTimeout(() => route(true), 6000);
    else view.innerHTML = `<div class="notice error">${esc(e.message)}</div><p><a href="#inicio">Volver al inicio</a></p>`;
  }
}
view.addEventListener('click', e => {
  const run = e.target.closest('[data-run]'), prof = e.target.closest('[data-prof]');
  if (run) location.hash = '#corrida/' + run.dataset.run;
  if (prof) location.hash = '#admin/contratistas/' + prof.dataset.prof;
});
window.addEventListener('hashchange', () => route());
(async () => {
  $('actor').value = localStorage.getItem('alkan.actor') || '';
  $('actor').onchange = () => localStorage.setItem('alkan.actor', $('actor').value.trim());
  try {
    token = (await api('/api/session')).token;
    const st = await api('/api/app/status');
    $('ver').textContent = 'v' + st.version;
    $('liveDot').classList.toggle('hidden', !st.active_run);
    route();
  } catch (e) { view.innerHTML = '<div class="notice error">No se pudo conectar con el motor local. Ábrelo con Start-BidEngine.ps1 y recarga esta página.</div>'; }
})();
})();
