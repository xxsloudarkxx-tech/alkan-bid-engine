/* Contractor Mode reuses V2.1 forms and the persistent EstimateWorkflow API. */
'use strict';
(() => {
 const params=new URLSearchParams(location.search),advanced=params.get('mode')==='advanced';
 const switcher=document.createElement('a');switcher.id='modeSwitch';switcher.style.color='white';switcher.href=advanced?'/?mode=contractor':'/?mode=advanced';switcher.textContent=advanced?'Abrir modo contratista':'Modo avanzado';document.querySelector('header').append(switcher);
 switcher.onclick=()=>{if(current)switcher.href+=(switcher.href.includes('?')?'&':'?')+'project_id='+encodeURIComponent(current.project_id);};
 document.querySelector('header small').textContent='Bid Engine V3 · '+(advanced?'Modo avanzado':'Modo contratista');
 if(advanced){
  if(params.get('project_id'))resume(params.get('project_id'),false);
  return;
 }
 document.body.classList.add('contractor-mode');
 const styles=document.createElement('style');styles.textContent=`
 .contractor-mode{background:#edf3f1}.contractor-mode main{max-width:1180px}.guided-intro{margin:0 0 18px;max-width:800px;color:#35515b;line-height:1.6}
 #guideHeader{background:#fff;border-radius:12px;padding:18px;margin-bottom:18px;border:1px solid #d9e2e4}#guideNav{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px;margin:14px 0 0}
 #guideNav button{text-align:left;background:#e8efed;color:#234b4e;padding:12px;font-size:13px;min-width:0}#guideNav button.active{background:#103e43;color:white}#guideNav button.done::after{content:' ✓';color:#46b09d}
 #guideProgress{width:100%;height:8px;accent-color:#277d73}#guideTitle{font-size:24px;margin-bottom:8px}.guide-bottom{position:sticky;bottom:0;background:#fff;padding:12px;border:1px solid #d9e2e4;border-radius:10px;display:flex;justify-content:space-between;gap:12px;z-index:4}
 #guideSaved{font-size:12px;color:#47635f}#guideAlerts ul{padding-left:20px}#guideAlerts button{background:transparent;color:#18565f;text-align:left;padding:4px;text-decoration:underline}
 .workflow-pending{border-left:4px solid #d9ad59;padding:12px;background:#fff8e7}.workflow-complete{border-left:4px solid #277d73;padding:12px;background:#e6f5ee}
 #downloadList a{display:block;padding:12px;border-bottom:1px solid #dce7e4}#analysisSummary{display:flex;flex-wrap:wrap;gap:10px;margin:14px 0}#analysisSummary span{background:#edf3f1;padding:9px;border-radius:7px}
 .contractor-mode .metric{font-size:23px}.contractor-mode input,.contractor-mode select,.contractor-mode textarea{min-width:0}.contractor-mode section{min-width:0}#guideHistory{margin-top:16px}
 @media(max-width:640px){#guideNav{grid-template-columns:1fr 1fr}#guideNav button:last-child{grid-column:1/-1}#guideHeader{padding:14px}#guideTitle{font-size:21px}.guide-bottom button{font-size:13px;padding:10px}.contractor-mode header{gap:12px}}
 `;document.head.append(styles);
 const names=['Proyecto y documentos','Análisis y evidencia','Partidas y cantidades','Proveedores y costos','Aprobación y documentos'];
 const ids=['documents','analysis','quantities','costs','approval'];
 const intro=[
  'Comience con el proyecto y sus documentos. Los archivos originales se conservan y puede agregar otros después.',
  'Revise lo que se pudo leer y su procedencia. Los documentos escaneados necesitan revisión manual; no hay OCR configurado.',
  'Confirme o corrija cantidades, unidades y especificaciones. Resuelva las diferencias de alcance con evidencia antes de aprobar.',
  'Compare cotizaciones, seleccione condiciones elegibles y revise costos y margen. Los valores que falten permanecen pendientes.',
  'Complete los datos comerciales, revise los pendientes y apruebe esta versión. Descargue los documentos sin enviarlos automáticamente.'
 ];
 const header=document.createElement('div');header.id='guideHeader';header.innerHTML='<div id="guideSaved">Expediente nuevo · sin guardar</div><h2 id="guideTitle">1. Proyecto y documentos</h2><progress id="guideProgress" max="100" value="0" aria-label="Progreso de verificaciones"></progress><nav id="guideNav" aria-label="Etapas del estimado">'+names.map((n,i)=>`<button data-step="${ids[i]}">${i+1}. ${n}</button>`).join('')+'</nav>';
 $('createPanel').before(header);
 const workspace=$('workspace'),technicalNav=workspace.querySelector('nav');technicalNav.hidden=true;
 workspace.querySelector('.steps').hidden=true;
 const guide=document.createElement('div');guide.id='guidedPages';guide.innerHTML=ids.map((id,i)=>`<div id="guide-${id}" data-guide-page="${id}" hidden><p class="guided-intro">${intro[i]}</p></div>`).join('');workspace.append(guide);
 const uploadSection=document.createElement('section');uploadSection.innerHTML='<h2>Agregar documentos</h2><p class="muted">PDF, TXT UTF-8, PNG/JPEG y catálogos CSV/XLSX. Máximo 25 MB por archivo y 20 por carga.</p><div class="actions" id="guidedUploadControls"></div><div id="uploadedSummary"></div><div class="actions"><button id="guideAnalyze">Analizar documentos y continuar</button></div>';$('guide-documents').append(uploadSection);
 for(const id of ['files','upload','importLegacy'])$('guidedUploadControls').append($(id));
 const docSection=$('documents').closest('section');const drop=docSection.querySelector('.dropzone');if(drop)uploadSection.prepend(drop);
 $('guide-analysis').append(docSection);
 docSection.insertAdjacentHTML('afterbegin','<div id="analysisSummary"></div>');
 for(const child of Array.from($('analysis').children))$('guide-quantities').append(child);
 for(const child of Array.from($('estimate').children)){
  if(child.querySelector('#actualForm')||child.querySelector('#batchForm')){const more=document.createElement('details');more.innerHTML='<summary>'+ (child.querySelector('#actualForm')?'Seguimiento de costos ejecutados (opcional)':'Cotización compartida (opcional)')+'</summary>';child.before(more);more.append(child);$('guide-costs').append(more);}
  else $('guide-costs').append(child);
 }
 for(const child of Array.from($('review').children))$('guide-approval').append(child);
 const historyDetails=document.createElement('details');historyDetails.id='guideHistory';historyDetails.innerHTML='<summary>Versiones del expediente y diferencias</summary>';$('guide-approval').append(historyDetails);historyDetails.append($('history').querySelector('section'));historyDetails.ontoggle=()=>{if(historyDetails.open)history().catch(e=>notice(e.message,true));};
 for(const id of ['analysis','estimate','review','history'])$(id).hidden=true;
 const alerts=document.createElement('section');alerts.id='guideAlerts';workspace.insertBefore(alerts,guide);
 const bottom=document.createElement('div');bottom.className='guide-bottom';bottom.innerHTML='<button class="secondary" id="guideBack">Anterior</button><button id="guideNext">Continuar</button>';workspace.append(bottom);
 $('guide-costs').insertAdjacentHTML('beforeend','<section><h2>Comprobar cálculo actual</h2><p class="muted">Recalcula con cantidades y precios verificados. Los costos parciales siguen identificados como pendientes.</p><button id="guideCalculate">Calcular y guardar revisión</button></section>');
 const scopeLabel=field($('lineForm'),'scope_key').closest('label'),scopeDetails=document.createElement('details');scopeDetails.innerHTML='<summary>Comparar referencias del mismo alcance (opcional)</summary><p class="muted">Use la misma referencia solo si las cantidades describen el mismo elemento y alcance. Si representan trabajos distintos, regístrelo en la conciliación.</p>';scopeLabel.before(scopeDetails);scopeDetails.append(scopeLabel);
 $('issueForm').closest('section').insertAdjacentHTML('beforeend','<div class="actions"><button id="guideExportAll">Generar los tres documentos finales</button></div><div id="downloadList" aria-live="polite"></div><div id="autoDocs" aria-live="polite"></div>');
 let step='documents',pending=new Map(),createId=crypto.randomUUID(),saving=false;
 const baseApi=api;
 function operationKey(path,data){return path+'|'+JSON.stringify(data);}
 api=async function(path,data){
  if(!data)return baseApi(path.replace('/api/project?','/api/workflow?'));
  if(saving)throw Error('Hay un guardado en curso. Espere la confirmación antes de continuar.');
  let target=path,body={...data};
  if(path==='/api/create'){target='/api/workflow/create';body.request_id=createId;}
  else if(path==='/api/action')target='/api/workflow/action';
  else if(path==='/api/upload')target='/api/workflow/upload';
  else if(path==='/api/catalog-use')target='/api/workflow/catalog-use';
  if(target.startsWith('/api/workflow/')&&!body.request_id){const key=operationKey(target,body);if(!pending.has(key))pending.set(key,crypto.randomUUID());body.request_id=pending.get(key);}
  const key=operationKey(target,data);saving=true;try{let result=await baseApi(target,body);if(result?.state&&!result.workflow_view)result=await baseApi('/api/workflow?project_id='+encodeURIComponent(result.project_id));pending.delete(key);return result;}finally{saving=false;}
 };
 // Show understandable blocker messages and route the contractor to the relevant stage.
 const fieldNames={address:'dirección',state:'estado',county:'condado',jurisdiction:'jurisdicción',client:'cliente',contractor:'contratista',trade:'especialidad',estimator:'responsable',terms:'condiciones',valid_until:'vigencia',assumptions:'supuestos',exclusions:'exclusiones',overhead_percent:'indirectos',contingency_percent:'contingencia',target_margin_percent:'margen'};
 function blocker(code){
  const suffix=code.split(':').slice(1).join(':'),line=current?.state.lines.find(l=>l.line_id===suffix),label=line?.description||'';
  if(code==='DOCUMENTS_PENDING')return ['Cargue los documentos del proyecto.','documents'];
  if(code==='DOCUMENT_REVIEW_PENDING')return ['Revise los documentos y registre lo que pudo verificar.','analysis'];
  if(code.includes('CONTRADICTIONS'))return ['Concilie las contradicciones y los alcances mencionados.','quantities'];
  if(code.startsWith('QUANTITY_FORMULA'))return ['La fórmula no coincide con la cantidad: '+label,'quantities'];
  if(code.includes('QUANTITY'))return ['Confirme la cantidad y su evidencia: '+label,'quantities'];
  if(code.startsWith('PROJECT_FIELD_PENDING:'))return ['Complete '+(fieldNames[suffix]||suffix)+' del proyecto.','approval'];
  if(code.startsWith('COMMERCIAL_FIELD_PENDING:'))return ['Complete '+(fieldNames[suffix]||suffix)+' de la propuesta.','approval'];
  if(code.includes('FINANCIAL_INPUT_PENDING:'))return ['Revise el porcentaje de '+(fieldNames[suffix]||suffix)+'.','costs'];
  if(code.includes('TAX'))return ['Documente el tratamiento tributario para este contrato y jurisdicción.','approval'];
  if(code.includes('SCOPE_REVIEW'))return ['Confirme que el alcance completo fue revisado.','approval'];
  if(code.includes('CONTRACTOR_IDENTITY'))return ['Confirme la identidad comercial del contratista.','approval'];
  if(code.includes('COMPLIANCE')||code.includes('CHANGE_ORDER'))return ['Revise requisitos documentados y cambios contractuales pendientes.','approval'];
  if(code.includes('PROPOSAL_VALIDITY')||code.includes('COMMERCIAL'))return ['Revise la vigencia y las condiciones comerciales.','approval'];
  if(code.includes('PRICE')||code.includes('QUOTE')||code.includes('OPTION')||code.includes('cost')||code.includes('financial')||code.includes('selected')||code.includes('FINANCIAL'))return ['Revise cotizaciones, selección y parámetros de costos.','costs'];
  return ['Hay una verificación pendiente. Consulte el detalle de la partida y su evidencia.','costs'];
 }
 function updateGuide(){
  if(!current){showStep('documents');return;}
  const view=current.workflow_view,state=current.state;
  if(view)step=view.current_step;
  $('guideProgress').value=view?.progress||0;
  $('guideSaved').textContent='Guardado · revisión '+current.revision+' · '+current.actor+' · '+new Date(current.created_at).toLocaleString();
  $('status').dataset.code=state.result.status;$('status').textContent=({DOCUMENTS_PENDING:'Documentos pendientes',QUANTITIES_PENDING:'Cantidades pendientes',PRICES_PENDING:'Precios pendientes',HUMAN_REVIEW_PENDING:'Revisión pendiente',READY_FOR_HUMAN_REVIEW:'Listo para aprobación humana',APPROVED:'Aprobado',PROPOSAL_ISSUED:'Propuesta emitida'})[state.result.status]||'Revisión pendiente';
  $('uploadedSummary').innerHTML=state.documents.map(d=>'<p class="file-name">'+esc(d.original_name)+' · versión '+esc(d.version)+'</p>').join('')||'<p>Agregue documentos para comenzar.</p>';
  $('analysisSummary').innerHTML=`<span>${state.documents.length} documentos conservados</span><span>${state.lines.length} partidas preliminares</span><span>${view?.manual_review_documents.length||0} requieren revisión manual</span>`;
  const messages=new Map();for(const code of state.result.release_blockers){const [text,target]=blocker(code);messages.set(text,target);}
  const list=Array.from(messages).map(([text,target])=>`<li><button data-go-step="${target}">${esc(text)}</button></li>`).join('');
  $('guideAlerts').innerHTML=messages.size?'<details><summary>'+messages.size+' verificaciones para completar el estimado</summary><ul>'+list+'</ul></details>':'<p class="workflow-complete">'+(view?.approved?'Versión aprobada. Puede generar los tres documentos.':'Verificaciones completas. Falta su aprobación explícita.')+'</p>';
  $('blockers').innerHTML=messages.size?'<p>La entrega final está bloqueada hasta resolver estas verificaciones.</p>':'<p class="ok">Verificaciones completas. Confirme la aprobación de esta versión.</p>';
  for(const b of document.querySelectorAll('[data-go-step]'))b.onclick=safe(()=>go(b.dataset.goStep));
  for(const b of document.querySelectorAll('[data-step]')){b.classList.toggle('done',view?.steps.find(s=>s.id===b.dataset.step)?.complete||false);b.setAttribute('aria-current',b.dataset.step===step?'step':'false');}
  $('guideAnalyze').disabled=!state.documents.length;$('guideExportAll').disabled=!view?.approved;
  $('autoDocs').innerHTML=(view?.generated_documents||[]).map(d=>'<p><a href="'+esc(d.url)+'" target="_blank" rel="noopener">'+esc(d.label)+' (PDF automático)</a></p>').join('')||'<p>Los PDF se generan al aprobar y al registrar el contrato.</p>';
  for(const b of document.querySelectorAll('[data-export]')){const kind=b.dataset.export;b.textContent=({internal:'Análisis interno (PDF)',supplier:'Materiales / Proveedores (PDF)',proposal:'Propuesta comercial (PDF)'})[kind]+(kind!=='proposal'&&!view?.approved?' · Borrador':'');}
  $('resolutionForm').hidden=!state.result.issues.some(i=>!i.resolved);
  const quantityNames={AUTO_EXTRACTED:'Extraída automáticamente; pendiente de confirmar',CALCULATED_FROM_MEASUREMENTS:'Calculada de medidas; pendiente de confirmar',PENDING_VERIFICATION:'Pendiente de verificación',MANUALLY_CORRECTED:'Corregida manualmente; pendiente de confirmar',CONFIRMED_WITH_EVIDENCE:'Confirmada con evidencia'};
  const rows=$('lineTable').querySelectorAll('tbody tr');state.lines.forEach((line,i)=>{const row=rows[i];if(!row)return;row.cells[2].textContent=quantityNames[line.quantity_status]||'Pendiente de revisión';const calc=line.calculation;row.cells[3].textContent=calc?.operation==='sum'?(calc.operands||[]).join(' + '):calc?.operation==='product'?(calc.operands||[]).join(' × '):calc?.operation==='productivity'?'Producción / productividad':'Medición directa o pendiente';if(line.assumptions?.length)row.cells[3].append(Object.assign(document.createElement('p'),{textContent:line.assumptions.join('; ')}));});
  const optional=document.createElement('details');optional.innerHTML='<summary>Fechas y próxima acción (opcional)</summary><div class="grid"></div>';
  for(const name of ['request_date','due_date','next_action']){const input=field($('projectForm'),name);if(input)optional.querySelector('.grid').append(input.closest('label'));}
  $('projectFields').append(optional);
  for(const b of document.querySelectorAll('[data-review-doc]')){
   const d=state.documents.find(d=>d.document_id===b.dataset.reviewDoc),form=document.createElement('form');form.className='guided-document-review';
   form.innerHTML='<label>Resultado de revisión<textarea required aria-label="Resultado de revisión de '+esc(d.original_name)+'">'+esc(d.review_notes||'')+'</textarea></label><div class="actions"><button>Guardar revisión del documento</button></div>';
   b.replaceWith(form);form.onsubmit=safe(()=>act('review_document',{document_id:d.document_id,notes:form.querySelector('textarea').value}));
  }
  showStep(step);scrollTables();
 }
 function showStep(id){step=id;const i=ids.indexOf(id);$('guideTitle').textContent=(i+1)+'. '+names[i];$('metrics').hidden=i<3;for(const page of document.querySelectorAll('[data-guide-page]'))page.hidden=page.dataset.guidePage!==id;for(const b of document.querySelectorAll('[data-step]'))b.classList.toggle('active',b.dataset.step===id);$('guideBack').disabled=i===0;$('guideNext').hidden=i===4;}
 async function go(id){
  if(!current){if(id!=='documents')throw Error('Cree el proyecto y cargue documentos para continuar');showStep(id);return;}
  if(id===step)return;
  await act('transition',{step:id});window.scrollTo({top:$('guideHeader').offsetTop,behavior:'smooth'});
 }
 for(const b of document.querySelectorAll('[data-step]'))b.onclick=safe(()=>go(b.dataset.step));
 $('guideBack').onclick=safe(()=>go(ids[Math.max(0,ids.indexOf(step)-1)]));
 $('guideNext').onclick=safe(async()=>{if(step==='documents'||step==='analysis'&&!current.workflow_view.analyzed){await act('analyze');if(step==='analysis')return;}else await go(ids[Math.min(4,ids.indexOf(step)+1)]);});
 $('guideAnalyze').onclick=safe(()=>act('analyze'));$('guideCalculate').onclick=safe(()=>act('calculate'));
 const baseRender=render;render=function(){baseRender();updateGuide();};
 safe=function(fn){return async e=>{if(e)e.preventDefault();const button=e?.submitter||e?.currentTarget;const controls=button?.matches?.('button')?[button]:[];for(const c of controls)c.disabled=true;try{await fn(e);}catch(err){notice(err.message,true);}finally{for(const c of controls)c.disabled=false;}};};
 // Existing handlers use safe(); overlapping mutations are rejected with an actionable message.
 const baseCreate=$('createForm').onsubmit;
 $('createForm').onsubmit=safe(async e=>{await baseCreate(e);if(current){try{localStorage.setItem('alkan-v3-project',current.project_id);}catch{}updateGuide();}});
 const baseNew=$('newProject').onclick;
 $('newProject').onclick=()=>{current=null;createId=crypto.randomUUID();pending.clear();baseNew();$('guideSaved').textContent='Expediente nuevo · sin guardar';$('guideProgress').value=0;showStep('documents');try{localStorage.removeItem('alkan-v3-project');}catch{}};
 const baseOpen=$('openProject').onclick;
 $('openProject').onclick=safe(async e=>{await baseOpen(e);if(current){if(!current.workflow_view)current=await baseApi('/api/workflow?project_id='+encodeURIComponent(current.project_id));render();try{localStorage.setItem('alkan-v3-project',current.project_id);}catch{}}});
 for(const b of document.querySelectorAll('[data-export]'))b.onclick=safe(()=>download([b.dataset.export]));
 $('guideExportAll').onclick=safe(()=>download(['internal','supplier','proposal']));
 async function download(kinds){
  const result=await api('/api/workflow/export',{project_id:current.project_id,revision:current.revision,kinds,language:$('language').value,final:current.workflow_view.approved});
  current=result.row;render();$('downloadList').innerHTML=result.artifacts.map(a=>`<a href="${esc(a.url)}" download>${esc(a.kind)} · ${a.final?'Revisado y aprobado':'Borrador'} · revisión ${a.source_revision}</a>`).join('');
  notice('Documentos guardados. Pulse cada enlace para descargar. No se han enviado.');
 }
 showStep('documents');
 let saved=params.get('project_id');try{saved=saved||localStorage.getItem('alkan-v3-project');}catch{}
 if(saved)resume(saved,true);

 async function resume(pid,guided){
  try{
   token=(await baseSession()).token;
   current=await (guided?api('/api/workflow?project_id='+encodeURIComponent(pid)):api('/api/project?project_id='+encodeURIComponent(pid)));
   await projects();render();
  }catch(e){notice('No se pudo recuperar el expediente: '+e.message,true);}
 }
 async function baseSession(){const r=await fetch('/api/session');return r.json();}
})();
