import test from "node:test";
import assert from "node:assert/strict";
import { validateSchema, validateDescriptor, verifyPair, sha256 } from "../src/verify.js";
import { profiles } from "../src/generated/schemas.js";
import { adapt } from "../src/api-types.js";
import { Incompatible, VerificationFailed } from "../src/errors.js";
import { fixture, decode } from "./helpers.js";

test("schema interpreter refuses wrong types, bounds, missing fields and union disagreements",()=>{
  const cases:[unknown,unknown][]=[
    [true,{type:"number"}],[Infinity,{type:"number"}],[1.5,{type:"integer"}],[-1,{type:"number",minimum:0}],[2,{type:"number",maximum:1}],[0,{type:"number",exclusiveMinimum:0}],
    [1,{type:"string"}],["",{type:"string",minLength:1}],["long",{type:"string",maxLength:2}],["no",{type:"string",pattern:"^yes$"}],
    [1,{type:"boolean"}],[0,{type:"null"}],[null,{type:"object"}],[[],{type:"object"}],[{}, {type:"object",required:["x"],properties:{x:{type:"string"}}}],
    [{},{type:"array",items:{type:"number"}}],[[],{type:"array",minItems:1,items:{type:"number"}}],[[1,2],{type:"array",maxItems:1,items:{type:"number"}}],[[true],{type:"array",items:{type:"number"}}],
    ["wrong",{const:"right"}],["wrong",{enum:["right"]}],[true,{type:["null","number"]}],
    [true,{anyOf:[{type:"null"},{type:"number"}]}],[1,{oneOf:[{type:"number"},{type:"integer"}]}],
    [1,false],[1,{$ref:"https://remote.invalid/schema"}]
  ];
  for(const [value,schema] of cases)assert.throws(()=>validateSchema(value,schema),VerificationFailed);
  validateSchema({new_field:"tolerated"},{type:"object",additionalProperties:false});validateSchema(1,true);
});

test("valid derived descriptor and explicit reader differences retain truthful semantics",async()=>{
  const rows=await fixture("recordings/synthetic-read.json");
  const d=JSON.parse(new TextDecoder().decode(decode(rows[1].body_base64)));
  const c=JSON.parse(new TextDecoder().decode(decode(rows[3].body_base64)));
  d.parents=[d.source_reference];d.origin="managed-derived";d.authority="ophiolite:derived";d.source_reference=null;d.provenance={...d.provenance,evidence:"script-declared",method:"synthetic"};d.representations[0].kind="derived-artifact";
  c.source={authority:d.authority,key:d.asset_id,revision:d.revision,profile:d.profile};
  const raw=new TextEncoder().encode(JSON.stringify(c));d.representations[1].bytes=raw.length;d.representations[1].sha256=await sha256(raw);
  await verifyPair(d,raw);
  d.recorded_interpretation.lasio_version="older";d.interpretation_evidence="recorded-differs";await verifyPair(d,raw);
  d.recorded_interpretation.mapping="other/1";assert.throws(()=>validateDescriptor(d),Incompatible);
});

test("recorded response adapters validate every exposed declared field and never return wire extras",async()=>{
  const rows=[...(await fixture("recordings/applications-workflow.json")).exchanges,...(await fixture("recordings/las-uploads-workflow.json")).exchanges];
  const mapping:Record<string,string>={configure:"binding",start:"run",original:"original",read:"curve",publish:"run",download:"download",share:"result","result-list":"results",upload:"upload",info:"upload"};
  let checks=0;
  for(const row of rows){
    const name=mapping[row.path.split("/").pop()];const original=adapt(name,row.response) as Record<string,unknown>;
    for(const key of Object.keys(original)){
      if(key==="visibility" || key==="receipt" && original[key]===null)continue;
      const bad={...row.response,[key]:typeof original[key]==="object" && original[key]!==null && !Array.isArray(original[key]) ? 0 : {invalid:"type"}};
      assert.throws(()=>adapt(name,bad),VerificationFailed);checks++;
    }
  }
  assert(checks>=65);
  const binding=rows[0].response;
  for(const generation of [0,1.5])assert.throws(()=>adapt("binding",{...binding,generation}),VerificationFailed);
  assert.throws(()=>adapt("binding",{...binding,publication_profile:"other"}),VerificationFailed);
  const published=rows.find((r:any)=>r.path.endsWith("/publish")).response;
  for(const bytes of [-1,1.5,32*1024*1024+1])assert.throws(()=>adapt("run",{...published,receipt:{...published.receipt,manifest:{...published.receipt.manifest,bytes}}}),VerificationFailed);
  assert.throws(()=>adapt("run",{...published,input_sha256:"invalid"}),VerificationFailed);
  assert.throws(()=>adapt("run",{...published,parent_visibility:"restricted"}),VerificationFailed);
});

test("descriptor invariants refuse independently of the paired-curve facts",async()=>{
  const cases=(await fixture("fixtures/scientific-invalid.json")).cases;
  for(const id of ["nonfinite-marker","unit-status","axis-unit-status","missing-count","duplicate-order","insufficient-order","derived-revision"]){
    const row=cases.find((r:any)=>r.id===id);assert(row);assert.throws(()=>validateDescriptor(row.descriptor),VerificationFailed);
  }
  const rows=await fixture("recordings/synthetic-read.json");const d=JSON.parse(new TextDecoder().decode(decode(rows[1].body_base64)));
  d.supported_operations=["read","read","export"];assert.throws(()=>validateDescriptor(d),VerificationFailed);
  d.supported_operations=["read","export"];d.interpretation_evidence="recorded-differs";assert.throws(()=>validateDescriptor(d),VerificationFailed);
});


test("local profile declarations cannot silently change role, envelope support or normalized profile",async()=>{
  const rows=await fixture("recordings/synthetic-read.json");const d=JSON.parse(new TextDecoder().decode(decode(rows[1].body_base64)));
  const original=profiles[d.profile] as Record<string,unknown>;
  try{
    profiles[d.profile]={...original,role:"normalized"};assert.throws(()=>validateDescriptor(d),VerificationFailed);
    profiles[d.profile]={...original,serves:[]};assert.throws(()=>validateDescriptor(d),VerificationFailed);
    profiles[d.profile]=original;
    const normalized=d.representations.find((r:any)=>r.kind==="normalized");
    profiles["synthetic-alias/1"]={...(profiles[normalized.profile] as Record<string,unknown>)};
    normalized.profile="synthetic-alias/1";assert.throws(()=>validateDescriptor(d),VerificationFailed);
  }finally{profiles[d.profile]=original;delete profiles["synthetic-alias/1"];}
  assert.throws(()=>validateSchema(1,{$ref:"foreign/x"},{$defs:{x:{type:"number"}}}),VerificationFailed);
});
