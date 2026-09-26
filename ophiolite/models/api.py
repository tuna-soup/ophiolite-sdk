"""Typed preview catalogue and browser-application grant responses."""
from pydantic import Field
from .generated import Contract, AssetSummary

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
from pydantic import ConfigDict, PrivateAttr
from .generated import Reference

class OutputReference(Contract):
    authority: str
    key: str
    revision: str

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
