import test from "node:test";
import assert from "node:assert/strict";
import { Client, VerificationFailed, Refused, AuthenticationRequired, PermissionRefused, IntegrityConflict, CapacityExceeded, Busy, Unavailable } from "../src/client.js";
import { decode, fixture, server } from "./helpers.js";

test("exact scientific read validates and preserves every coordinate and null", async () => {
  const rows = await fixture("recordings/synthetic-read.json");
  const descriptor = JSON.parse(new TextDecoder().decode(decode(rows[1].body_base64)));
  const normalized = JSON.parse(new TextDecoder().decode(decode(rows[3].body_base64)));
  let calls = 0, corrupt = false;
  const app = await server((req,res) => {
    calls++; const row = rows.find((r: any) => r.path === req.url);
    assert(row); assert.equal(req.headers["authorization"], undefined); assert.equal(req.headers["x-csrf-token"], "test-csrf");
    let bytes = decode(row.body_base64); if (corrupt && req.url?.includes("/representations/")) bytes = bytes.slice(1);
    res.writeHead(row.status,{"Content-Type":"application/json"}); res.end(bytes);
  });
  try {
    const client = new Client(app.url, { mode:"session",csrf:()=>"test-csrf" });
    const result = await client.readCurve("p",descriptor.asset_id,descriptor.revision,"GR");
    assert.deepEqual(result.curve.axis, normalized.axis); assert.deepEqual(result.curve.values, normalized.values);
    assert.deepEqual(result.descriptor, descriptor); assert.equal(calls,2);
    corrupt = true; await assert.rejects(client.readCurve("p",descriptor.asset_id,descriptor.revision,"GR"),VerificationFailed);
  } finally { await app.close(); }
});

test("bearer supplier is per request; cookie omission and manual redirect are enforced", async () => {
  let supplied = 0, calls = 0;
  const app = await server((req,res) => {
    calls++; assert.equal(req.headers.authorization,"Bearer supplied-"+calls); assert.equal(req.headers["x-ophiolite-application-grant"],"grant"); assert.equal(req.headers.cookie,undefined); assert.equal(req.headers["x-csrf-token"],undefined);
    res.writeHead(200,{"Content-Type":"application/json"});res.end("{}");
  });
  try {
    const observed: RequestInit[] = [];
    const client = new Client(app.url,{mode:"bearer",token:async()=>({token:"supplied-"+(++supplied),grant:"grant"})},async (url,init)=>{observed.push(init!);return fetch(url,init);});
    await client.request("POST","/api/v1/projects/{project}/applications/list",{project:"p"},undefined,{});
    await client.request("POST","/api/v1/projects/{project}/applications/list",{project:"p"},undefined,{});
    assert.equal(supplied,2); assert.equal(calls,2); assert(observed.every(i=>i.credentials==="omit" && i.redirect==="manual"));
  } finally { await app.close(); }
});

test("session and no-auth modes keep their credential boundaries",async()=>{
  for (const mode of ["session","none"] as const) {
    const client=new Client("https://example.invalid",mode==="session"?{mode,csrf:()=>"csrf"}:{mode},async(_url,init)=>{
      assert.equal(init?.credentials,mode==="session"?"include":"omit");
      const h=new Headers(init?.headers);assert.equal(h.get("Authorization"),null);assert.equal(h.get("X-CSRF-Token"),mode==="session"?"csrf":null);
      return new Response("{}");
    }); await client.request("GET","/api/v1/contracts",{});
  }
});

test("redirects never follow to a second server",async()=>{
  let targetCalls=0; const target=await server((_req,res)=>{targetCalls++;res.end("{}");});
  const origin=await server((_req,res)=>{res.writeHead(302,{Location:target.url+"/stolen"});res.end();});
  try { await assert.rejects(new Client(origin.url,{mode:"none"}).request("GET","/api/v1/contracts",{}),Refused);assert.equal(targetCalls,0); }
  finally{await origin.close();await target.close();}
});

for (const [status, kind] of [[401,AuthenticationRequired],[403,PermissionRefused],[409,IntegrityConflict],[413,CapacityExceeded],[429,Busy],[503,Busy],[404,Unavailable],[400,Refused]] as const) {
  test(`HTTP ${status} maps to safe SDK error`,async()=>{
    const client=new Client("https://example.invalid",{mode:"none"},async()=>new Response("private server diagnostic",{status}));
    await assert.rejects(client.request("GET","/api/v1/contracts",{}),kind);
  });
}

test("descriptor must match the explicitly requested revision and curve",async()=>{
  const rows=await fixture("recordings/synthetic-read.json"); const descriptor=JSON.parse(new TextDecoder().decode(decode(rows[1].body_base64)));
  for(const overrides of [{project_id:"other"},{asset_id:"other"},{revision:"other"},{scientific:{...descriptor.scientific,curve:"other"}}]) {
    const client=new Client("https://example.invalid",{mode:"none"},async()=>new Response(JSON.stringify({...descriptor,...overrides})));
    await assert.rejects(client.readCurve("p",descriptor.asset_id,descriptor.revision,"GR"),VerificationFailed);
  }
});

test("unsafe service URLs and relative path escapes refuse before sending",async()=>{
  for(const url of ["http://example.com","https://user:password@example.com","https://example.com/?secret=1","https://example.com/base","file:///tmp/foo"])assert.throws(()=>new Client(url,{mode:"none"}),Refused);
  const client=new Client("https://example.invalid",{mode:"none"},async()=>{throw new Error("must not send");});
  await assert.rejects(client.request("GET","/api/v1/projects/{project}",{project:".."}),VerificationFailed);
});

test("exact revision identity refusal precedes fetching a valid foreign representation",async()=>{
  const rows=await fixture("recordings/synthetic-read.json");const descriptor=JSON.parse(new TextDecoder().decode(decode(rows[1].body_base64)));
  for(const args of [["other",descriptor.asset_id,descriptor.revision,"GR"],["p","other",descriptor.revision,"GR"],["p",descriptor.asset_id,"other","GR"],["p",descriptor.asset_id,descriptor.revision,"OTHER"]]){
    let calls=0;const client=new Client("https://example.invalid",{mode:"none"},async()=>{calls++;return new Response(decode(rows[calls===1?1:3].body_base64));});
    await assert.rejects(client.readCurve(args[0],args[1],args[2],args[3]),VerificationFailed);assert.equal(calls,1);
  }
});

test("route and empty token guards refuse before transport",async()=>{
  let calls=0;const transport:typeof fetch=async()=>{calls++;return new Response("{}");};
  const noauth=new Client("https://example.invalid",{mode:"none"},transport);
  for(const path of ["https://other.invalid/api/v1/contracts","/session","/api/v1/contracts?token=leak","/api/v1/contracts#fragment","/api/v1/../session"])await assert.rejects(noauth.request("GET",path,{}),VerificationFailed);
  const bearer=new Client("https://example.invalid",{mode:"bearer",token:async()=>({token:""})},transport);
  await assert.rejects(bearer.request("GET","/api/v1/contracts",{}),VerificationFailed);assert.equal(calls,0);
});

test("same-length valid JSON with different sample values fails its original digest",async()=>{
  const rows=await fixture("recordings/synthetic-read.json");const descriptor=JSON.parse(new TextDecoder().decode(decode(rows[1].body_base64)));
  const bytes=decode(rows[3].body_base64);const text=new TextDecoder().decode(bytes);const changed=text.replace('30.0','31.0');assert(changed!==text);assert.equal(changed.length,text.length);
  let calls=0;const client=new Client("https://example.invalid",{mode:"none"},async()=>new Response(++calls===1?decode(rows[1].body_base64):changed));
  await assert.rejects(client.readCurve("p",descriptor.asset_id,descriptor.revision,"GR"),VerificationFailed);
});

test("default fetch retains its host receiver in browsers",async()=>{
  const original=globalThis.fetch;
  try {
    globalThis.fetch=async function(this:unknown){assert.equal(this,globalThis);return new Response("{}");};
    const client=new Client("https://example.invalid",{mode:"none"});await client.request("GET","/api/v1/contracts",{});
  }finally{globalThis.fetch=original;}
});
