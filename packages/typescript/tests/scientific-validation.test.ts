import test from "node:test";
import assert from "node:assert/strict";
import { verifyPair, sha256 } from "../src/verify.js";
import { VerificationFailed } from "../src/errors.js";
import { fixture } from "./helpers.js";

test("scientific validation executes every independently required corpus ID with correct byte integrity",async()=>{
  const cases=(await fixture("fixtures/scientific-invalid.json")).cases;
  const required=(await fixture("fixtures/scientific-required.json")).required;
  const executed:string[]=[];
  for(const row of cases){
    const raw=new TextEncoder().encode(row.normalized_utf8);const rep=row.descriptor.representations.find((r:any)=>r.kind==="normalized");
    assert.equal(raw.length,rep.bytes);assert.equal(await sha256(raw),rep.sha256);
    await assert.rejects(verifyPair(row.descriptor,raw),VerificationFailed);executed.push(row.id);
  }
  assert.equal(new Set(executed).size,executed.length);
  assert.deepEqual(executed.sort(),Object.values(required).sort());
  assert.equal(executed.length,47);
});
