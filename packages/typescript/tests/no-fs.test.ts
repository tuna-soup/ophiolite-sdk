import test from "node:test";
import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
test("distributed source imports no filesystem or other Node runtime module",async()=>{
  const root=new URL("../src/",import.meta.url);
  const files=(await readdir(root,{recursive:true})).filter(x=>x.endsWith(".js"));assert(files.length>=7);
  for(const file of files){const text=await readFile(new URL(file,root),"utf8");assert(!/(?:from\s*|import\s*\(|require\s*\()\s*["'](?:node:|fs["'/])/.test(text),file);}
});
test("compiled scientific corpus test is present and discovered",async()=>{
  const files=await readdir(new URL("./",import.meta.url));assert(files.includes("scientific-validation.test.js"));
  const source=await readFile(new URL("./scientific-validation.test.js",import.meta.url),"utf8");assert(source.includes('test("scientific validation executes'));
});
