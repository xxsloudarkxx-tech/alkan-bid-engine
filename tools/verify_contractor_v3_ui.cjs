/* All mutations through the Contractor Mode UI. Disposable data, no external services. */
const {chromium}=require('playwright-core');
const {spawn,spawnSync}=require('node:child_process');
const fs=require('node:fs');const path=require('node:path');const assert=require('node:assert/strict');
(async()=>{
 const root=path.resolve(__dirname,'..'),output=path.join(root,process.env.ALKAN_AUDIT_DIR||'data/v3_audit');fs.mkdirSync(output,{recursive:true});
 const work=fs.mkdtempSync(path.join(root,'tmp/v3-browser-'));
 const python=process.env.ALKAN_PYTHON||'C:\\Users\\diana\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\python\\python.exe';
 const port=18905,url=`http://127.0.0.1:${port}`;let server,browser,page;let logs='';const errors=[];
 const source='Anonymous supplier quotation. Materials: 100 USD per panel, freight 25 USD. Revised material price: 105 USD. Labor: 50 USD per hour, freight 0 USD. Specification S1. Tax 0 and discount 0 for synthetic QA only.';
 const pdf=spawnSync(python,['-c',"from reportlab.pdfgen import canvas;import sys;from io import BytesIO;b=BytesIO();c=canvas.Canvas(b,invariant=1);[c.drawString(40,750-i*18,t) for i,t in enumerate(sys.argv[1].split('. '))];c.save();sys.stdout.buffer.write(b.getvalue())",source],{windowsHide:true});assert.equal(pdf.status,0,String(pdf.stderr));
 async function start(){logs='';server=spawn(python,[path.join(root,'run_bidkit.py'),'estimate-ui','--root',work,'--port',String(port),'--no-browser'],{cwd:root,windowsHide:true,stdio:['ignore','pipe','pipe']});server.stdout.on('data',x=>logs+=x);server.stderr.on('data',x=>logs+=x);for(let i=0;i<80&&!logs.includes('http://');i++)await new Promise(r=>setTimeout(r,100));assert(logs.includes('http://'),logs);}
 async function stop(){if(server&&!server.killed){const stopped=new Promise(r=>server.once('exit',r));server.kill();await stopped;}}
 try{
  await start();browser=await chromium.launch({executablePath:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',headless:true});
  page=await browser.newPage({viewport:{width:1440,height:1000},acceptDownloads:true});page.on('pageerror',e=>errors.push(e.message));
  async function save(locator,action){const pending=page.waitForResponse(r=>r.url().endsWith('/api/workflow/action')&&r.request().postDataJSON()?.action===action);await locator.click();const response=await pending;const body=await response.json();assert(response.ok(),JSON.stringify(body));await page.waitForFunction(revision=>current?.revision===revision,body.revision);return body;}
  async function go(step){if(await page.locator(`[data-guide-page=${step}]`).isVisible())return;await save(page.locator(`[data-step=${step}]`),'transition');assert(await page.locator(`[data-guide-page=${step}]`).isVisible());}
  await page.goto(url+'/expedientes');await page.locator('#actor').fill('Anonymous V3 reviewer');
  const create=page.locator('#createForm');for(const [key,value] of Object.entries({name:'Anonymous V3 guided acceptance',address:'Synthetic location',trade:'Fencing'}))await create.locator(`[name=${key}]`).fill(value);
  await page.locator('#initialFiles').setInputFiles([{name:'anonymous_scope.txt',mimeType:'text/plain',buffer:Buffer.from('Anonymous Scope of work\n10 EA panels\n8 HR labor\nSpecification S1. Synthetic measurements; no real client.')},{name:'anonymous_quote.pdf',mimeType:'application/pdf',buffer:pdf.stdout}]);
  const uploaded=page.waitForResponse(r=>r.url().endsWith('/api/workflow/upload'));await create.locator('button').click();assert((await uploaded).ok());await page.waitForFunction(()=>current?.state.documents.length===2);
  assert.equal(await page.locator('#guide-documents').isVisible(),true);assert.equal(await page.locator('#guideExportAll').isDisabled(),true);
  await save(page.locator('#guideAnalyze'),'analyze');assert.equal(await page.locator('[data-edit-line]').count(),2);
  // Re-analyze must preserve candidate identity.
  await save(page.locator('#analyze'),'analyze');assert.equal(await page.locator('[data-edit-line]').count(),2);
  for(let i=0;i<2;i++){
   const details=page.locator('#documents > details').nth(i);await details.locator(':scope > summary').click();await details.locator('textarea').fill('Anonymous QA: reviewed source text and page; synthetic evidence only.');await save(details.getByRole('button',{name:'Guardar revisión del documento'}),'review_document');
  }
  await page.screenshot({path:path.join(output,'guided_analysis_desktop.png'),fullPage:true});
  await go('quantities');
  for(let i=0;i<2;i++){
   await page.locator('[data-edit-line]').nth(i).click();const form=page.locator('#lineForm');await form.locator('[name=quantity_status]').selectOption('CONFIRMED_WITH_EVIDENCE');await form.locator('[name=category]').selectOption(i===0?'material':'labor');await form.locator('[name=specification]').fill('S1');await save(form.locator('button'),'line');
  }
  // A correction and a subsequent evidence-backed confirmation create separate revisions.
  await page.locator('[data-edit-line]').first().click();await page.locator('#lineForm [name=quantity]').fill('11');await page.locator('#lineForm [name=quantity_status]').selectOption('MANUALLY_CORRECTED');await save(page.locator('#lineForm button'),'line');
  await page.locator('[data-edit-line]').first().click();await page.locator('#lineForm [name=quantity]').fill('10');await page.locator('#lineForm [name=quantity_status]').selectOption('CONFIRMED_WITH_EVIDENCE');await save(page.locator('#lineForm button'),'line');
  while(await page.locator('#issueSelect option').count()){
   await page.locator('#resolutionForm [name=disposition]').selectOption('included');await page.locator('#resolutionForm [name=reason]').fill('Synthetic reviewed scope and specification included.');await page.locator('#reDoc').selectOption({label:'anonymous_scope.txt'});await page.locator('#reExcerpt').fill('Specification S1. Synthetic measurements; no real client.');await save(page.locator('#resolutionForm button'),'resolve');
  }
  await page.reload();await page.waitForFunction(()=>current?.workflow_view.current_step==='quantities');assert(await page.locator('#guide-quantities').isVisible());await page.locator('#actor').fill('Anonymous V3 reviewer');
  await go('costs');await page.locator('#supplierFormDetails > summary').click();const supplier=page.locator('#supplierForm');await supplier.locator('[name=name]').fill('Anonymous supplier');await supplier.locator('[name=location]').fill('Synthetic branch');await save(supplier.locator('button'),'supplier');
  await page.locator('#quoteFormDetails > summary').click();const quote=page.locator('#quoteForm');
  const today=new Date().toISOString().slice(0,10);
  for(let i=0;i<2;i++){
   await quote.locator('[name=line_id]').selectOption({index:i});await quote.locator('[name=supersedes]').selectOption('');
   for(const [key,value] of Object.entries({description:i?'Anonymous labor quote':'Anonymous panel quote',specification:'S1',unit:i?'HR':'EA',pack_size:'1',unit_price:i?'50':'100',delivery:i?'0':'25',tax_total:'0',discount_percent:'0',quoted_on:today,valid_until:'2099-12-31'}))await quote.locator(`[name=${key}]`).fill(value);
   for(const key of ['technical_match','availability_confirmed','confirmed'])await quote.locator(`[name=${key}]`).check();
   await page.locator('#qeDoc').selectOption({label:'anonymous_quote.pdf'});await page.locator('#qeExcerpt').fill(i?'Labor: 50 USD per hour, freight 0 USD':'Materials: 100 USD per panel, freight 25 USD');
   await save(quote.locator('button'),'quote');await save(page.locator('[data-select-quote]').last(),'select_quote');
  }
  // Supplier update is a new immutable quote, requiring explicit selection.
  await page.locator('[data-edit-quote]').first().click();await quote.locator('[name=unit_price]').fill('105');await page.locator('#qeExcerpt').fill('Revised material price: 105 USD');
  for(const key of ['technical_match','availability_confirmed','confirmed'])await quote.locator(`[name=${key}]`).check();
  await save(quote.locator('button'),'quote');assert((await page.locator('#scenarios').textContent()).includes('50.00'));await save(page.locator('[data-select-quote]').last(),'select_quote');
  const financial=page.locator('#financialForm');for(const [key,value] of Object.entries({overhead_percent:'10',contingency_percent:'0',target_margin_percent:'20',sensitivity_percent:'5'}))await financial.locator(`[name=${key}]`).fill(value);
  await financial.locator('[name=confirmed]').check();await save(financial.locator('button'),'settings');await save(page.locator('#guideCalculate'),'calculate');
  assert((await page.locator('#metrics').textContent()).includes('2028.13'));
  await page.screenshot({path:path.join(output,'guided_costs_desktop.png'),fullPage:true});
  await go('approval');assert(await page.locator('#approve').isDisabled());assert(await page.locator('#guideExportAll').isDisabled());
  // Draft supplier request can be generated while final release is blocked.
  await page.locator('[data-export=supplier]').click();await page.waitForFunction(()=>document.querySelectorAll('#downloadList a').length===1);assert((await page.locator('#downloadList').textContent()).includes('Borrador'));
  const project=page.locator('#projectForm');for(const [key,value] of Object.entries({state:'WA',county:'Synthetic county',jurisdiction:'Synthetic jurisdiction',client:'Anonymous client',contractor:'Anonymous contractor',estimator:'Anonymous reviewer'}))await project.locator(`[name=${key}]`).fill(value);await save(project.locator('button'),'settings');
  const review=page.locator('#reviewForm');for(const name of ['scope_confirmed','tax_reviewed','company_confirmed'])await review.locator(`[name=${name}]`).check();for(const [key,value] of Object.entries({tax_basis:'Explicit synthetic zero tax assumption, QA only; not Washington tax advice',assumptions:'Anonymous test scope',exclusions:'Unlisted work excluded',terms:'Synthetic QA terms',valid_until:'2099-12-31'}))await review.locator(`[name=${key}]`).fill(value);await save(review.locator('button'),'settings');
  await page.waitForFunction(()=>current.state.result.status==='READY_FOR_HUMAN_REVIEW');await page.locator('#humanConfirmation').check();await save(page.locator('#approve'),'approve');assert.equal(await page.locator('#guideExportAll').isDisabled(),false);
  const approved=await page.evaluate(()=>({pid:current.project_id,approval:current.state.current_approval.approval_id}));
  await page.locator('#guideExportAll').click();await page.waitForFunction(()=>document.querySelectorAll('#downloadList a').length===3);
  const downloads=[];for(let i=0;i<3;i++){const pending=page.waitForEvent('download');await page.locator('#downloadList a').nth(i).click();const download=await pending;const name=['internal','supplier','proposal'][i];await download.saveAs(path.join(output,`guided_${name}_SYNTHETIC.pdf`));downloads.push(name);}
  // V3.1 supplier export center: three read-only views, each as CSV and PDF.
  const supplierDownloads=[];
  for(const kind of ['directory','project','comparison']){
   await page.locator('#supplierExportKind').selectOption(kind);await page.locator('#supplierExportFormat').selectOption('both');
   const pendingResponse=page.waitForResponse(r=>r.url().endsWith('/api/supplier-export'));
   await page.locator('#supplierExportButton').click();const exportResponse=await pendingResponse;assert(exportResponse.ok(),await exportResponse.text());
   const exportBody=await exportResponse.json();assert.equal(exportBody.kind,kind);assert.equal(exportBody.artifacts.length,2);
   await page.waitForFunction(()=>document.querySelectorAll('#supplierExportLinks a').length===2);
   for(let i=0;i<2;i++){const link=page.locator('#supplierExportLinks a').nth(i),pending=page.waitForEvent('download');await link.click();const download=await pending;const saved=path.join(output,`supplier_${kind}_${i?'pdf':'csv'}_SYNTHETIC.${i?'pdf':'csv'}`);await download.saveAs(saved);const bytes=fs.readFileSync(saved);assert(i?bytes.subarray(0,4).toString()==='%PDF':bytes.subarray(0,3).equals(Buffer.from([0xef,0xbb,0xbf])));supplierDownloads.push(path.basename(saved));}
  }
  await page.screenshot({path:path.join(output,'guided_approval_desktop.png'),fullPage:true});
  // Actual server restart, same directory: restores stage and approval with a fresh session token.
  await stop();await start();await page.reload();await page.waitForFunction(()=>current?.workflow_view.approved);assert.equal(await page.locator('#guide-approval').isVisible(),true);await page.locator('#actor').fill('Anonymous V3 reviewer');
  assert.equal(await page.evaluate(()=>current.state.current_approval.approval_id),approved.approval);
  await page.setViewportSize({width:390,height:844});await go('costs');assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await page.screenshot({path:path.join(output,'guided_costs_mobile.png'),fullPage:true});await go('approval');assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await page.screenshot({path:path.join(output,'guided_approval_mobile.png'),fullPage:true});
  await page.locator('#modeSwitch').click();await page.waitForSelector('[data-tab=estimate]');assert.equal(await page.locator('body').evaluate(e=>e.classList.contains('contractor-mode')),false);await page.waitForFunction(()=>current?.state.current_approval);assert.equal(await page.evaluate(()=>current.project_id),approved.pid);
  assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(output,'guided_browser_results.json'),JSON.stringify({status:'PASS',synthetic:true,workspace:work,browser:await browser.version(),desktop:[1440,1000],mobile:[390,844],page_errors:errors,mobile_overflow:false,multiple_uploads:2,correction_history:true,quote_version_delta:'50.00',internal_cost:'1622.50',proposed_price:'2028.13',draft_before_approval:true,downloads,supplierDownloads,server_restart_recovered:true,advanced_mode_same_project:true,external_services:false},null,2));
  console.log('Contractor V3.1 PASS: document → review → suppliers → costs → approval → 3 PDFs + 3 supplier CSV/PDF exports; restart; desktop/mobile; advanced mode');
 }catch(e){if(page)await page.screenshot({path:path.join(output,'guided_failure.png'),fullPage:true}).catch(()=>{});throw e;}
 finally{if(browser)await browser.close();await stop();}
})().catch(e=>{console.error(e);process.exitCode=1;});
