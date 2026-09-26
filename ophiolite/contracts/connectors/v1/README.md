# Connector semantics v1 — Stage 0 foundation

Canonical semantic vocabulary for managed source manifests and native external
snapshot descriptors. `contract.json` is distributed byte-for-byte in Connectors;
Integration checks equality and Connectors checks its pinned digest. Native protobuf
and managed JSON remain separate transport contracts. No identity or payload migration.

A scientific profile states the bounded scientific meaning exposed (source well-log,
raster, well-location or native snapshot); it is not a claim of complete OSDU WKS
validation. The exact upstream schema and adapter/customer mapping version are separate.
OSDU kinds come from approved exact configuration and returned metadata. SQL uses
schema digest and saved mapping version. Unknown schemas remain refused by readers.

Fidelity reports contain state, enumerated scope, assessor, method, version, losses
and limitations. Unassessed is not verified lossless. Assessed-no-loss requires an
empty loss list; assessed-with-loss requires a nonempty one. Byte preservation does
not certify meaning. Unknown schema/report versions are refused by conformance tools;
older UI manifests default to unassessed. New optional fields are additive; changes to
meaning, required fields or enum interpretation require a new contract version.

Reports on original source payloads and edited representations are independent;
never replace an original report with an edited-output report. Legacy wire messages
cannot carry these fields: their separate descriptor is unassessed, not a wire change.

Policy declarations are trusted configuration inputs, not client-provided authority.
The Stage 0 evaluator is a conformance helper only. Existing runtime authorization
remains authoritative. Read requires project and source read permission. Export adds
export permission; retain adds retention permission; redistribution adds retained
content, source distribution permission and an explicit recipient audience. Unknown
actions and missing grants deny. Continued upstream restrictions/revocation still
apply: the caller must supply current effective source grants. Retained package
services and team delegation are Stage 1/3 work, not implemented by a JSON declaration.

Quality policy preserves original unit/reference labels. Inspection is allowed with
visible unresolved findings. Operations and publication requiring resolved context
are blocked until resolved; a missing reference lookup never fabricates a valid record.

History means capability to attempt exact upstream reads, not guaranteed availability
forever. File/SQL pins cannot recover replaced bytes. Authorized retention is a separate
capability and does not transfer authority. Analytical projections carry exact source
revision and scientific context; edits do not implicitly write back upstream.
