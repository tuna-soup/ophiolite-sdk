import type { ApplicationCurve, Reference, ScientificAsset, ScientificContext } from "./generated/contracts.js";
import { schemas, profiles } from "./generated/schemas.js";
import { Incompatible, VerificationFailed } from "./errors.js";

type ObjectValue = Record<string, unknown>;
export function requireValue(condition: unknown, message?: string): asserts condition {
  if (!condition) throw new VerificationFailed(message);
}
export function object(value: unknown): ObjectValue {
  requireValue(value !== null && typeof value === "object" && !Array.isArray(value));
  return value as ObjectValue;
}
function equal(a: unknown, b: unknown): boolean { return JSON.stringify(a) === JSON.stringify(b); }
function selected(a: object, b: object, keys: readonly string[]): boolean {
  const x = a as ObjectValue, y = b as ObjectValue;
  return keys.every(k => (x[k] ?? null) === (y[k] ?? null));
}
const referenceKeys = ["authority", "key", "revision", "profile"];
const interpretationKeys = ["reader", "parsing_policy", "mapping", "lasio_version", "null_policy"];

/** Tolerate new fields, but validate every declared field against the pinned schema. */
export function validateSchema(value: unknown, schema: unknown, document: unknown = schema): void {
  if (schema === true) return;
  const s = object(schema);
  if (typeof s.$ref === "string") {
    requireValue(s.$ref.startsWith("#/$defs/"));
    const key = s.$ref.slice(8).replaceAll("~1", "/").replaceAll("~0", "~");
    validateSchema(value, object(object(document).$defs)[key], document); return;
  }
  if ("const" in s) requireValue(equal(value, s.const));
  if (Array.isArray(s.enum)) requireValue(s.enum.some(x => equal(x, value)));
  for (const union of ["anyOf", "oneOf"]) {
    if (Array.isArray(s[union])) {
      let successes = 0;
      for (const branch of s[union]) {
        try { validateSchema(value, branch, document); successes++; }
        catch (error) { if (!(error instanceof VerificationFailed)) throw error; }
      }
      requireValue(union === "oneOf" ? successes === 1 : successes > 0); return;
    }
  }
  if (Array.isArray(s.type)) {
    validateSchema(value, { anyOf: s.type.map(type => ({ ...s, type })) }, document); return;
  }
  if (s.type === "null") { requireValue(value === null); return; }
  if (s.type === "object") {
    const v = object(value);
    for (const key of (s.required ?? []) as string[]) requireValue(Object.hasOwn(v, key));
    for (const [key, child] of Object.entries((s.properties ?? {}) as ObjectValue)) {
      if (Object.hasOwn(v, key)) validateSchema(v[key], child, document);
    }
  } else if (s.type === "array") {
    requireValue(Array.isArray(value));
    if (typeof s.minItems === "number") requireValue(value.length >= s.minItems);
    if (typeof s.maxItems === "number") requireValue(value.length <= s.maxItems);
    for (const item of value) validateSchema(item, s.items, document);
  } else if (s.type === "string") {
    requireValue(typeof value === "string");
    if (typeof s.minLength === "number") requireValue([...value].length >= s.minLength);
    if (typeof s.maxLength === "number") requireValue([...value].length <= s.maxLength);
    if (typeof s.pattern === "string") requireValue(new RegExp(s.pattern).test(value));
  } else if (s.type === "boolean") requireValue(typeof value === "boolean");
  else if (s.type === "number" || s.type === "integer") {
    requireValue(typeof value === "number" && Number.isFinite(value));
    if (s.type === "integer") requireValue(Number.isInteger(value));
    if (typeof s.minimum === "number") requireValue(value >= s.minimum);
    if (typeof s.maximum === "number") requireValue(value <= s.maximum);
    if (typeof s.exclusiveMinimum === "number") requireValue(value > s.exclusiveMinimum);
  }
}
function marker(value: string): number {
  const parsed = value.trim() === "" ? NaN : Number(value);
  requireValue(Number.isFinite(parsed), "LAS missing marker must be finite."); return parsed;
}
function reference(value: Reference | null): void {
  if (value !== null) requireValue(Object.hasOwn(profiles, value.profile), "Reference profile is not registered.");
}
function context(value: ScientificContext): void {
  marker(value.missing_value_marker);
  for (const label of ["unit", "axis_unit"] as const) requireValue(value[`${label}_status`] === (value[label].trim() ? "declared" : "unknown"));
  requireValue(value.missing_count <= value.sample_count);
  requireValue(!value.axis_duplicates || value.axis_order === "unordered");
  requireValue((value.sample_count < 2) === (value.axis_order === "insufficient"));
}
export function validateDescriptor(value: unknown): ScientificAsset {
  validateSchema(value, schemas["ophiolite.scientific-asset/1"]);
  const asset = value as ScientificAsset;
  reference(asset.source_reference); asset.parents.forEach(reference); context(asset.scientific);
  for (const rep of asset.representations) {
    const profile = object(profiles[rep.profile]);
    requireValue(profile.role === (rep.kind === "normalized" ? "normalized" : "artifact"));
    requireValue(Array.isArray(profile.media_types) && profile.media_types.includes(rep.media_type));
  }
  const retained = asset.origin !== "source-reference";
  requireValue(retained === (asset.custodian !== null) && retained === (asset.retention.mode === "retained"));
  requireValue(asset.retention.historical_reads === (retained ? "while-retained-and-authorized" : "not-guaranteed"));
  if (asset.origin === "managed-derived") {
    requireValue(asset.authority === "ophiolite:derived" && asset.source_reference === null && (asset.parents.length > 0 || asset.parent_visibility === "restricted"));
    const ids = asset.parents.map(p => JSON.stringify([p.authority, p.key, p.revision]));
    requireValue(new Set(ids).size === ids.length && !ids.includes(JSON.stringify([asset.authority, asset.asset_id, asset.revision])));
    requireValue(asset.provenance.evidence === "script-declared" && asset.provenance.method !== null);
  } else {
    requireValue(asset.source_reference !== null && asset.authority === asset.source_reference.authority && asset.parents.length === 0);
    requireValue(asset.provenance.evidence === "source-declared");
  }
  // Match Python's tolerant defaults for old descriptors that predate reader history.
  requireValue((asset.recorded_interpretation == null) === (["live", "not-recorded"].includes(asset.interpretation_evidence ?? "live")));
  const reps = asset.representations;
  requireValue(new Set(reps.map(r => r.id)).size === reps.length);
  const profile = object(profiles[asset.profile]);
  requireValue(Array.isArray(profile.serves) && profile.serves.includes("ophiolite.scientific-asset/1"));
  const rules = object(profile.representation_rules);
  const normalized = reps.filter(r => r.kind === "normalized");
  const artifactKind = object(rules.artifact_kind_by_origin)[asset.origin];
  const artifacts = reps.filter(r => r.kind === artifactKind);
  requireValue(normalized.length === rules.normalized && artifacts.length === 1 && reps.length === rules.total);
  requireValue(artifacts[0].profile === asset.profile && normalized[0].profile === profile.normalized_profile);
  if (asset.origin === "managed-derived") requireValue(asset.revision === artifacts[0].sha256);
  requireValue(new Set(asset.supported_operations).size === asset.supported_operations.length);
  if (asset.authorization.status === "evaluated") {
    const auth = asset.authorization, date = new Date(auth.evaluated_at);
    requireValue(Number.isFinite(date.getTime()) && date.toISOString().replace(".000Z", "Z") === auth.evaluated_at, "Authorization timestamp is not a real calendar time.");
    requireValue(new Set(auth.allowed_operations).size === auth.allowed_operations.length && auth.allowed_operations.every(x => asset.supported_operations.includes(x)));
  }
  if (asset.recorded_interpretation) {
    const old = asset.recorded_interpretation;
    if (old.mapping !== asset.interpretation.mapping) throw new Incompatible();
    const same = selected(old, asset.interpretation, ["reader", "parsing_policy", "lasio_version"]);
    requireValue(asset.interpretation_evidence === (same ? "recorded" : "recorded-differs"), "The reported reader history disagrees with its records.");
  }
  return asset;
}
export function validateCurve(value: unknown): ApplicationCurve {
  validateSchema(value, schemas["ophiolite.application-curve/1"]);
  const curve = value as ApplicationCurve;
  reference(curve.source); const sentinel = marker(curve.context.missing_value_marker);
  requireValue(curve.axis.length === curve.values.length && curve.curve !== curve.context.depth_index);
  requireValue(!curve.axis.includes(sentinel) && !curve.values.includes(sentinel));
  return curve;
}
export async function sha256(raw: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new Uint8Array(raw).buffer);
  return Array.from(new Uint8Array(digest), x => x.toString(16).padStart(2, "0")).join("");
}
export async function verifyBytes(raw: Uint8Array, bytes: number, digest: string): Promise<void> {
  requireValue(raw.length === bytes && await sha256(raw) === digest, "Representation integrity mismatch.");
}
export async function verifyPair(descriptor: unknown, raw: Uint8Array): Promise<{ descriptor: ScientificAsset; curve: ApplicationCurve }> {
  const asset = validateDescriptor(descriptor);
  const rep = asset.representations.find(r => r.kind === "normalized")!;
  requireValue(rep.available); await verifyBytes(raw, rep.bytes, rep.sha256);
  let value: unknown;
  try { value = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(raw)); }
  catch { throw new VerificationFailed("Normalized data is not valid JSON."); }
  const curve = validateCurve(value);
  const expected = asset.source_reference ?? { authority: asset.authority, key: asset.asset_id, revision: asset.revision, profile: asset.profile };
  const artifact = asset.representations.find(r => r.kind !== "normalized")!;
  requireValue(selected(curve.source, expected, referenceKeys) && curve.source_sha256 === artifact.sha256);
  const axis = curve.axis;
  const pairs = axis.slice(1).map((v, i) => [axis[i], v]);
  const order = !pairs.length ? "insufficient" : pairs.every(([a,b]) => a < b) ? "increasing" : pairs.every(([a,b]) => a > b) ? "decreasing" : "unordered";
  const facts = { curve: curve.curve, unit: curve.unit, unit_status: curve.unit.trim() ? "declared" : "unknown", axis_unit: curve.context.depth_unit, axis_unit_status: curve.context.depth_unit.trim() ? "declared" : "unknown", depth_reference: curve.context.depth_reference, sample_count: axis.length, missing_count: curve.values.filter(x => x === null).length, missing_value_marker: curve.context.missing_value_marker, axis_order: order, axis_duplicates: new Set(axis).size !== axis.length };
  requireValue(selected(asset.scientific, facts, Object.keys(facts)) && selected(asset.interpretation, curve.interpretation, interpretationKeys));
  return { descriptor: asset, curve };
}
