import type { Run, Result } from "../src/api-types.js";
export function narrowing(run:Run,result:Result):void {
  if(run.visibility==="restricted") {
    // @ts-expect-error restricted runs never expose input hashes
    run.input_sha256;
    // @ts-expect-error restricted receipts never expose parents
    run.receipt.manifest.parent;
    // @ts-expect-error restricted binding contains no ID
    run.binding.id;
  } else { const hash:string=run.input_sha256;const authority:string=run.input.authority;void hash;void authority; }
  if(result.visibility==="restricted") {
    // @ts-expect-error restricted result has no source reference
    result.input.authority;
    // @ts-expect-error restricted result manifest omits report
    result.receipt.manifest.report;
  }
}
