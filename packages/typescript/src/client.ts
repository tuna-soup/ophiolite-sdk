import { adapt, type UploadMetadata } from "./api-types.js";
import { CapacityExceeded, Refused, ShareOutcomeUnknown, VerificationFailed, httpError } from "./errors.js";
import { object, requireValue, validateDescriptor, verifyPair } from "./verify.js";
import { postProjectsProjectResultsDependents, postProjectsProjectResultsRemakeRun, postProjectsProjectResultsRemakeSave, postProjectsProjectResultsStory, postProjectsProjectResultsWhatChanged } from "./generated/operations.js";
import type { postProjectsProjectResultsRemakeSaveInput } from "./generated/operations.js";
export * from "./errors.js";
export * from "./api-types.js";
export { verifyPair, validateDescriptor } from "./verify.js";

export type Auth = { mode: "session"; csrf: () => string | Promise<string> } | { mode: "bearer"; token: () => Promise<{ token: string; grant?: string }> } | { mode: "none" };
export type OperationOptions = { signal?: AbortSignal; upload?: UploadMetadata; traceparent?: string };
/** E93: what this package reports on every request (product and version only; never a host name or user text). */
export const CLIENT_HEADER = "ophiolite-typescript/0.1.0";
const TRACEPARENT = /^00-(?!0{32})[0-9a-f]{32}-(?!0{16})[0-9a-f]{16}-[0-9a-f]{2}$/;
export interface Transport {
  request<T>(method: string, path: string, params: Record<string, unknown>, query?: Record<string, unknown>, body?: unknown, options?: OperationOptions, adapter?: string | null, binary?: boolean): Promise<T>;
}
const MAX_BYTES = 32 * 1024 * 1024;
/** E94: the revision manifest profiles this package reads (/3 carries how a result was made). */
export const PROFILES = "/1,/2,/3";
function uploadHeader(value: UploadMetadata): string {
  const v = object(value);
  for (const [name, limit] of Object.entries({project_id:160,command_id:64,filename:160,name:160,attribution:500})) {
    requireValue(typeof v[name] === "string" && (v[name] as string).length > 0 && (v[name] as string).length <= limit);
  }
  requireValue(v.rights_confirmed === true && Array.isArray(v.audience) && v.audience.length <= 100 && v.audience.every(x => typeof x === "string"));
  requireValue(v.well_notes === undefined || (typeof v.well_notes === "string" && v.well_notes.length <= 1000));
  const bytes = new TextEncoder().encode(JSON.stringify(value));
  return btoa(Array.from(bytes, x => String.fromCharCode(x)).join(""));
}
export class Client implements Transport {
  readonly url: URL;
  constructor(baseURL: string, private readonly auth: Auth, private readonly fetcher: typeof fetch = globalThis.fetch.bind(globalThis)) {
    this.url = new URL(baseURL);
    const loopback = ["localhost", "127.0.0.1", "[::1]"].includes(this.url.hostname);
    if (!(this.url.protocol === "https:" || (this.url.protocol === "http:" && loopback)) || this.url.username || this.url.password || this.url.search || this.url.hash) throw new Refused();
    if (this.url.pathname !== "/") throw new Refused();
  }
  private async send(method: string, path: string, params: Record<string, unknown>, query: Record<string, unknown> | undefined, body: unknown, options: OperationOptions | undefined, binary: boolean): Promise<Uint8Array> {
    requireValue(path.startsWith("/api/v1/") && !path.includes("?") && !path.includes("#") && !path.includes(".."));
    const route = path.replace(/\{([^}]+)\}/g, (_, name: string) => {
      const value = params[name]; requireValue(typeof value === "string" && value.length > 0 && value !== "." && value !== ".."); return encodeURIComponent(value);
    });
    const url = new URL(route, this.url);
    for (const [key, value] of Object.entries(query ?? {})) if (value !== undefined && value !== null) url.searchParams.set(key, String(value));
    const headers = new Headers({ Accept: "application/json", "X-Ophiolite-Client": CLIENT_HEADER });
    if (options?.traceparent !== undefined && TRACEPARENT.test(options.traceparent)) headers.set("traceparent", options.traceparent);  // the caller's trace; never invented
    if (this.auth.mode === "session") headers.set("X-CSRF-Token", await this.auth.csrf());
    if (this.auth.mode === "bearer") {
      const credential = await this.auth.token();
      requireValue(typeof credential.token === "string" && credential.token.length > 0);
      headers.set("Authorization", "Bearer " + credential.token);
      if (credential.grant !== undefined) headers.set("X-Ophiolite-Application-Grant", credential.grant);
    }
    let payload: BodyInit | undefined;
    if (binary) {
      requireValue(body instanceof Uint8Array && body.length > 0 && body.length <= 8 * 1024 * 1024);
      requireValue(options?.upload && options.upload.project_id === params.project);
      headers.set("Content-Type", "application/octet-stream"); headers.set("X-Ophiolite-Upload", uploadHeader(options.upload));
      payload = new Uint8Array(body).buffer;
    } else if (body !== undefined) { headers.set("Content-Type", "application/json"); payload = JSON.stringify(body); }
    const share = /\/(applications|las-uploads)\/share$/.test(path);
    // Deliberately one attempt. In particular, an uncertain share is never retried.
    let response: Response;
    try { response = await this.fetcher(url, { method, headers, body: payload, redirect: "manual", credentials: this.auth.mode === "session" ? "include" : "omit", signal: options?.signal }); }
    catch (error) { if (share) throw new ShareOutcomeUnknown(); throw error; }
    if (response.type === "opaqueredirect" || (response.status >= 300 && response.status < 400)) throw new Refused(response.status);
    if (!response.ok) throw httpError(response.status);
    if (Number(response.headers.get("Content-Length")) > MAX_BYTES) { await response.body?.cancel(); throw new CapacityExceeded(); }
    const reader = response.body?.getReader(); if (!reader) return new Uint8Array();
    const chunks: Uint8Array[] = []; let size = 0;
    try {
      while (true) {
        const next = await reader.read(); if (next.done) break;
        size += next.value.length; if (size > MAX_BYTES) { await reader.cancel(); throw new CapacityExceeded(); }
        chunks.push(next.value);
      }
    } catch (error) { if (share) throw new ShareOutcomeUnknown(); throw error; }
    finally { reader.releaseLock(); }
    const bytes = new Uint8Array(size); let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
    return bytes;
  }
  async request<T>(method: string, path: string, params: Record<string, unknown>, query?: Record<string, unknown>, body?: unknown, options?: OperationOptions, adapter: string | null = null, binary = false): Promise<T> {
    const bytes = await this.send(method, path, params, query, body, options, binary);
    try {
      const value = bytes.length ? JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) : null;
      return adapt(adapter, value) as T;
    } catch (error) {
      if (/\/(applications|las-uploads)\/share$/.test(path)) throw new ShareOutcomeUnknown();
      if (error instanceof VerificationFailed) throw error;
      throw new VerificationFailed("The service response is not valid JSON for this operation.");
    }
  }
  async readCurve(project: string, asset: string, revision: string, curve: string, options?: OperationOptions) {
    const path = "/api/v1/projects/{project}/scientific-assets/{asset}/revisions/{revision}";
    const params = { project, asset, revision };
    const descriptor = validateDescriptor(await this.request<unknown>("GET", path, params, { curve, profiles: PROFILES }, undefined, options));
    requireValue(descriptor.project_id === project && descriptor.asset_id === asset && descriptor.revision === revision && (descriptor.scientific as { curve?: string }).curve === curve);
    const rep = descriptor.representations.find(x => x.kind === "normalized")!;
    const bytes = await this.send("GET", path + "/representations/{representation}", { ...params, representation: rep.id }, { curve }, undefined, options, false);
    return verifyPair(descriptor, bytes);
  }
}

/** E94: one page of how an exact result version was made (follow `next_cursor`; `continue_from` when a history is long). */
export function story(transport: Transport, project: string, asset: string, revision: string, page: { cursor?: string; limit?: number } = {}, options?: OperationOptions): ReturnType<typeof postProjectsProjectResultsStory> {
  return postProjectsProjectResultsStory(transport, { path: { project }, body: { project_id: project, asset_id: asset, revision, ...page }, options });
}
/** E94: what differs in how two exact result versions were made; `a` is the earlier one. */
export function whatChanged(transport: Transport, project: string, a: { asset_id: string; revision: string }, b: { asset_id: string; revision: string }, options?: OperationOptions): ReturnType<typeof postProjectsProjectResultsWhatChanged> {
  return postProjectsProjectResultsWhatChanged(transport, { path: { project }, body: { project_id: project, a, b }, options });
}
/** E94: the results made from an exact version the reader may open. */
export function dependents(transport: Transport, project: string, asset: string, revision: string, page: { cursor?: string; limit?: number } = {}, options?: OperationOptions): ReturnType<typeof postProjectsProjectResultsDependents> {
  return postProjectsProjectResultsDependents(transport, { path: { project }, body: { project_id: project, asset_id: asset, revision, ...page }, options });
}
export type RemakeStep = { step: "preview"; inputs?: "recorded" | "newer" } | { step: "run"; inputs: { slot: string; asset_id: string; revision: string }[]; command_id: string } | { step: "status" | "discard"; execution_id: string };
/** E94: make an exact result version again (preview, run, status, discard). Nothing is saved; `remakeSave` does that. */
export function remake(transport: Transport, project: string, asset: string, revision: string, step: RemakeStep, options?: OperationOptions): ReturnType<typeof postProjectsProjectResultsRemakeRun> {
  if (step.step === "run" && !step.command_id) throw new Refused();
  return postProjectsProjectResultsRemakeRun(transport, { path: { project }, body: { project_id: project, asset_id: asset, revision, ...step }, options });
}
/** E94: save held outputs that differ, each on its own command id; a new version carries the confirmed audience digest. */
export function remakeSave(transport: Transport, project: string, execution_id: string, outputs: postProjectsProjectResultsRemakeSaveInput["body"]["outputs"], options?: OperationOptions): ReturnType<typeof postProjectsProjectResultsRemakeSave> {
  requireValue(outputs.length > 0 && outputs.every(o => (o.target === "new-result" || o.target === "new-version") && !!o.command_id));
  return postProjectsProjectResultsRemakeSave(transport, { path: { project }, body: { project_id: project, execution_id, outputs }, options });
}
