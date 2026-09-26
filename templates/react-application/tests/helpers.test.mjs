import test from 'node:test';
import assert from 'node:assert/strict';
import {bootstrap,request,sample} from '../src/helpers.mjs';
test('missing samples are distinct from zero',()=>{assert.equal(sample(null),'Missing');assert.equal(sample(0),'0');});
test('bootstrap and all API actions are POST with in-memory explicit proof',async()=>{
 const original=globalThis.fetch;const calls=[];
 globalThis.fetch=async(path,options)=>{calls.push({path,options});return new Response(JSON.stringify(path.endsWith('bootstrap')?{proof:'test-proof'}:{ok:true}));};
 try{await bootstrap();await request('list');assert.equal(calls.length,2);assert.equal(calls[0].options.method,'POST');assert.equal(calls[0].options.headers['X-Ophiolite-Bootstrap'],'1');assert.equal(calls[1].options.method,'POST');assert.equal(calls[1].options.headers['X-Ophiolite-Proof'],'test-proof');assert(!JSON.stringify(calls).includes('Authorization'));}finally{globalThis.fetch=original;}
});
test('validation errors preserve bounded violation guidance and do not retry',async()=>{
 const original=globalThis.fetch;let calls=0;globalThis.fetch=async()=>{calls++;return new Response(JSON.stringify({message:'Correct values',violations:['Use a supported name.']}),{status:422});};
 try{await assert.rejects(request('validate'),error=>error.message==='Correct values'&&error.violations.length===1);assert.equal(calls,1);}finally{globalThis.fetch=original;}
});
