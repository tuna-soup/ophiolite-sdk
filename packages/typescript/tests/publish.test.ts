import test from "node:test";
import assert from "node:assert/strict";
import { Client, ShareOutcomeUnknown, VerificationFailed } from "../src/client.js";
import { adapt, run, result } from "../src/api-types.js";
import * as operations from "../src/generated/operations.js";
import { decode, fixture, server } from "./helpers.js";

const operationMap = operations as unknown as Record<string,(client:Client,input:unknown)=>Promise<unknown>>;
test("every application/upload override consumes its actual gateway recording over HTTP",async()=>{
  const coverage=JSON.parse(await (await import("node:fs/promises")).readFile(new URL("../../operation-coverage.json",import.meta.url),"utf8"));
  const rows=[...(await fixture("recordings/applications-workflow.json")).exchanges,...(await fixture("recordings/las-uploads-workflow.json")).exchanges];
  let calls=0;
  const app=await server((req,res)=>{
    const row=rows.find((r:any)=>r.path===req.url);assert(row);calls++;
    if(req.url?.endsWith("/upload")){ assert.equal(req.headers["content-type"],"application/octet-stream");assert(typeof req.headers["x-ophiolite-upload"]==="string"); }
    res.writeHead(200,{"Content-Type":"application/json"});res.end(JSON.stringify(row.response));
  });
  try{
    const client=new Client(app.url,{mode:"none"});
    for(const entry of coverage.filter((e:any)=>e.response==="tested-override")){
      const path=entry.operation.split(" ")[1].replace("{project}","p");const row=rows.find((r:any)=>r.path===path);assert(row);
      const binary=path.endsWith("/upload");
      const body=binary?decode(row.request_base64):JSON.parse(new TextDecoder().decode(decode(row.request_base64)));
      const got=await operationMap[entry.function](client,{path:{project:"p"},body,options:binary?{upload:{project_id:"p",command_id:"fixture",filename:"input.las",name:"Recording input",attribution:"Synthetic",audience:["alice","bob"],rights_confirmed:true}}:undefined});
      assert.deepEqual(got,adapt(entry.override.adapter,row.response));
    }
    assert.equal(calls,10);
  }finally{await app.close();}
});

test("restricted runs and results remove hidden parent identity even if extra fields leak into the response",async()=>{
  const rows=(await fixture("recordings/applications-workflow.json")).exchanges;
  const owned=rows.find((r:any)=>r.path.endsWith("/publish")).response;
  const restricted=run({...owned,input:null,parent_visibility:"restricted",binding:{...owned.binding,name:"Shared",curve:"GR"}});
  assert.equal(restricted.visibility,"restricted"); assert(!("input_sha256" in restricted));assert(!("parameters" in restricted));assert(!("id" in restricted.binding));assert(!("parent" in restricted.receipt!.manifest));assert(!("report" in restricted.receipt!.manifest));
  const summary=rows.find((r:any)=>r.path.endsWith("/share")).response;
  const reduced=result({...summary,input:null,parameters:{hidden:"parent"}});
  assert.equal(reduced.visibility,"restricted");assert(!("parameters" in reduced));assert(!("parent" in reduced.receipt.manifest));
  assert.equal(run(owned).visibility,"owned");assert.equal(result(summary).visibility,"owned");
});

test("share with lost reply has unknown outcome and exactly one call",async()=>{
  let calls=0;const app=await server((req,_res)=>{calls++;req.socket.destroy();});
  try {await assert.rejects(new Client(app.url,{mode:"none"}).request("POST","/api/v1/projects/{project}/applications/share",{project:"p"},undefined,{id:"r",audience:["bob"]}),ShareOutcomeUnknown);assert.equal(calls,1);}
  finally{await app.close();}
});

test("share malformed/truncated success also requires grants inspection",async()=>{
  for(const response of [()=>new Response("{"),()=>new Response(new ReadableStream({start(c){c.error(new Error("truncated"));}}))]){
    let calls=0;const client=new Client("https://example.invalid",{mode:"none"},async()=>{calls++;return response();});
    await assert.rejects(client.request("POST","/api/v1/projects/{project}/applications/share",{project:"p"},undefined,{}),ShareOutcomeUnknown);assert.equal(calls,1);
  }
});

test("upload enforces size, rights, project identity and required metadata before sending",async()=>{
  let calls=0;const client=new Client("https://example.invalid",{mode:"none"},async()=>{calls++;return new Response("{}");});
  const base={project_id:"p",command_id:"c",filename:"f",name:"n",attribution:"a",audience:[],rights_confirmed:true as const};
  for(const upload of [{...base,project_id:"wrong"},{...base,rights_confirmed:false},{...base,filename:""},{...base,well_notes:"x".repeat(1001)}])await assert.rejects(client.request("POST","/api/v1/projects/{project}/las-uploads/upload",{project:"p"},undefined,new Uint8Array([1]),{upload:upload as typeof base},"upload",true),VerificationFailed);
  for(const body of [new Uint8Array(),new Uint8Array(8*1024*1024+1)])await assert.rejects(client.request("POST","/api/v1/projects/{project}/las-uploads/upload",{project:"p"},undefined,body,{upload:base},"upload",true),VerificationFailed);
  assert.equal(calls,0);
});
