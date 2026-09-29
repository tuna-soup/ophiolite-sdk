import {spawn} from 'node:child_process';
import assert from 'node:assert/strict';
import {chromium} from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
const base='http://127.0.0.1:56110',backend='http://127.0.0.1:56111';
for(const url of [base,backend]){let occupied=false;try{await fetch(url,{signal:AbortSignal.timeout(500)});occupied=true;}catch{}if(occupied)throw Error('Template port already occupied: '+url);}
const child=spawn(process.execPath,['tools/dev.mjs'],{env:process.env,detached:true,stdio:['ignore','pipe','pipe']});let log='';child.stdout.on('data',x=>log+=x);child.stderr.on('data',x=>log+=x);
let browser;
try{
 for(let i=0;i<80;i++){try{const r=await fetch(base+'/api/wells');if(r.status===405)break;}catch{}if(i===79)throw Error('Template did not start: '+log);await new Promise(r=>setTimeout(r,150));}
 browser=await chromium.launch(process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:{});
 const context=await browser.newContext(),page=await context.newPage();
 const requests=[],responses=[],errors=[];
 page.on('pageerror',error=>errors.push(error.message));
 page.on('request',request=>requests.push(request));
 page.on('response',response=>{if(response.url().includes('/api/'))responses.push(response);});
 await page.goto(base);await page.getByRole('status').filter({hasText:'wells you may read are located'}).waitFor();
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
   const r=await context.request.post(origin+'/api/wells',{headers,data:{}});assert.equal(r.status(),403);
  }
  const preflight=await context.request.fetch(origin+'/api/bootstrap',{method:'OPTIONS',headers:{Origin:'http://foreign.invalid','Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'X-Ophiolite-Bootstrap'}});assert.equal(preflight.status(),403);assert(!preflight.headers()['access-control-allow-origin']);
  assert.equal((await context.request.get(origin+'/api/wells')).status(),405);
 }
 const list=page.getByRole('region',{name:'Wells',exact:true});
 for(const name of ['Synthetic well 1','Synthetic well 2','Synthetic well 3'])await list.getByRole('button',{name,exact:true}).waitFor();
 assert((await list.innerText()).includes('no location you may read'));
 await list.getByRole('button',{name:'Synthetic well 1',exact:true}).click();
 const details=page.getByRole('article',{name:'Synthetic well 1'});await details.waitFor();
 let visible=await page.locator('main').innerText();assert(!/well-synthetic-1|wells-table/.test(visible),'identifiers visible outside Technical details');
 await details.getByText('Technical details',{exact:true}).click();visible=await details.innerText();assert(visible.includes('well-synthetic-1')&&visible.includes('wells-table'));
 const after=await page.evaluate(async()=>{const {request}=await import('/src/helpers.mjs');return request('_test');});assert.deepEqual(after.mutations,{});
 await page.evaluate(async()=>{const {request}=await import('/src/helpers.mjs');await request('_test',{fault:'expired'});});
 await page.getByRole('button',{name:'Retry',exact:true}).click();await page.getByRole('status').filter({hasText:'ophiolite login'}).waitFor();
 await page.evaluate(async()=>{const {request}=await import('/src/helpers.mjs');await request('_test',{clear:true});});
 for(const request of requests){assert(request.url().startsWith(base+'/')||request.url().startsWith('blob:'+base+'/')||request.url().startsWith('data:'),'Browser contacted gateway or external origin: '+request.url());const headers=await request.allHeaders();assert(!headers.authorization);assert(!headers.cookie);}
 for(const response of responses){const body=await response.text();assert(!/access_token|refresh_token|oph_api_/.test(body));}
 const bootstrapRequest=requests.find(r=>r.url().endsWith('/api/bootstrap'));assert(bootstrapRequest);assert.equal((await bootstrapRequest.allHeaders())['sec-fetch-site'],'same-origin');assert.equal((await bootstrapRequest.allHeaders()).origin,base);
 const accessibility=await new AxeBuilder({page}).analyze();assert.deepEqual(accessibility.violations.map(v=>({id:v.id,impact:v.impact})),[]);assert.deepEqual(errors,[]);
 console.log(JSON.stringify({result:'PASS',browserRequests:requests.length,apiResponses:responses.length,negativeChecks:24,mutations:0,axeViolations:0,scope:'Synthetic fixture; actual browser and Vite proxy; no tile service; no external identity-provider claim'}));
}finally{
 if(browser)await browser.close();try{process.kill(-child.pid,'SIGTERM');}catch{}
 await new Promise(resolve=>{if(child.exitCode!==null)return resolve();child.once('exit',resolve);setTimeout(resolve,3000);});
}
