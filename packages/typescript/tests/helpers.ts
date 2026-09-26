import { readFile } from "node:fs/promises";
import { createServer, type Incoming, type Outgoing } from "node:http";
export async function fixture(name: string): Promise<any> {
  return JSON.parse(await readFile(new URL("../../../../tests/" + name, import.meta.url), "utf8"));
}
export function decode(value: string): Uint8Array<ArrayBuffer> { return Uint8Array.from(atob(value), x => x.charCodeAt(0)); }
export async function server(handler: (request: Incoming, response: Outgoing) => void) {
  const instance = createServer(handler); await new Promise<void>(resolve => instance.listen(0, "127.0.0.1", resolve));
  const address = instance.address(); if (!address || typeof address === "string") throw new Error("No server address");
  return { url: `http://127.0.0.1:${address.port}`, close: async () => { instance.closeAllConnections(); await new Promise<void>((resolve,reject) => instance.close(error => error ? reject(error) : resolve())); } };
}
