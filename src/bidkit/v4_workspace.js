/* ALKAN Bid Engine v4 Enterprise Views (13 Workspaces + 7 Canonical States) */
(function(){
  const V4_VIEWS = {
    dashboard: { title: "Project Dashboard", sub: "Canonical 7-state portfolio overview & readiness" },
    docs: { title: "Document Manager", sub: "Expediente files, PDF/scan detection & revision tracking" },
    viewer: { title: "Drawing Viewer", sub: "Interactive scale calibration & plan inspection canvas" },
    takeoff: { title: "Takeoff Workspace", sub: "Measured vs declared quantities, waste & traceability" },
    catalog: { title: "Material Catalog", sub: "Pricebook (BUDGET / QUOTE / HISTORICAL / ALLOWANCE / VERIFIED)" },
    quotes: { title: "Supplier Quotes", sub: "Import CSV/XLSX/PDF quotes, pending review & vendor comparison" },
    labor: { title: "Labor Database", sub: "Base/fringe/burden/loaded/commercial rates & productivity norms" },
    "cost-analysis": { title: "Cost Analysis", sub: "13-bucket breakdown, Markup vs Margin & 3 Scenarios" },
    review: { title: "Estimate Review", sub: "Independent QA discrepancies & anti-self-approval signoff" },
    rfq: { title: "RFQ Manager", sub: "RFI drafts, supplier RFQs, coverage & manual send gate" },
    proposals: { title: "Proposal Generator", sub: "6 normalized deliverables (PDF / XLSX / DOCX) & immutable versions" },
    integrations: { title: "Integration Status", sub: "ALKAN Workflow Studio, Contractor Superbot & QuickBooks Online" },
    audit: { title: "Audit Trail", sub: "SHA-256 hash-chained event ledger & verified backups" }
  };

  let _token = null;
  async function tok(){
    if(_token) return _token;
    const r = await fetch("/api/session");
    const j = await r.json();
    _token = j.token;
    return _token;
  }
  function actorName(){
    return (document.getElementById("actor")?.value || "").trim() || "Estimator";
  }
  async function v4Get(path){
    const r = await fetch(path);
    const j = await r.json();
    if(!r.ok) throw new Error(j.error || r.statusText);
    return j;
  }
  async function v4Post(path, body){
    const t = await tok();
    const r = await fetch(path, {
      method: "POST",
      headers: {"Content-Type":"application/json","X-ALKAN-Token":t},
      body: JSON.stringify({actor: actorName(), ...body})
    });
    const j = await r.json();
    if(!r.ok) throw new Error(j.error || r.statusText);
    return j;
  }
  function esc(s){ return String(s==null?"":s).replace(/[&<>"']/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }
  function statePill(st){
    const cls = st==="Approved"||st==="Exported"?"ok":(st==="Rejected"||st==="Error"?"bad":(st==="Processing"?"live":"warn"));
    return `<span class="pill ${cls}">${esc(st||"Draft")}</span>`;
  }

  async function renderV4(key){
    const meta = V4_VIEWS[key];
    if(!meta) return false;
    document.querySelectorAll("#nav a").forEach(a => a.classList.toggle("on", a.getAttribute("href") === "#" + key));
    const view = document.getElementById("view");
    view.innerHTML = `<h1>${esc(meta.title)}</h1><p class="sub">${esc(meta.sub)}</p><div class="card">Cargando…</div>`;

    try {
      if(key === "dashboard"){
        const d = await v4Get("/api/v4/dashboard");
        const pills = d.canonical_states.map(s => `<div class="stat"><div class="k">${statePill(s)}</div><div class="v">${d.counts[s]||0}</div></div>`).join("");
        const rows = d.runs.map(r => `<tr><td><b>${esc(r.key)}</b><div class="muted">${esc(r.id)}</div></td><td>${statePill(r.canonical_state)}</td><td>${esc(r.contractor||"-")}</td><td class="num">${r.price?"$"+esc(r.price):"-"}</td><td>${esc(r.authorized_by||"Pending")}</td></tr>`).join("") || `<tr><td colspan="5" class="muted">No hay estimados registrados.</td></tr>`;
        view.innerHTML = `<h1>${esc(meta.title)}</h1><p class="sub">${esc(meta.sub)}</p>
          <div class="card"><div class="row">${pills}</div></div>
          <div class="card"><h2>Estimados activos e históricos</h2><table><thead><tr><th>Proyecto</th><th>Estado Canónico</th><th>Contratista</th><th class="num">Precio</th><th>Aprobación</th></tr></thead><tbody>${rows}</tbody></table></div>`;
      } else if(key === "catalog" || key === "quotes"){
        const pb = await v4Get("/api/v4/pricebook");
        const rows = pb.records.slice(0, 80).map(r => `<tr><td>${esc(r.id)}</td><td><b>${esc(r.material)}</b><div class="muted">${esc(r.specification_std)}</div></td><td>${statePill(r.price_type)}</td><td class="num">$${esc(r.unit_price)} / ${esc(r.estimate_unit)}</td><td>${esc(r.supplier||"-")}</td><td>${esc(r.verification_status)}${r.expired?' <span class="pill bad">EXPIRED</span>':''}</td></tr>`).join("");
        view.innerHTML = `<h1>${esc(meta.title)}</h1><p class="sub">${esc(meta.sub)}</p>
          <div class="card"><div class="row"><button class="primary" onclick="location.hash='#quotes'">Importar CSV/XLSX/PDF vía API /v4/pricebook/import</button><span class="muted">Registros totales: ${pb.records.length}</span></div></div>
          <div class="card"><table><thead><tr><th>ID</th><th>Material / Norma</th><th>Clasificación</th><th class="num">Precio</th><th>Proveedor</th><th>Verificación</th></tr></thead><tbody>${rows}</tbody></table></div>`;
      } else if(key === "labor"){
        const lb = await v4Get("/api/v4/labor");
        const wrows = lb.wages.map(w => `<tr><td>${esc(w.county)}, ${esc(w.state)}</td><td>${esc(w.trade)} (${esc(w.classification)})</td><td class="num">$${esc(w.base_wage)}</td><td class="num">${esc(w.labor_burden_pct)}%</td><td class="num"><b>$${esc(w.loaded_rate)}</b></td><td>${w.verified?'<span class="pill ok">Verified</span>':'<span class="pill warn">Unverified</span>'}</td></tr>`).join("");
        const prows = lb.productivity.slice(0, 40).map(p => `<tr><td>${esc(p.norm_id)}</td><td>${esc(p.task)}</td><td>${esc(p.trade)}</td><td class="num">${esc(p.hours_per_unit)} ${esc(p.unit)}</td><td>${esc(p.source)}</td></tr>`).join("");
        view.innerHTML = `<h1>${esc(meta.title)}</h1><p class="sub">${esc(meta.sub)}</p>
          <div class="card"><h2>Tarifas Salariales (Base -> Burden -> Loaded)</h2><table><thead><tr><th>Ubicación</th><th>Oficio</th><th class="num">Base</th><th class="num">Burden</th><th class="num">Loaded</th><th>Estado</th></tr></thead><tbody>${wrows}</tbody></table></div>
          <div class="card"><h2>Normas de Productividad</h2><table><thead><tr><th>ID</th><th>Actividad</th><th>Oficio</th><th class="num">Rendimiento</th><th>Fuente</th></tr></thead><tbody>${prows}</tbody></table></div>`;
      } else if(key === "viewer"){
        view.innerHTML = `<h1>${esc(meta.title)}</h1><p class="sub">${esc(meta.sub)}</p>
          <div class="card">
            <div class="row" style="margin-bottom:10px">
              <button class="primary" id="v4CalBtn">Calibrar escala de referencia</button>
              <a class="btn" href="/herramientas">Abrir Calibrador PDF Completo</a>
              <span class="muted" id="v4ViewerMsg">Haga clic en dos puntos sobre el lienzo para medir escala</span>
            </div>
            <canvas id="v4PlanCanvas" width="840" height="360" style="border:1px solid var(--border);background:#fafbfc;width:100%;max-width:840px;cursor:crosshair"></canvas>
          </div>`;
        const c = document.getElementById("v4PlanCanvas");
        const ctx = c.getContext("2d");
        ctx.strokeStyle = "#d9e2e4";
        for(let x=0;x<840;x+=40){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,360);ctx.stroke();}
        for(let y=0;y<360;y+=40){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(840,y);ctx.stroke();}
        let pts = [];
        c.addEventListener("click", ev => {
          const r = c.getBoundingClientRect();
          const x = (ev.clientX - r.left) * (c.width / r.width);
          const y = (ev.clientY - r.top) * (c.height / r.height);
          pts.push([x, y]);
          ctx.fillStyle = "#B3121B";
          ctx.beginPath(); ctx.arc(x, y, 4, 0, Math.PI*2); ctx.fill();
          if(pts.length >= 2){
            const [a, b] = pts.slice(-2);
            ctx.strokeStyle = "#103e43"; ctx.lineWidth = 2;
            ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
            const px = Math.hypot(b[0]-a[0], b[1]-a[1]).toFixed(1);
            document.getElementById("v4ViewerMsg").textContent = `Segmento medido: ${px} px (use escala real para calibrar)`;
          }
        });
      } else if(key === "integrations"){
        const st = await v4Get("/api/v4/integrations/status");
        view.innerHTML = `<h1>${esc(meta.title)}</h1><p class="sub">${esc(meta.sub)}</p>
          <div class="grid">
            <div class="card"><h2>ALKAN Workflow Studio</h2><p>${st.workflow_studio.configured?'<span class="pill ok">Configured</span>':'<span class="pill warn">Outbox Local</span>'}</p><p class="muted">Eventos soportados: ${st.workflow_studio.supported_events.length}</p><p class="muted">En cola: ${st.workflow_studio.outbox_counts.pending} · Enviados: ${st.workflow_studio.outbox_counts.delivered}</p></div>
            <div class="card"><h2>Contractor Superbot</h2><p><span class="pill ok">Bridge Active</span></p><p class="muted">Oportunidades recibidas: ${st.superbot_jobs.length}</p></div>
            <div class="card"><h2>QuickBooks Online</h2><p>${st.quickbooks.credentials_ready?'<span class="pill ok">Credentials Ready</span>':'<span class="pill warn">Credentials Required</span>'}</p><p class="muted">Env: ${esc(st.quickbooks.environment)} · Faltan: ${esc(st.quickbooks.missing_credentials.join(", ")||"ninguna")}</p></div>
          </div>`;
      } else if(key === "audit"){
        const aud = await v4Get("/api/v4/audit-trail");
        const erows = aud.events.map(e => `<tr><td>${e.seq}</td><td>${esc(e.timestamp)}</td><td>${esc(e.actor)} (${esc(e.role)})</td><td><b>${esc(e.action)}</b></td><td>${esc(e.state_from)} → ${esc(e.state_to)}</td><td class="muted">${esc(e.entry_hash.slice(0,12))}…</td></tr>`).join("") || `<tr><td colspan="6" class="muted">Sin eventos registrados aún.</td></tr>`;
        view.innerHTML = `<h1>${esc(meta.title)}</h1><p class="sub">${esc(meta.sub)}</p>
          <div class="card"><div class="row"><span>Integridad cadena SHA-256: ${aud.chain_verification.valid?'<span class="pill ok">VALID</span>':'<span class="pill bad">INVALID</span>'} (${aud.chain_verification.count} eventos)</span><button class="primary" id="v4BackupBtn">Crear Respaldo Verificado</button></div><div id="v4BackupOut" class="muted" style="margin-top:8px"></div></div>
          <div class="card"><table><thead><tr><th>#</th><th>Fecha</th><th>Actor</th><th>Acción</th><th>Transición</th><th>Hash</th></tr></thead><tbody>${erows}</tbody></table></div>`;
        document.getElementById("v4BackupBtn").onclick = async () => {
          const res = await v4Post("/api/v4/backup/create", {role:"admin"});
          document.getElementById("v4BackupOut").textContent = `Respaldo creado: ${res.zip_path} (${res.file_count} archivos, SHA-256 ${res.zip_sha256.slice(0,16)}…)`;
        };
      } else {
        const dash = await v4Get("/api/v4/dashboard");
        const opts = dash.runs.map(r => `<option value="${esc(r.id)}">${esc(r.key)} — ${esc(r.canonical_state)}</option>`).join("");
        view.innerHTML = `<h1>${esc(meta.title)}</h1><p class="sub">${esc(meta.sub)}</p>
          <div class="card"><div class="row"><label class="f grow">Seleccionar corrida/estimado<select id="v4RunSel">${opts||'<option value="">Sin corridas aún</option>'}</select></label><button class="primary" id="v4ExecBtn">Cargar datos de ${esc(meta.title)}</button></div><pre id="v4Out" style="white-space:pre-wrap;font-size:12.5px;margin-top:12px" class="muted">Seleccione un proyecto o corrida para inspeccionar.</pre></div>`;
        document.getElementById("v4ExecBtn").onclick = async () => {
          const rid = document.getElementById("v4RunSel").value;
          const out = document.getElementById("v4Out");
          if(!rid){ out.textContent = "No hay corridas disponibles."; return; }
          try{
            let data;
            if(key === "cost-analysis") data = await v4Post("/api/v4/cost-analysis", {run_id: rid});
            else if(key === "review") data = await v4Post("/api/v4/review/run", {run_id: rid, role:"reviewer"});
            else if(key === "rfq") data = await v4Post("/api/v4/rfi-rfq/generate", {run_id: rid});
            else if(key === "proposals") data = await v4Post("/api/v4/deliverables/generate", {run_id: rid, role:"operator"});
            else data = await v4Get("/api/app/run?id=" + encodeURIComponent(rid));
            out.textContent = JSON.stringify(data, null, 2);
          }catch(err){ out.textContent = "Error: " + err.message; }
        };
      }
    } catch (err) {
      view.innerHTML = `<h1>${esc(meta.title)}</h1><div class="notice error">${esc(err.message)}</div>`;
    }
    return true;
  }

  function intercept(){
    const h = (location.hash || "").replace(/^#/, "");
    if(V4_VIEWS[h]){
      renderV4(h);
    }
  }
  window.addEventListener("hashchange", intercept, true);
  window.addEventListener("DOMContentLoaded", () => setTimeout(intercept, 20));
})();
