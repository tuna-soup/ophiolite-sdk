// Minimal test-only declarations. Published browser sources import no Node module.
declare module "node:test" { export default function test(name: string, callback: () => void | Promise<void>): void; }
declare module "node:assert/strict" {
  interface Assert { (value: unknown, message?: string): asserts value; equal(a: unknown,b: unknown,message?:string): void; deepEqual(a: unknown,b: unknown,message?:string):void; rejects(callback: (() => Promise<unknown>) | Promise<unknown>, error?: unknown):Promise<void>; throws(callback:()=>unknown,error?:unknown):void; }
  const assert: Assert; export default assert;
}
declare module "node:fs/promises" { export function readFile(path: URL | string, encoding: "utf8"): Promise<string>; export function readdir(path: URL | string, options?: {recursive: boolean}): Promise<string[]>; }
declare module "node:http" {
  export interface Incoming { method?:string;url?:string;headers:Record<string,string|string[]|undefined>; on(event: string, callback: (data: Uint8Array)=>void):void; socket:{destroy():void}; }
  export interface Outgoing { writeHead(status:number,headers?:Record<string,string>):void;end(body?:string|Uint8Array):void; }
  export function createServer(handler:(req:Incoming,res:Outgoing)=>void): { listen(port:number,host:string,callback:()=>void):void;address():{port:number}|string|null; close(callback:(error?:Error)=>void):void; closeAllConnections():void };
}
