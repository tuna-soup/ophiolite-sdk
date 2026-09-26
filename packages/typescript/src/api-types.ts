import type { Reference, ApplicationCurve } from "./generated/contracts.js";
import { object, requireValue, validateCurve } from "./verify.js";

export type Binding = { id: string; owner: string; project_id: string; kind: "binding"; name: string; generation: number; curve: string; publication_profile: "curve-edits/1" | "las-derived-curves/1" };
export type ResultManifest = { schema: string; media_type: string; bytes: number; sha256: string };
export type OwnerManifest = ResultManifest & { parent: Reference; report: Record<string, unknown> };
export type Receipt<M = OwnerManifest> = { destination: string; upstream_write: boolean; publication_id: string; identity: string; output_reference: { authority: string; key: string; revision: string }; manifest: M };
export type OwnedRun = { visibility: "owned"; id: string; owner: string; project_id: string; kind: "run"; binding: Binding; input: Reference; input_sha256: string; application_version: string; parameters: Record<string, unknown>; state: string; receipt: Receipt | null };
export type RestrictedRun = { visibility: "restricted"; id: string; owner: string; project_id: string; kind: "run"; binding: { name: string; curve: string }; input: null; parent_visibility: "restricted"; application_version: string; state: string; receipt: Receipt<ResultManifest> };
export type Run = OwnedRun | RestrictedRun;
export type ResultSummary = { visibility: "owned"; asset_id: string; revision: string; id: string; name: string; owner: string; input: Reference; curve: string; receipt: Receipt; can_share: boolean; recipients: string[]; reuse_recipients: string[]; published: number };
export type RestrictedResultSummary = Omit<ResultSummary, "visibility" | "input" | "receipt"> & { visibility: "restricted"; input: null; receipt: Receipt<ResultManifest> };
export type Result = ResultSummary | RestrictedResultSummary;
export type UploadResult = { asset_id: string; revision: string; name: string; can_share: boolean; acquisition: Record<string, unknown>; permitted_audience: string[]; recipients: string[]; reuse_recipients: string[] };
export type Original = { representation: string; source: Reference; sha256: string; payload_base64: string };
export type Download = Receipt & { payload_base64: string };
export type UploadMetadata = { project_id: string; command_id: string; filename: string; name: string; attribution: string; well_notes?: string; audience: string[]; rights_confirmed: true };

function text(value: unknown): string { requireValue(typeof value === "string"); return value; }
function number(value: unknown): number { requireValue(typeof value === "number" && Number.isFinite(value)); return value; }
function bool(value: unknown): boolean { requireValue(typeof value === "boolean"); return value; }
function strings(value: unknown): string[] { requireValue(Array.isArray(value)); return value.map(text); }
function hash(value: unknown): string { const h = text(value); requireValue(/^[0-9a-f]{64}$/.test(h)); return h; }
function reference(value: unknown): Reference {
  const v = object(value); return { authority: text(v.authority), key: text(v.key), revision: text(v.revision), profile: text(v.profile) };
}
export function binding(value: unknown): Binding {
  const v = object(value); requireValue(v.kind === "binding");
  const generation = number(v.generation); requireValue(Number.isInteger(generation) && generation >= 1);
  const profile = v.publication_profile ?? "curve-edits/1"; requireValue(profile === "curve-edits/1" || profile === "las-derived-curves/1");
  return { id: text(v.id), owner: text(v.owner), project_id: text(v.project_id), kind: "binding", name: text(v.name), generation, curve: text(v.curve), publication_profile: profile };
}
function manifest(value: unknown, restricted: boolean): ResultManifest | OwnerManifest {
  const v = object(value), bytes = number(v.bytes);
  requireValue(Number.isInteger(bytes) && bytes >= 0 && bytes <= 32 * 1024 * 1024);
  const common = { schema: text(v.schema), media_type: text(v.media_type), bytes, sha256: hash(v.sha256) };
  return restricted ? common : { ...common, parent: reference(v.parent), report: object(v.report) };
}
function receipt(value: unknown, restricted: true): Receipt<ResultManifest>;
function receipt(value: unknown, restricted: false): Receipt;
function receipt(value: unknown, restricted: boolean): Receipt<ResultManifest> {
  const v = object(value), output = object(v.output_reference);
  return { destination: text(v.destination), upstream_write: bool(v.upstream_write), publication_id: text(v.publication_id), identity: text(v.identity), output_reference: { authority: text(output.authority), key: text(output.key), revision: text(output.revision) }, manifest: manifest(v.manifest, restricted) };
}
export function run(value: unknown): Run {
  const v = object(value); requireValue(v.kind === "run");
  const common = { id: text(v.id), owner: text(v.owner), project_id: text(v.project_id), kind: "run" as const, application_version: text(v.application_version), state: text(v.state) };
  if (v.parent_visibility === "restricted") {
    requireValue(v.input === null); const b = object(v.binding);
    return { ...common, visibility: "restricted", parent_visibility: "restricted", binding: { name: text(b.name), curve: text(b.curve) }, input: null, receipt: receipt(v.receipt, true) };
  }
  return { ...common, visibility: "owned", binding: binding(v.binding), input: reference(v.input), input_sha256: hash(v.input_sha256), parameters: object(v.parameters), receipt: v.receipt == null ? null : receipt(v.receipt, false) };
}
export function result(value: unknown): Result {
  const v = object(value);
  const common = { asset_id: text(v.asset_id), revision: text(v.revision), id: text(v.id), name: text(v.name), owner: text(v.owner), curve: text(v.curve), can_share: bool(v.can_share), recipients: strings(v.recipients), reuse_recipients: strings(v.reuse_recipients), published: number(v.published) };
  if (v.input === null) return { ...common, visibility: "restricted", input: null, receipt: receipt(v.receipt, true) };
  return { ...common, visibility: "owned", input: reference(v.input), receipt: receipt(v.receipt, false) };
}
export function upload(value: unknown): UploadResult {
  const v = object(value);
  return { asset_id: text(v.asset_id), revision: text(v.revision), name: text(v.name), can_share: bool(v.can_share), acquisition: object(v.acquisition), permitted_audience: strings(v.permitted_audience), recipients: strings(v.recipients), reuse_recipients: strings(v.reuse_recipients) };
}
export function adapt(name: string | null, value: unknown): unknown {
  if (name === null) return value;
  if (name === "binding") return binding(value);
  if (name === "run") return run(value);
  if (name === "curve") return validateCurve(value);
  if (name === "upload") return upload(value);
  if (name === "result") return result(value);
  if (name === "results") { const v = object(value); requireValue(Array.isArray(v.results)); return { results: v.results.map(result) }; }
  if (name === "original") { const v = object(value); return { representation: text(v.representation), source: reference(v.source), sha256: hash(v.sha256), payload_base64: text(v.payload_base64) } satisfies Original; }
  if (name === "download") { const v = object(value); return { ...receipt(v, false), payload_base64: text(v.payload_base64) } satisfies Download; }
  throw new Error("Unknown generated response adapter");
}
export type { ApplicationCurve };
