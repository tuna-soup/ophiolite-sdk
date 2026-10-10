"""Typed preview catalogue and browser-application grant responses."""
from pydantic import Field
from .generated import Contract, AssetSummary, Via

class ListPage(Contract):
    items: list[AssetSummary]
    next_cursor: str | None = None

class Grant(Contract):
    id: str
    user_id: str
    project_id: str
    scopes: list[str]
    label: str
    confirmation_code: str
    state: str
    created_at: str
    expires_at: str
    capability: int = Field(ge=1)

# Hand-written application responses are kept separate from generated contracts.
from typing import Literal
from pydantic import ConfigDict, PrivateAttr, model_validator
from .generated import Reference

class OutputReference(Contract):
    authority: str
    key: str
    revision: str
    revision_number: int | None = Field(default=None,ge=1)  # present when the publication added a version (E8)

class ResultManifest(Contract):
    schema_: str = Field(alias='schema')
    media_type: str
    bytes: int = Field(ge=0,le=32*1024*1024)
    sha256: str = Field(pattern='^[0-9a-f]{64}$')

class OwnerManifest(ResultManifest):
    parent: Reference
    report: dict

class RestrictedManifest(ResultManifest):
    model_config=ConfigDict(extra='forbid',strict=True,allow_inf_nan=False)

class Receipt(Contract):
    destination: str
    upstream_write: bool
    publication_id: str
    identity: str
    output_reference: OutputReference
    manifest: OwnerManifest

    @property
    def asset(self):
        return {'asset_id':self.output_reference.key,'revision':self.output_reference.revision,'authority':self.output_reference.authority}

class RestrictedReceipt(Receipt):
    manifest: RestrictedManifest
    model_config=ConfigDict(extra='forbid',strict=True,allow_inf_nan=False)

class Binding(Contract):
    id: str
    owner: str
    project_id: str
    kind: Literal['binding']
    name: str
    generation: int = Field(ge=1)
    curve: str
    publication_profile: Literal['curve-edits/1','las-derived-curves/1'] = 'curve-edits/1'

class Run(Contract):
    id: str
    owner: str
    project_id: str
    kind: Literal['run']
    binding: Binding
    input_reference: Reference = Field(alias='input')
    input_sha256: str = Field(pattern='^[0-9a-f]{64}$')
    application_version: str
    parameters: dict
    state: str
    receipt: Receipt | None = None
    _client: object = PrivateAttr(default=None)
    _view_wire: dict | None = PrivateAttr(default=None)
    _original: bytes | None = PrivateAttr(default=None)
    _view: object = PrivateAttr(default=None)
    _work: object = PrivateAttr(default=None)
    _original_reference: dict = PrivateAttr(default_factory=dict)

    def input(self):
        if self._client is None:raise ValueError('Use the client that resolved this run to read its input.')
        return self._work.input(self) if self._work is not None else self._client.run_input(self)

class RestrictedBinding(Contract):
    model_config=ConfigDict(extra='forbid',strict=True)
    name: str
    curve: str

class RestrictedRun(Contract):
    # Ignore other run fields deliberately: a redacted run must not expose cached
    # input hashes/interpretations or source-bearing arbitrary parameters.
    model_config=ConfigDict(extra='ignore',strict=True,allow_inf_nan=False)
    id: str
    owner: str
    project_id: str
    kind: Literal['run']
    binding: RestrictedBinding
    input: None
    parent_visibility: Literal['restricted']
    application_version: str
    state: str
    receipt: RestrictedReceipt

class InputUpdate(Contract):
    newer_revision_available: bool

class HistoryEntry(Contract):
    number: int = Field(ge=1)
    revision: str
    parent_revision: str | None = None
    published_at: float | None = None
    by: str | None = None
    calculation: str | None = None
    application_version: str | None = None
    input: Reference | None = None
    run_id: str | None = None
    stage: str
    via: Via | None = None  # B1(a): the project access key this version was published through, as named then

class History(Contract):
    asset_id: str
    head_revision: str
    count: int = Field(ge=1)
    revisions: list[HistoryEntry] = Field(min_length=1)

class Recommendation(Contract):
    asset_id: str | None = None
    revision: str | None = None
    by: str
    at: float
    reason: str
    stage: str | None = None

class GroupMember(Contract):
    asset_id: str
    name: str | None = None
    head_revision: str
    revision_count: int = Field(ge=1)

class ResultGroup(Contract):
    """E8: a project result group as the caller may see it (hidden members are omitted, never counted)."""
    id: str
    name: str
    description: str
    owner: str
    members: list[GroupMember]
    recommended: Recommendation | None = None
    history: list[Recommendation] = Field(default_factory=list)
    generation: int = Field(ge=1)
    can_edit: bool
    can_recommend: bool

class ResultDiff(Contract):
    """E8: parameter, input and sample changes between two exact result versions."""
    a: dict
    b: dict
    parameters: dict
    application_version: dict
    input: dict
    samples: dict

class ResultSummary(Contract):
    asset_id: str
    revision: str
    id: str
    name: str
    owner: str
    input: Reference
    curve: str
    receipt: Receipt
    can_share: bool
    recipients: list[str]
    reuse_recipients: list[str]
    published: float
    revision_number: int | None = Field(default=None,ge=1)
    revision_count: int | None = Field(default=None,ge=1)
    input_update: InputUpdate | None = None  # derived signal; never a recommendation

class RestrictedResultSummary(ResultSummary):
    model_config=ConfigDict(extra='ignore',strict=True,allow_inf_nan=False)
    input: None
    receipt: RestrictedReceipt

class UploadResult(Contract):
    asset_id: str
    revision: str
    name: str
    can_share: bool
    acquisition: dict
    permitted_audience: list[str]
    recipients: list[str]
    reuse_recipients: list[str]

class Grants(Contract):
    asset_id: str
    revision: str
    recipients: list[str]
    reuse_recipients: list[str]
    generation: int | None = None  # None: the server does not support conditional sharing
    project: bool | None = None  # E78: shared with everyone in the project; None: the server does not report it

class UploadRequest(Contract):
    model_config=ConfigDict(extra='forbid',strict=True)
    project_id: str = Field(min_length=1,max_length=160)
    command_id: str = Field(min_length=1,max_length=64)
    filename: str = Field(min_length=1,max_length=160)
    name: str = Field(min_length=1,max_length=160)
    attribution: str = Field(min_length=1,max_length=500)
    well_notes: str = Field(default='',max_length=1000)
    audience: list[str] = Field(max_length=100)
    rights_confirmed: Literal[True]
    # E11 typed data and E18 import provenance (sent only when used).
    profile: str | None = Field(default=None, max_length=64)
    declared: dict[str, str] | None = Field(default=None, max_length=12)
    well_log: dict | None = None
    origin: dict | None = None
    # E53: a new version of your own uploaded wavelet, model or section (both or neither; sent only when used).
    append_to: str | None = Field(default=None, min_length=1, max_length=160)
    expected_parent: str | None = Field(default=None, pattern='^[0-9a-f]{64}$')

    @model_validator(mode='after')
    def appended(self):
        if (self.append_to is None) != (self.expected_parent is None): raise ValueError('A new version names both the result and the version it replaces')
        return self

class ResultPreview(ResultSummary):
    rows: list[dict]
    columns: list[dict]
    context: dict
    total_rows: int = Field(ge=0)
    truncated: bool

class RestrictedResultPreview(RestrictedResultSummary):
    rows: list[dict]
    columns: list[dict]
    context: dict
    total_rows: int = Field(ge=0)
    truncated: bool

# E30b: publications/derive
from .generated import MethodRecord

class PublicationReceipt(Contract):
    asset_id: str
    revision: str = Field(pattern='^[0-9a-f]{64}$')
    revision_number: int = Field(ge=1)
    profile: str
    derived_from: list[Reference] = Field(min_length=1,max_length=32)
    method: MethodRecord
    command_id: str


# E31 S2: the journey routes' answers, validated before a client method hands them on (the method's return shape
# is unchanged). tests/test_journey_models.py holds each to the synced OpenAPI component it mirrors.
class ProjectEntry(Contract):
    id: str
    name: str | None
    role: str | None
    can_administer: bool
    organization_id: str | None


class ProjectsPage(Contract):
    projects: list[ProjectEntry]
    next_cursor: str | None


class OrganizationEntry(Contract):
    id: str
    name: str


class OrganizationsPage(Contract):
    organizations: list[OrganizationEntry]


class ChangeEvent(Contract):
    project: str
    cursor: int
    epoch: str
    kind: str
    subject_kind: str | None
    subject_id: str | None
    generation: int | None
    revision: str | None
    actor_kind: str | None
    actor: str | None
    at: float


class ChangesHead(Contract):
    epoch: str
    cursor: int


class ChangesPage(Contract):
    epoch: str
    changes: list[ChangeEvent]
    cursor: int
    has_more: bool


class EntityExtent(Contract):
    crs: str
    bbox: list[float] | None = Field(min_length=4, max_length=4)
    count: int = Field(ge=0)
    untransformed: int = Field(ge=0)


class EntityPage(Contract):
    entities: list[dict]
    next_cursor: str | None = None
    untransformed: int | None = None


class SourceReferenceDoc(Contract):
    """E50a: the exact identity of one upstream read (sources/list, sources/export)."""
    authority: str
    key: str
    revision: str
    profile: str


class SourceSelectionDoc(Contract):
    """E50a: one source selection as sources/list answers it (only the fields the SDK reads are named)."""
    id: str
    name: str
    profile: str
    state: str
    mode: str
    authority: str
    key: str
    connection_id: str
    reference: SourceReferenceDoc


class SourceSelectionsPage(Contract):
    selections: list[SourceSelectionDoc]
    scope: str


class SourceExportManifestDoc(Contract):
    schema_: str = Field(alias='schema', pattern='^ophiolite\\.source-snapshot/1$')
    reference: SourceReferenceDoc
    metadata: dict
    sha256: str = Field(pattern='^[0-9a-f]{64}$')
    bytes: int = Field(ge=0)
    media_type: str
    reviewed_meaning_digest: str | None
    interpretation: dict | None


class SourceExportAnswer(Contract):
    manifest: SourceExportManifestDoc
    payload_base64: str


# E50c: the release routes Wells.with_source reads (releases/list, download-snapshot, download); other fields are kept.
class ReleaseListItem(Contract):
    id: str
    state: str
    manifest_digest: str
    assets: int = Field(ge=0)


class ReleasesListAnswer(Contract):
    items: list[ReleaseListItem]


class ReleasesDownloadAnswer(Contract):
    filename: str
    payload_base64: str

# E42a: well imports (well-imports/*), the fields the SDK and the command line read; other fields are kept.
WellImportState = Literal['importing', 'resumable', 'needs-review', 'complete', 'complete-with-skipped', 'cancelled']
Number = float | int


class WellImportWell(Contract):
    entity_id: str
    name: str


class WellImportRowWell(Contract):
    ordinal: int
    row_key: str
    well: WellImportWell | None = None


class WellImportSkipped(Contract):
    ordinal: int
    row_key: str
    codes: list[str]
    reason: str | None = None
    fields: list[str] | None = None


class WellImportSuperseded(WellImportRowWell):
    reason: str


class WellImportCounts(Contract):
    accepted: int
    planned: int
    created: int
    already_here: int
    skipped: int


class WellImportSummary(Contract):
    id: str
    project_id: str
    state: WellImportState
    words: str
    reason: str | None = None
    initiator: str
    connection_id: str
    key: str
    release_id: str
    approved_by: str
    approved_at: Number
    created_at: Number
    updated_at: Number
    counts: WellImportCounts


class WellImport(WellImportSummary):
    identity_authority: str
    audience: list[str]
    mapping: dict
    input_revision: str
    preview_digest: str
    skipped: list[WellImportSkipped]
    possible_duplicates: list[WellImportRowWell]
    already_here: list[WellImportRowWell]
    superseded: list[WellImportSuperseded]


class WellImportsListAnswer(Contract):
    imports: list[WellImportSummary]


class WellImportPreviewCounts(Contract):
    rows: int
    create: int
    already_here: int
    skipped: int
    possible_duplicates: int
    names_from_numbers: int


class WellImportsPreviewAnswer(Contract):
    preview_digest: str
    connection_id: str
    key: str
    source_name: str
    counts: WellImportPreviewCounts
    skipped: list[WellImportSkipped]
    possible_duplicates: list[WellImportRowWell]
    already_here: list[WellImportRowWell]
    warnings: list[dict]
    audience: dict
    input_revision: str

# E55: folder uploads (upload-runs/*), the fields the SDK and the command line read; other fields are kept.
UploadRunFileState = Literal['waiting', 'reading', 'added', 'already-here', 'needs-decision', 'not-read', 'not-supported', 'cancelled']


class UploadRunCounts(Contract):
    waiting: int
    reading: int
    added: int
    already_here: int
    needs_decision: int
    not_read: int
    not_supported: int
    cancelled: int


class UploadRunFile(Contract):
    ordinal: int
    path: str
    bytes: int
    sha256: str
    role: str
    state: UploadRunFileState
    profile: str | None = None
    kind: str | None = None
    reason_code: str | None = None
    sentence: str | None = None
    technical: str | None = None
    asset_id: str | None = None
    revision: str | None = None
    read: str | None = None
    well: str | None = None
    declared: dict | None = None
    proposal: dict | None = None
    association: dict | None = None


class UploadRunSummary(Contract):
    run_id: str
    project_id: str
    folder_name: str
    state: Literal['open', 'closed', 'cancelled']
    label: str
    files: int
    counts: UploadRunCounts


class UploadRun(UploadRunSummary):
    items: list[UploadRunFile]


class UploadRunsListAnswer(Contract):
    runs: list[UploadRunSummary]


class UploadCheckFetched(Contract):
    """E85b: what the gateway fetched from an address (the address without its query string)."""
    address: str
    host: str
    name: str
    bytes: int
    sha256: str


class UploadCheckAnswer(Contract):
    """E85: upload-runs/check, the fields the SDK reads."""
    reads: Literal['head', 'whole']
    kind: dict | None = None
    stated: list[dict]
    asks: list[dict]
    refusal: dict | None = None
    fetched: UploadCheckFetched | None = None


class UploadRunStep(Contract):
    run_id: str
    step: Literal['send', 'done', 'wait', 'next', 'parts', 'checking']
    attempt: int | None = None
    send: dict | None = None
    file: UploadRunFile
    session: dict | None = None


class OrgConnectionYou(Contract):
    use: bool
    administer: bool
    signed_in: bool


class OrgConnectionReadiness(Contract):
    code: str
    actor: str


class OrgConnectionAccess(Contract):
    person: str
    use: bool
    administer: bool


class OrgConnectionDoc(Contract):
    """E39: one organisation connection as its person may see it; access lists only for those who administer it."""
    id: str
    organization_id: str
    name: str
    enabled: bool
    generation: int
    you: OrgConnectionYou
    readiness: OrgConnectionReadiness | None = None
    access: list[OrgConnectionAccess] | None = None


class OrgConnectionsPage(Contract):
    organization_id: str
    connections: list[OrgConnectionDoc]
    scope: str
