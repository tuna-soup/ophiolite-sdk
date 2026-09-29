import test from 'node:test';
import assert from 'node:assert/strict';
import {bootstrap,request,popup,bounds} from '../src/helpers.mjs';
test('the popup shows the name; identifiers only under technical details',()=>{
 const shown=popup({name:'W1',entity_id:'well-1',source_asset_id:'table',source_revision:'r1',source_row:'7'});
 assert.equal(shown.name,'W1');assert.deepEqual(shown.technical.map(([label])=>label),['Well','Source','Revision','Row']);
 assert.equal(popup({entity_id:'well-2'}).name,'Unnamed well');assert.deepEqual(popup({name:'W3'}).technical,[]);
});
test('the extent becomes map bounds, none when nothing is located',()=>{assert.deepEqual(bounds([1,2,3,4]),[[1,2],[3,4]]);assert.equal(bounds(null),null);});
test('bootstrap and all API actions are POST with in-memory explicit proof',async()=>{
 const original=globalThis.fetch;const calls=[];
 globalThis.fetch=async(path,options)=>{calls.push({path,options});return new Response(JSON.stringify(path.endsWith('bootstrap')?{proof:'test-proof'}:{ok:true}));};
 try{await bootstrap();await request('wells');assert.equal(calls.length,2);assert.equal(calls[0].options.method,'POST');assert.equal(calls[0].options.headers['X-Ophiolite-Bootstrap'],'1');assert.equal(calls[1].options.method,'POST');assert.equal(calls[1].options.headers['X-Ophiolite-Proof'],'test-proof');assert(!JSON.stringify(calls).includes('Authorization'));}finally{globalThis.fetch=original;}
});
test('refusals carry the backend message and do not retry',async()=>{
 const original=globalThis.fetch;let calls=0;globalThis.fetch=async()=>{calls++;return new Response(JSON.stringify({message:'Sign in again'}),{status:401});};
 try{await assert.rejects(request('wells'),error=>error.message==='Sign in again');assert.equal(calls,1);}finally{globalThis.fetch=original;}
});
