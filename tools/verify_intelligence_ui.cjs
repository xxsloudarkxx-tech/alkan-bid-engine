/* Browser acceptance on a disposable local dossier. No remote pages or services. */
const {chromium}=require('playwright-core');
const {spawn}=require('node:child_process');
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');

(async()=>{
 const root=path.resolve(__dirname,'..');
 const work=fs.mkdtempSync(path.join(root,'tmp','v2-browser-'));
 const output=process.env.ALKAN_AUDIT_DIR||path.join(root,'data','v2_audit');
 fs.mkdirSync(output,{recursive:true});
 const python=process.env.ALKAN_PYTHON||'C:\\Users\\diana\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\python\\python.exe';
 const port=18875;
 const server=spawn(python,[path.join(root,'run_bidkit.py'),'estimate-ui','--root',work,'--port',String(port),'--no-browser'],{cwd:root,windowsHide:true,stdio:['ignore','pipe','pipe']});
 let logs='';server.stdout.on('data',x=>logs+=x);server.stderr.on('data',x=>logs+=x);
 let browser;
 try{
  for(let i=0;i<60&&!logs.includes('http://');i++)await new Promise(r=>setTimeout(r,100));
  assert(logs.includes('http://'),'server failed: '+logs);
  browser=await chromium.launch({executablePath:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',headless:true});
  const page=await browser.newPage({viewport:{width:1440,height:1000},acceptDownloads:true});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(`http://127.0.0.1:${port}/?mode=advanced`); await page.locator('#actor').fill('Anonymous browser reviewer');
  const create=page.locator('#createForm');
  await create.locator('[name=name]').fill('Anonymous browser acceptance');
  await create.locator('[name=address]').fill('Synthetic location');await create.locator('[name=trade]').fill('Fence');
  await page.locator('#initialFiles').setInputFiles({name:'synthetic_scope.txt',mimeType:'text/plain',buffer:Buffer.from('Scope of work: fence 10 EA panels.\nFormal quotation 100.00 each plus delivery 25.00. Specification S1. Test-only documented scope and price.\nSynthetic paid expense record: 1200 USD; reference ANONYMOUS-PAID-001.')});
  await create.locator('button').click();await page.waitForFunction(()=>document.querySelector('#revisionText').textContent.includes('Revisión 2'));
  await page.locator('#analyze').click();await page.waitForFunction(()=>document.querySelectorAll('[data-edit-line]').length===1);
  page.on('dialog',d=>d.accept('Synthetic full document review'));
  await page.locator('#documents > details > summary').first().click();
  await page.locator('[data-review-doc]').click();await page.waitForFunction(()=>document.querySelector('#documents').textContent.includes('Revisado por'));
  await page.locator('[data-edit-line]').click();const line=page.locator('#lineForm');
  await line.locator('[name=quantity_status]').selectOption('CONFIRMED_WITH_EVIDENCE');await line.locator('[name=specification]').fill('S1');await line.locator('button').click();
  await page.waitForFunction(()=>document.querySelector('#lineForm').hidden);
  await page.locator('[data-tab=estimate]').click();await page.locator('#supplierFormDetails summary').click();const supplier=page.locator('#supplierForm');await supplier.locator('[name=name]').fill('Synthetic supplier');await supplier.locator('[name=location]').fill('Synthetic branch');await supplier.locator('button').click();
  await page.waitForFunction(()=>document.querySelector('#suppliers').options.length===1);
  const quote=page.locator('#quoteForm');
  await page.locator('#quoteFormDetails > summary').click();
  const fields={description:'Synthetic panel quotation',specification:'S1',unit:'EA',pack_size:'1',unit_price:'100',delivery:'25',tax_total:'0',discount_percent:'0',quoted_on:new Date().toISOString().slice(0,10),valid_until:'2099-12-31'};
  for(const [key,value] of Object.entries(fields))await quote.locator(`[name=${key}]`).fill(value);
  for(const name of ['technical_match','availability_confirmed','confirmed'])await quote.locator(`[name=${name}]`).check();
  await page.locator('#qeExcerpt').fill('Formal quotation 100.00 each plus delivery 25.00. Specification S1. Test-only documented scope and price.');await quote.locator('button').click();
  await page.waitForFunction(()=>document.querySelectorAll('[data-select-quote]').length===1);await page.locator('[data-select-quote]').click();
  await page.waitForFunction(()=>document.querySelector('#comparisons').textContent.includes('Seleccionada'));
  if(process.env.ALKAN_V21){
   await page.locator('[data-tab=analysis]').click();
   const csv='product_name,supplier,location,unit,unit_price,pack_size,specification,currency,delivery,tax_total,discount_percent,quoted_on,valid_until,kind\nSynthetic catalog panel,Supplier B,Branch B,EA,100,1,S1,USD,5,0,0,'+fields.quoted_on+',2099-12-31,FORMAL_QUOTE\n';
   await page.locator('#analysis .dropzone').dispatchEvent('drop',{dataTransfer:await page.evaluateHandle(text=>{const d=new DataTransfer();d.items.add(new File([text],'synthetic_catalog.csv',{type:'text/csv'}));return d;},csv)});
   assert.equal(await page.locator('#files').evaluate(e=>e.files[0].name),'synthetic_catalog.csv');
   await page.locator('#upload').click();await page.waitForFunction(()=>document.querySelectorAll('#documents > details').length===2);
   await page.locator('#documents > details').nth(1).locator('summary').first().click();
   await page.locator('#documents > details').nth(1).locator('[data-review-doc]').click();
   await page.waitForFunction(()=>Array.from(document.querySelectorAll('#documents > details'))[1].textContent.includes('Revisado por'));
   await page.locator('#documents > details').nth(1).locator('summary').first().click();
   const imported=page.waitForResponse(r=>r.url().endsWith('/api/action')&&r.request().postDataJSON()?.action==='catalog_import');
   await page.locator('#documents > details').nth(1).getByRole('button',{name:'Importar filas',exact:false}).click();await imported;
   await page.locator('[data-tab=estimate]').click();await page.locator('#catalogQuery').fill('Synthetic catalog panel');await page.locator('#catalogSearch').click();
   await page.waitForFunction(()=>document.querySelectorAll('[data-use-catalog]').length===1);
   await page.locator('[data-use-catalog]').click();await page.waitForFunction(()=>document.querySelector('#comparisons').textContent.includes('Provisional'));
   assert((await page.locator('#comparisons').textContent()).includes('1005.00'));
   // Explicit review produces a new version; the imported reference remains pending.
   await quote.locator('[name=kind]').selectOption('formal_quote');
   for(const name of ['technical_match','availability_confirmed','confirmed'])await quote.locator(`[name=${name}]`).check();
   await quote.locator('button').click();await page.waitForFunction(()=>document.querySelectorAll('[data-select-quote]').length===1);
   assert((await page.locator('#comparisons').textContent()).includes('-20.00'));
  }
  await page.locator('[data-tab=analysis]').click();
  while(await page.locator('#issueSelect option').count()){
   const revision=await page.locator('#revisionText').textContent();
   await page.locator('#resolutionForm [name=disposition]').selectOption('included');
   await page.locator('#resolutionForm [name=reason]').fill('Included in the reviewed material specification and delivery quotation.');
   await page.locator('#reExcerpt').fill('Formal quotation 100.00 each plus delivery 25.00. Specification S1. Test-only documented scope and price.');
   await page.locator('#resolutionForm button').click();
   await page.waitForFunction(old=>document.querySelector('#revisionText').textContent!==old,revision);
  }
  await page.locator('[data-tab=estimate]').click();
  const financial=page.locator('#financialForm');
  for(const [key,value] of Object.entries({overhead_percent:'10',contingency_percent:'0',target_margin_percent:'20',sensitivity_percent:'5'}))await financial.locator(`[name=${key}]`).fill(value);
  await financial.locator('[name=confirmed]').check();await financial.locator('button').click();await page.waitForFunction(()=>document.querySelector('#metrics').textContent.includes('1409.38'));
  await page.locator('[data-tab=review]').click();const project=page.locator('#projectForm');
  for(const [key,value] of Object.entries({state:'WA',county:'Synthetic county',jurisdiction:'Synthetic jurisdiction',client:'Anonymous client',contractor:'Anonymous company',estimator:'Anonymous estimator'}))await project.locator(`[name=${key}]`).fill(value);
  const priorProjectRevision=await page.locator('#revisionText').textContent();
  await project.locator('button').click();
  await page.waitForFunction(old=>document.querySelector('#revisionText').textContent!==old,priorProjectRevision);
  const review=page.locator('#reviewForm');
  for(const name of ['scope_confirmed','tax_reviewed','company_confirmed'])await review.locator(`[name=${name}]`).check();
  for(const [key,value] of Object.entries({tax_basis:'Synthetic explicit zero applicable tax - QA only',assumptions:'Test scope only',exclusions:'No other work',terms:'Synthetic commercial terms',valid_until:'2099-12-31'}))await review.locator(`[name=${key}]`).fill(value);
  await review.locator('button').click();await page.waitForFunction(()=>document.querySelector('#status').textContent==='READY_FOR_HUMAN_REVIEW');
  await page.locator('#humanConfirmation').check();await page.locator('#approve').click();await page.waitForFunction(()=>document.querySelector('#status').textContent==='APPROVED');
  const downloads=[];
  for(const kind of ['internal','supplier','proposal']){const pending=page.waitForEvent('download');await page.locator(`[data-export=${kind}]`).click();const download=await pending;await download.saveAs(path.join(output,`browser_${kind}_SYNTHETIC.pdf`));downloads.push(kind);}
  await page.locator('[data-tab=history]').click();await page.waitForFunction(()=>document.querySelector('#historyRows').textContent.includes('approve'));
  await page.screenshot({path:path.join(output,'browser_desktop.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});await page.locator('[data-tab=analysis]').click();await page.screenshot({path:path.join(output,'browser_mobile.png'),fullPage:true});
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);assert.equal(overflow,false,'Mobile document overflow');
  await page.reload();await page.locator('#projectSelect').selectOption({label:'Anonymous browser acceptance'});await page.locator('#openProject').click();await page.waitForFunction(()=>document.querySelector('#status').textContent==='APPROVED');
  if(process.env.ALKAN_V21){
   await page.locator('#actor').fill('Anonymous actual cost reviewer');await page.locator('[data-tab=estimate]').click();
   const actual=page.locator('#actualForm');await actual.locator('..').locator(':scope > summary').click();
   for(const [key,value] of Object.entries({amount:'1200',incurred_on:fields.quoted_on,invoice_reference:'ANONYMOUS-PAID-001',provider:'Synthetic supplier'}))await actual.locator(`[name=${key}]`).fill(value);
   await page.locator('#acExcerpt').fill('Synthetic paid expense record: 1200 USD; reference ANONYMOUS-PAID-001.');
   await actual.locator('[name=human_confirmation]').check();
   await actual.locator('button').click();await page.waitForFunction(()=>document.querySelector('#actualTotals').textContent.includes('72.50'));
   assert.equal(await page.locator('[data-export=proposal]').isDisabled(),true);
   await page.reload();await page.locator('#projectSelect').selectOption({label:'Anonymous browser acceptance'});await page.locator('#openProject').click();await page.locator('[data-tab=estimate]').click();
   await page.waitForFunction(()=>document.querySelector('#actualTotals').textContent.includes('1200.00'));
   await page.locator('#actualSearch').locator('xpath=ancestor::details/summary').click();
   await page.locator('#actualProvider').fill('Synthetic supplier');await page.locator('#actualSearch').click();
   await page.waitForFunction(()=>document.querySelector('#actualAnalysis').textContent.includes('1200.00'));
   const estimateOverflow=await page.evaluate(()=>({overflow:document.documentElement.scrollWidth>innerWidth,elements:Array.from(document.querySelectorAll('body *')).filter(e=>e.getBoundingClientRect().right>innerWidth&&!e.closest('.scroll')).map(e=>({tag:e.tagName,id:e.id,cls:e.className,width:e.getBoundingClientRect().width,right:e.getBoundingClientRect().right})).slice(0,20)}));
   if(estimateOverflow.overflow)console.log(JSON.stringify(estimateOverflow));
   assert.equal(estimateOverflow.overflow,false,'Mobile estimate overflow');
   await page.screenshot({path:path.join(output,'browser_v21_costs_mobile.png'),fullPage:true});
  }
  assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(output,'browser_results.json'),JSON.stringify({status:'PASS',synthetic:true,workspace:work,downloads,page_errors:errors,mobile_overflow:overflow,flow:'create → upload → analyze → review document → edit quantity → supplier → quote → select → calculate → review → approve → 3 downloads → history → reload',v21:process.env.ALKAN_V21?{drag_drop_csv:true,catalog_row_evidence:true,reviewed_reference:true,normalized_alternative:'1005.00',alternative_difference:'-20.00',approved_proposal:'1409.38',internal_estimated_cost:'1127.50',documented_actual_cost:'1200.00',documented_variance:'72.50',history_analysis:true,proposal_blocked_after_change:true,persisted_cost_after_reload:true}:null,browser:await browser.version()},null,2));
  console.log('Browser flow PASS: desktop/mobile, persisted approval, 3 PDF downloads');
 }finally{if(browser)await browser.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
