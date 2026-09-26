import {spawn} from 'node:child_process';
import assert from 'node:assert/strict';
import {chromium} from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
const base='http://127.0.0.1:56110',backend='http://127.0.0.1:56111';
for(const url of [base,backend]){let occupied=false;try{await fetch(url,{signal:AbortSignal.timeout(500)});occupied=true;}catch{}if(occupied)throw Error('Template port already occupied: '+url);}
const child=spawn(process.execPath,['tools/dev.mjs'],{env:process.env,detached:true,stdio:['ignore','pipe','pipe']});let log='';child.stdout.on('data',x=>log+=x);child.stderr.on('data',x=>log+=x);
let browser;
try{
 for(let i=0;i<80;i++){try{const r=await fetch(base+'/api/list');if(r.status===405)break;}catch{}if(i===79)throw Error('Template did not start: '+log);await new Promise(r=>setTimeout(r,150));}
 browser=await chromium.launch(process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:{});
 const context=await browser.newContext(),page=await context.newPage();
 const requests=[],responses=[],errors=[];
 page.on('pageerror',error=>errors.push(error.message));
 page.on('request',request=>requests.push(request));
 page.on('response',response=>{if(response.url().includes('/api/'))responses.push(response);});
 await page.goto(base);await page.getByRole('status').filter({hasText:'Select a permitted curve'}).waitFor();
 const proof=await page.evaluate(async()=>{const r=await fetch('/api/bootstrap',{method:'POST',headers:{'X-Ophiolite-Bootstrap':'1'}});return (await r.json()).proof;});
 // Same negative cases against Vite and directly against its Python backend.
 for(const origin of [base,backend]){
  for(const headers of [
   {'Origin':'http://foreign.invalid','Sec-Fetch-Site':'same-origin','X-Ophiolite-Bootstrap':'1'},
   {'Origin':'null','Sec-Fetch-Site':'same-origin','X-Ophiolite-Bootstrap':'1'},
   {'Sec-Fetch-Site':'same-origin','X-Ophiolite-Bootstrap':'1'},
   {'Origin':base,'Host':'foreign.invalid','Sec-Fetch-Site':'same-origin','X-Ophiolite-Bootstrap':'1'}]){
    const r=await context.request.post(origin+'/api/bootstrap',{headers});assert.equal(r.status(),403);assert(!r.headers()['access-control-allow-origin']);assert(!(await r.text()).includes(proof));
  }
  for(const headers of [{'Origin':'http://foreign.invalid','X-Ophiolite-Proof':proof},{'Origin':'null','X-Ophiolite-Proof':proof},{'X-Ophiolite-Proof':proof},{'Origin':base},{'Origin':base,'X-Ophiolite-Proof':'wrong'},{'Origin':base,'Host':'foreign.invalid','X-Ophiolite-Proof':proof}]){
   const r=await context.request.post(origin+'/api/stage',{headers,data:{}});assert.equal(r.status(),403);
  }
  const preflight=await context.request.fetch(origin+'/api/bootstrap',{method:'OPTIONS',headers:{Origin:'http://foreign.invalid','Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'X-Ophiolite-Bootstrap'}});assert.equal(preflight.status(),403);assert(!preflight.headers()['access-control-allow-origin']);
  assert.equal((await context.request.get(origin+'/api/list')).status(),405);
 }
 const before=await page.evaluate(async()=>{const {request}=await import('/src/helpers.mjs');return request('_test');});assert.deepEqual(before.mutations,{});
 await page.getByRole('button',{name:'Read curve',exact:true}).click();await page.getByRole('status').filter({hasText:'Exact source version loaded'}).waitFor();
 let visible=await page.locator('main').innerText();assert(!/las2\/1|curve-a|synthetic-file|source-reference|asset_connectors\.las_reader\/1|\bincreasing\b|\bsource-declared\b|[0-9a-f]{64}/.test(visible));assert(visible.includes('gAPI')&&visible.includes('Samples')&&visible.includes('Missing'));
 const sourceLink=page.getByRole('link',{name:'Open this exact version in Workspace'});assert((await sourceLink.getAttribute('href')).includes('kind=scientific'));
 await page.getByText('Technical details',{exact:true}).click();assert((await page.locator('main').innerText()).includes('las2/1'));await page.getByText('Technical details',{exact:true}).click();
 await page.getByLabel('New curve name').fill('bad');await page.getByRole('button',{name:'Stage calculation',exact:true}).click();await page.getByRole('button',{name:'Validate',exact:true}).click();await page.getByRole('list',{name:'Corrections needed'}).waitFor();assert(await page.getByRole('button',{name:'Publish derived curve',exact:true}).isDisabled());
 await page.getByLabel('New curve name').fill('CALC');await page.getByRole('button',{name:'Validate',exact:true}).click();await page.getByRole('status').filter({hasText:'satisfies'}).waitFor();
 await page.getByRole('button',{name:'Publish derived curve',exact:true}).click();await page.getByRole('heading',{name:'Derived result saved'}).waitFor();assert((await page.getByRole('link',{name:'Open this result in Workspace'}).getAttribute('href')).includes('revision='));
 await page.evaluate(async()=>{const {request}=await import('/src/helpers.mjs');await request('_test',{drop_share:true});});
 await page.getByLabel('Recipients (comma separated)').fill('alice,bob');await page.getByRole('button',{name:'Share result',exact:true}).click();await page.getByRole('status').filter({hasText:'Read recipients first'}).waitFor();
 const after=await page.evaluate(async()=>{const {request}=await import('/src/helpers.mjs');return request('_test');});assert.equal(after.mutations.share,1);assert.equal(after.mutations.publish,1);
 for(const [fault,text] of [['expired','ophiolite login'],['busy','service is busy']]){
  await page.evaluate(async fault=>{const {request}=await import('/src/helpers.mjs');await request('_test',{fault});},fault);await page.getByRole('button',{name:'Retry',exact:true}).click();await page.getByRole('status').filter({hasText:text}).waitFor();
  await page.evaluate(async()=>{const {request}=await import('/src/helpers.mjs');await request('_test',{clear:true});});
 }
 for(const request of requests){assert(request.url().startsWith(base+'/'),'Browser contacted gateway or external origin');const headers=await request.allHeaders();assert(!headers.authorization);assert(!headers.cookie);}
 for(const response of responses){const body=await response.text();assert(!/access_token|refresh_token|oph_api_/.test(body));}
 const bootstrapRequest=requests.find(r=>r.url().endsWith('/api/bootstrap'));assert(bootstrapRequest);assert.equal((await bootstrapRequest.allHeaders())['sec-fetch-site'],'same-origin');assert.equal((await bootstrapRequest.allHeaders()).origin,base);
 const accessibility=await new AxeBuilder({page}).analyze();assert.deepEqual(accessibility.violations.map(v=>({id:v.id,impact:v.impact})),[]);assert.deepEqual(errors,[]);
 console.log(JSON.stringify({result:'PASS',browserRequests:requests.length,apiResponses:responses.length,negativeChecks:24,publicationCount:after.mutations.publish,shareCount:after.mutations.share,axeViolations:0,scope:'Synthetic fixture; actual browser and Vite proxy; no external identity-provider claim'}));
}finally{
 if(browser)await browser.close();try{process.kill(-child.pid,'SIGTERM');}catch{}
 await new Promise(resolve=>{if(child.exitCode!==null)return resolve();child.once('exit',resolve);setTimeout(resolve,3000);});
}
