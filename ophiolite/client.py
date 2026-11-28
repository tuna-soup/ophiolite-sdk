"""Bounded reads of exact scientific revisions. No implicit login or cache access."""
from __future__ import annotations  # E217 s0 (D1): annotations stay strings; nothing below is imported to run

import gc
import hashlib
import json
import math
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote, urlencode
import httpx
from . import _client_header  # E93
from . import _core
from . import _deprecation  # E148: one warning per deprecated route
from . import _ranges  # E100d1: ranged reads, shared with aio
from . import surveys as _surveys  # E142 s1
from .errors import (AuthenticationRequired, PermissionRefused, IntegrityConflict, CapacityExceeded, Refused, Busy,
                     Incompatible, OphioliteError, Unavailable, VerificationFailed)

MAX_BYTES=32*1024*1024
# E94: every descriptor request declares the revision manifest profiles this library verifies (/3 carries how a result was made;
# E106: /4, how a result was made with a catalogue procedure on a person's computer)
PROFILES='&profiles=%2F1%2C%2F2%2C%2F3%2C%2F4'
FILE_BYTES=128*1024*1024  # E58b: a downloaded table file (a connected table is read up to 64 MiB; CSV is longer than Parquet)
FILE_FORMATS=('parquet','geoparquet','csv')
DOWNLOAD_MISMATCH='The download did not match the file the server holds; nothing was saved.'
WELL_LOG_FORM='ophiolite.well-log-curve/1'  # E183 s2c: the one form `read` may ask for (the gateway's)
FORM_CHOICE='Ask for the well log form (ophiolite.well-log-curve/1) or for no form.'  # the gateway's sentence (curve_mapping.FORM_CHOICE)


from ._core import origin


from .auth import Credential
from .entities import EntityClient
from .navigation import Navigation

if TYPE_CHECKING:  # E217 s0 (D1): read by a type checker only; `import ophiolite.client` loads none of these
    from collections.abc import Iterator, Mapping, Sequence
    from typing import Any

    import numpy as np
    import numpy.typing as npt
    import pandas as pd

    from .bundle import Bundle
    from .imports import Imports
    from .layouts import Layouts
    from .models.api import (Binding, Grants, History, PublicationReceipt, Receipt, RestrictedReceipt, RestrictedResultPreview,
                             RestrictedResultSummary, RestrictedRun, ResultDiff, ResultGroup, ResultPreview, ResultSummary, Run,
                             UploadResult)
    from .models.generated import ApplicationCurve, ScientificAsset, SearchAnswer, SearchAnswerByMeaning, SearchRow, SurveyPage
    from .models.items import AssetItem
    from .presentation import PresentedExchange, PresentedReceipt
    from .public_repositories import PublicRepositories
    from .publish import WorkFolder
    from .scientific import Descriptor, WellLog, WellLogDescriptor
    from .surveys import Survey
    from .sync import Sync
    from .table_kinds import TableKindClient
    from .table_templates import Template
    from .typed import SeismicSlice, TypedData
    from .upload_runs import Report, UploadRuns
    from .volume_windows import VolumeWindowResult, WindowReader
    from .well_imports import WellImports
    from .well_names import WellNames
    from .well_sets import WellSets
    from .windows import CurveWindow


class CurveSet:
    """The curves you read from one exact version, each checked against what the server stored.

    `descriptors` holds each curve's description, `curves` its values with the depth axis, `artifact` the original
    file's bytes, and `url` and `project` where it was read.

    Example
    -------
    curves = client.read('log-id', 'revision-id', ['GR'])
    gamma_ray = curves.curves[0]
    print(gamma_ray.axis[0], gamma_ray.values[0])
    """
    descriptors: list[ScientificAsset]
    curves: list[ApplicationCurve]
    artifact: bytes
    url: str
    project: str

    def __init__(self,descriptors,curves,artifact,*,url='',project='',wire_descriptors=None,wire_curves=None,wire_curve_bytes=None):
        self.descriptors,self.curves,self.artifact=descriptors,curves,artifact
        self.url,self.project=url,project
        self._wire_descriptors,self._wire_curves=wire_descriptors,wire_curves
        self._wire_curve_bytes=wire_curve_bytes  # exact served bytes; their digest is in the descriptor

    @property
    def evidence(self) -> dict[str, str]:
        """How each curve's reading of the file compares with the one recorded at upload, by curve mnemonic.

        Each value is 'recorded', 'recorded-differs', 'live', 'not-recorded' or 'not-available' (an older server
        that states none).
        """
        return {asset.scientific.curve:_core.rules.interpretation(asset.model_dump(by_alias=True,exclude_unset=True)) for asset in self.descriptors}

    def to_numpy(self) -> tuple[npt.NDArray[np.float64], Descriptor]:
        """The curves as one array, one column per curve, with what describes them (needs numpy)."""
        from .scientific import to_numpy
        return to_numpy(self)

    def to_frame(self) -> tuple[pd.DataFrame, Descriptor]:
        """The curves as one table indexed by depth, with what describes them (needs pandas)."""
        from .scientific import to_frame
        return to_frame(self)

    def workspace_url(self) -> str | None:
        """The address of this version's page in the Workspace, or None when the read has no server address."""
        from .scientific import workspace_url
        return workspace_url(self)

    def _repr_html_(self):
        from .repr import curve_set_html
        return curve_set_html(self)

    def save(self,path:str|os.PathLike[str],*,legacy_order:bool=False) -> None:
        """Save the original file and each curve with its description into a new private folder.

        The folder must not exist yet; `legacy_order=True` writes the JSON files in the order the server sent them.
        """
        path=Path(path)
        try:path.mkdir(mode=0o700,parents=True,exist_ok=False)
        except FileExistsError:raise Refused('Output already exists. Choose a new folder.') from None
        def write(name,raw):
            fd=os.open(path/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as stream:stream.write(raw)
        def encode(value):return (json.dumps(value,indent=2,allow_nan=False)+'\n').encode()
        write('artifact.las',self.artifact)
        for index,(descriptor,view) in enumerate(zip(self.descriptors,self.curves)):
            suffix='' if len(self.curves)==1 else '-'+quote(view.curve,safe='')
            write('curve'+suffix+'.json',encode(self._wire_curves[index] if legacy_order and self._wire_curves is not None else view.model_dump(by_alias=True,exclude_unset=True)))
            # Single-curve output matches the old kit; every multi-curve descriptor
            # is retained, rather than silently keeping only the last one.
            write('descriptor'+suffix+'.json',encode(self._wire_descriptors[index] if legacy_order and self._wire_descriptors is not None else descriptor.model_dump(by_alias=True,exclude_unset=True)))


class WellLogSet(CurveSet):
    """E183 s2c: curves read with form `ophiolite.well-log-curve/1`; each of `curves` is a verified
    `ophiolite.scientific.WellLog`. `to_numpy` and `to_frame` combine them only when depth, depth unit, depth kind,
    datum, well and source agree (else AxisMismatch); the frame's index is named by the declared depth kind."""
    form=WELL_LOG_FORM
    curves: list[WellLog]  # type: ignore[assignment]  # E217 s0: a well log read holds WellLog views, not application curves

    def to_numpy(self) -> tuple[npt.NDArray[np.float64], WellLogDescriptor]:  # type: ignore[override]
        from .scientific import well_logs_numpy
        return well_logs_numpy(self)

    def to_frame(self) -> tuple[pd.DataFrame, WellLogDescriptor]:  # type: ignore[override]
        from .scientific import well_logs_frame
        return well_logs_frame(self)

    def _repr_html_(self):
        import html
        return '<section aria-label="Well logs"><p>'+html.escape(', '.join(repr(v) for v in self.curves),quote=True)+'</p></section>'


class Provenance:
    """E122 s0: one version's source record as served: `words` (the gateway's sentence), `record` (or None),
    `observation` (the run, reader and time that read it), `gone` (E122 s2, or None) and `json` (the served document).
    E182 s2b: `sender` (what the request that made the version said sent it, `ophiolite.sender/1` as served) and
    `sender_words` (the gateway's sentence for it, passed through unchanged); both None from a gateway that serves neither."""
    __slots__=('json',)

    def __init__(self,data):self.json=data
    words=property(lambda self:self.json['words'])
    record=property(lambda self:self.json.get('record'))
    observation=property(lambda self:self.json.get('observation'))
    gone=property(lambda self:self.json.get('gone'))  # E122 s2: the item marked gone from its source (source, path, run_id, marked_at, sentence), or None
    sender=property(lambda self:self.json.get('sender'))  # E182 s2b: as served, never composed or checked here
    sender_words=property(lambda self:self.json.get('sender_words'))  # E182 s2b: the gateway's own sentence

    def __repr__(self):return 'Provenance(%r)'%self.json['words']


PROVENANCE_BYTES=64*1024
NO_SOURCE_RECORDS='this server has no source records'  # E122 s5b: an older gateway has no provenance route


def _provenance_path(prefix,asset,revision):
    if not all(isinstance(x,str) and x for x in (asset,revision)):
        raise Refused('Choose an asset and its exact revision.')
    return prefix+'/'+quote(asset,safe='')+'/revisions/'+quote(revision,safe='')+'/provenance'


def _provenance_of(data,asset,revision):
    """E122 s5b: one check of the provenance answer for both clients."""
    if not isinstance(data,dict) or data.get('schema')!='ophiolite.source-provenance/1' or not isinstance(data.get('words'),str) \
            or (data.get('asset_id'),data.get('revision'))!=(asset,revision):
        raise VerificationFailed('The provenance answer is not for the version asked.')
    return Provenance(data)


def _no_provenance_route(error):
    """The router's own 404 (code `NOT_FOUND`), not the route's `not-found` for an asset it cannot show."""
    return getattr(error,'status',None)==404 and getattr(error,'code',None)=='NOT_FOUND'


def _source_record_of(found):
    if found.record is None:return None
    return {'schema':'ophiolite.source-provenance/1','asset_id':found.json['asset_id'],'revision':found.json['revision'],'record':found.record}


def _parts_of(found):
    """E182 s2b (D-5): (source record or None, sender or None) of one provenance answer, each its own bundle entry field:
    a sender travels without a record, a record without a sender is as before."""
    return _source_record_of(found),found.sender


def _warn_source_records_omitted(omitted):
    if omitted:
        import warnings
        warnings.warn('Source records were left out of this bundle: '+omitted+'.',UserWarning,stacklevel=3)


def _environment_credential(url,project):
    """The credential gallery.connect would take for URL and PROJECT, in its order: the file OPHIOLITE_CREDENTIAL names
    or the sign-in `ophiolite account login` saved for them, else OPHIOLITE_ACCESS_KEY; None when there is none."""
    from .auth import default_path
    path=os.environ.get('OPHIOLITE_CREDENTIAL') or default_path(url,project)
    if os.environ.get('OPHIOLITE_CREDENTIAL') or os.path.exists(path) or os.path.islink(path):return Credential.from_file(path)
    if 'OPHIOLITE_ACCESS_KEY' in os.environ:return Credential.bearer(os.environ['OPHIOLITE_ACCESS_KEY'],source='environment')
    return None


from .locations import LocationClient  # noqa: E402
from .sources import SourceClient  # noqa: E402
from .checks import CheckClient  # noqa: E402
from .procedures import ProcedureClient  # noqa: E402
from .tools import ToolClient  # noqa: E402  (E131 s1: the tool_* twins)
from .access_history import AccessHistoryClient  # noqa: E402  (E67b)
from .outcomes import OutcomeClient  # noqa: E402  (E120)
from .chains import ChainClient  # noqa: E402  (E178 s2c)
from .figures import FigureClient  # noqa: E402  (E191 s1)
from .documents import DocumentClient  # noqa: E402  (E222 s1)
from .verdicts import VerdictClient  # noqa: E402  (E132)
from .trajectories import TrajectoryClient  # noqa: E402  (E134)
from .rule_results import RuleResultsClient  # noqa: E402  (E144 s3)


def affected_whole(pages):
    """E177 s1 (D-8): served changes/affected pages gathered into the whole answer Client.affected() returns."""
    whole={'rows':[],'restricted':False,'complete':True,'pages':0}
    for page in pages:
        whole['rows']+=page['rows']
        whole.update({key:page[key] for key in ('item','as_of','counts','without_inputs')})
        whole['restricted']=whole['restricted'] or page['restricted']
        whole['complete']=whole['complete'] and page['complete']
        whole['pages']+=1
    return whole


class Client(Navigation, EntityClient, LocationClient, SourceClient, CheckClient, ProcedureClient, ToolClient, AccessHistoryClient, OutcomeClient, VerdictClient, TrajectoryClient, RuleResultsClient):  # E29: wells() and extent(); E50a: sources(); E96: checks; E105b: procedures; E131 s1: tools; E67b: access history and teams; E120: outcomes; E132: verdicts; E134: export_trajectories; E144 s3: rule_results
    """One project on an Ophiolite deployment, read and written with your own sign-in.

    Parameters
    ----------
    url
        The deployment's address.
    project
        The project's id.
    credential
        Your sign-in; `from_configuration` finds the one saved for this deployment when none is given.
    http
        An httpx client to send requests through; without one the client makes and closes its own.
    application, host
        (name, version) of the program that sends the requests and of the application it runs in; each request
        reports them. Without them the requests report this library.

    Example
    -------
    with ophiolite.Client.from_configuration('configuration.json') as connected:
        wells = connected.wells()
    """
    _sender=None  # E182 s1: what this client says sent its requests; None is this library's own report

    def __init__(self,url:str,project:str,credential:Credential|None=None,http:httpx.Client|None=None,*,application:tuple[str,str]|None=None,host:tuple[str,str]|None=None) -> None:
        sender=_client_header.sender(application,host)  # refused before a transport exists
        self.url=origin(url)
        if not isinstance(project,str) or not project:raise Refused('Choose a project.')
        self.project,self.credential,self._sender=project,credential,sender
        self.prefix='/api/v1/projects/'+quote(project,safe='')+'/scientific-assets'
        self._owns_http=http is None
        self.http=http or httpx.Client(timeout=60,follow_redirects=False,trust_env=False)
        self._notifier=_deprecation.Notifier()  # E148: this client's once-set; nothing is installed on http

    @classmethod
    def from_configuration(cls,path:str|os.PathLike[str]='configuration.json',*,credential:Credential|None=None,http:httpx.Client|None=None,application:tuple[str,str]|None=None,host:tuple[str,str]|None=None) -> Client:
        """Connect to the deployment and project named in the configuration file you downloaded from Connect.

        Without `credential`, the sign-in `ophiolite account login` saved for them is used, or the file
        OPHIOLITE_CREDENTIAL names, or OPHIOLITE_ACCESS_KEY.
        """
        try:value=json.loads(Path(path).read_text())
        except (OSError,ValueError):raise Refused('Cannot read configuration. Download it again from Connect.') from None
        if not isinstance(value,dict) or value.get('schema') not in ('ophiolite.read-configuration/1','ophiolite.local-configuration/1'):
            raise Refused('Download a supported configuration from Connect.')
        if ('asset' in value)!=('revision' in value):raise Refused('An exact selection needs both asset and revision.')
        for key in ('asset','revision','curve'):
            if key in value and (not isinstance(value[key],str) or not value[key]):raise Refused('Invalid exact-read selection.')
        client=cls(value.get('url'),value.get('project'),credential,http,application=application,host=host)
        if credential is None:client.credential=_environment_credential(client.url,client.project)  # first-run defect 9
        return client

    def sync(self,checkpoint=None) -> Sync:
        """A local copy of this project, kept current from what changed in it.

        Parameters
        ----------
        checkpoint
            The file (or ophiolite.sync.Checkpoint) that remembers how far a copy has read; None starts afresh.

        Returns
        -------
        Sync
            The local copy (ophiolite.sync.Sync).
        """
        # E28
        from .sync import Sync
        return Sync(self,checkpoint=checkpoint)

    @property
    def upload_runs(self) -> UploadRuns:
        """Upload a folder or a .zip with one report (ophiolite.upload_runs.UploadRuns)."""
        # E55
        from .upload_runs import UploadRuns
        return UploadRuns(self)

    def upload(self,path_or_address,*,attribution=None,rights_confirmed,audience=None,well_notes='',declare=None,skip_decisions=False,link_wellbore=False,new=False,progress=None,
               use_project_defaults=False) -> Report:
        """Add a file, a folder, a .zip or an https address to the project in one upload.

        An address is fetched by the server: no file bytes are sent from here.

        Parameters
        ----------
        path_or_address
            The path of a file, a folder or a .zip, or an https address.
        attribution
            Who the files are attributed to; None takes the project's New data setting.
        rights_confirmed
            True: you confirm that you may keep these files, make results from them and share them with the audience.
        audience
            Who may see the files: 'me' (only you), 'project' (everyone, when that is the project's setting) or a
            list of people; None takes the project's New data setting.
        well_notes
            A note kept with the wells the files name.
        declare
            {kind: {field: value}}: what the files of that kind leave open; the value 'project-default' keeps the
            project's default for that field.
        skip_decisions
            True skips every file that needs a decision `declare` does not give.
        link_wellbore
            True links each file to the one wellbore whose name its header names.
        new
            True starts a new upload even when an unfinished upload of the same files exists; otherwise that one
            continues.
        progress
            Called with the report after each file.
        use_project_defaults
            True keeps the project's default for every field a file leaves open.

        Returns
        -------
        Report
            What happened to each file (ophiolite.upload_runs.Report).

        Raises
        ------
        ValidationFailed
            When `rights_confirmed` is not True.
        Refused
            When the path is not a path or an address, or a `declare` entry is not one the files can take.
        """
        # E85; E90: attribution, audience and the project-default declarations
        return self.upload_runs.upload(path_or_address,attribution=attribution,rights_confirmed=rights_confirmed,audience=audience,well_notes=well_notes,
                                       declare=declare,skip_decisions=skip_decisions,associate_matches=link_wellbore,new=new,progress=progress,
                                       use_project_defaults=use_project_defaults)

    def templates(self) -> list[dict[str, Any]]:
        """The kinds of table you can fill in from a template.

        Returns
        -------
        list[dict[str, Any]]
            One row per kind of table as the server lists it: target, display name, lengths, formats and whether a
            coordinate system must be chosen.

        Raises
        ------
        VerificationFailed
            When the list does not have its documented shape.
        """
        # E91
        from . import table_templates
        return table_templates.listing(self)

    def template(self,target:str,format:str='csv',*,length:str='m',crs:str|None=None,reference=None) -> Template:
        """An empty table to fill in for one kind of table, as the server writes it.

        Parameters
        ----------
        target
            The kind of table, as `templates()` names it.
        format
            'csv' or 'xlsx'.
        length
            The length unit of the columns.
        crs
            The coordinate system, for a kind of table that needs one.
        reference
            The depth reference the wells table names in its depth column.

        Returns
        -------
        Template
            The file with `.bytes`, `.filename` and `.save(path)`.

        Raises
        ------
        Refused
            When `format` is neither 'csv' nor 'xlsx'.
        VerificationFailed
            When the file arrives empty.
        """
        # E91
        from . import table_templates
        return table_templates.template(self,target,format,length,crs,reference)

    def start_sample(self,*,command_id=None,progress=None) -> dict[str, Any]:
        """Add the start sample from NLOG to the project, a gamma-ray log and 2,222 wells.

        Only a project administrator may. The log arrives through an upload and the wells through a table import,
        each followed here to its end.

        Parameters
        ----------
        command_id
            The same id answers the same run again; None makes a new one.
        progress
            Called with the wells import's status while it is still importing.

        Returns
        -------
        dict[str, Any]
            {run_id, log, wells, statement}: the log as the upload report shows it and the wells import's final status.

        Raises
        ------
        VerificationFailed
            When the answer does not have its documented shape.
        """
        # E91
        from . import table_templates
        return table_templates.start_sample(self,command_id,progress)

    def new_data_defaults(self) -> dict[str, Any]:
        """What new files start with in this project: who sees them, their depth reference, coordinate system, units and attribution.

        Returns
        -------
        dict[str, Any]
            The five settings, their `revision`, `legacy` and whether you may change them (`administrator`); pass it
            to `set_new_data_defaults` to change them.
        """
        # E90
        from . import new_data
        return new_data.defaults(self)

    def set_new_data_defaults(self,snap,**fields) -> dict[str, Any]:
        """Change what new files start with in this project, as a project administrator.

        Parameters
        ----------
        snap
            The settings you read with `new_data_defaults()`; the change is refused when they changed since, and
            nothing is read again here.
        **fields
            The settings to change, by name.

        Returns
        -------
        dict[str, Any]
            The settings as saved, in the form `new_data_defaults()` returns.
        """
        # E90
        from . import new_data
        return new_data.set_defaults(self,snap,**fields)

    def audience(self,asset) -> dict[str, Any]:
        """Who can see a file you uploaded and who can build on it.

        Parameters
        ----------
        asset
            The uploaded original.

        Returns
        -------
        dict[str, Any]
            `state` (me, people or project), `people` with what each may do, and both generations; pass it to
            `set_audience` to change them.
        """
        # E90
        from . import new_data
        return new_data.audience(self,asset)

    def set_audience(self,snap,*,state=None,people=None,build_on=None,reason=None,command_id=None) -> dict[str, Any]:
        """Change who can see a file you uploaded and who can build on it.

        Both generations of `snap` are sent and nothing is read again: a change made since is refused.

        Parameters
        ----------
        snap
            What `audience()` returned.
        state
            'me', 'people' or 'project'; None keeps it.
        people
            The ids of the people who can see it; None keeps them.
        build_on
            The ids of the people who can build on it; None keeps them.
        reason
            Why; a narrower audience needs one, and the server's refusal says so.
        command_id
            The same id makes a retry return the first answer; None makes a new one.

        Returns
        -------
        dict[str, Any]
            Who can see it and build on it now, in the form `audience()` returns.
        """
        # E90
        from . import new_data
        return new_data.save(self,new_data.change(snap,state,people,build_on),reason,command_id)

    def rights(self,kind:str,ref:str,*,key:str|None=None) -> dict[str, Any]:
        """The recorded rights to use an uploaded file, a release or a connection target.

        `kind` is 'upload', 'release' or 'connection' (with its `key`). The answer says what they permit, their last
        day, and whether you may change them ({'basis': None, ...} when none are recorded).
        """
        # E35a
        return self._post('rights','get',_rights_target(kind,ref,key))

    def attach_rights(self,kind:str,ref:str,*,uses,last_day,key:str|None=None,delete_on_end:bool=False) -> dict[str, Any]:
        """Record the rights to use data, as a project administrator or the person who added the file.

        `uses` from 'read', 'derive', 'export', 'model-use'; `last_day` the last permitted day (a date or YYYY-MM-DD,
        UTC).
        """
        # E35a
        return self._post('rights','attach',{**_rights_target(kind,ref,key),'uses':list(uses),'last_day':str(last_day),'delete_on_end':bool(delete_on_end)})

    def renew_rights(self,kind:str,ref:str,*,uses,last_day,expected_generation,key:str|None=None,delete_on_end:bool=False) -> dict[str, Any]:
        """Record a new version of the rights you read, which everything they govern follows from then on.

        `expected_generation` is the generation you read (rights(...)['basis']['generation']); a changed generation
        raises RightsConflict.
        """
        # E35a
        return self._post('rights','renew',{**_rights_target(kind,ref,key),'uses':list(uses),'last_day':str(last_day),'delete_on_end':bool(delete_on_end),
                                            'expected_generation':expected_generation})

    def layouts(self) -> Layouts:
        """The project's layouts, by name.

        Returns
        -------
        Layouts
            List, match, save, rename, retire, use again, keep, update, reconnect, export and import
            (ophiolite.layouts.Layouts).
        """
        # E89
        from .layouts import Layouts
        return Layouts(self)

    @property
    def public_repositories(self) -> PublicRepositories:
        """Public repositories such as NLOG, to search, preview and bring data in from.

        It offers search, preview, bring_in, check and a derived result's attribution
        (ophiolite.public_repositories.PublicRepositories).
        """
        # E60
        from .public_repositories import PublicRepositories
        return PublicRepositories(self)

    @property
    def well_names(self) -> WellNames:
        """The wells your uploads and imports name: proposals, accept, aliases and go back (ophiolite.well_names.WellNames)."""
        # E88
        from .well_names import WellNames
        return WellNames(self)

    @property
    def well_sets(self) -> WellSets:
        """Your private well sets: save, new_version, list and read.

        `from_list` makes one with the trajectory version named by its label (ophiolite.well_sets.WellSets).
        """
        # E119a
        from .well_sets import WellSets
        return WellSets(self)

    @property
    def chains(self) -> ChainClient:
        """The project's chains and their runs (ophiolite.chains.ChainClient).

        Chains: declare, revise, enable, disable, withdraw, list, get, due and dismiss. Runs: run_start, run_attach,
        run_choose, run_acknowledge, run_decide, run_continue, run_get and run_list.
        """
        # E178 s2c
        return ChainClient(self)

    @property
    def figures(self) -> FigureClient:
        """The figures kept with item versions: attach, list, read, withdraw (ophiolite.figures.FigureClient)."""
        # E191 s1
        return FigureClient(self)

    @property
    def documents(self) -> DocumentClient:
        """The documents kept with wells, wellbores, surveys and the project (ophiolite.documents.DocumentClient).

        Add, list, read and describe; the server checks every file and every right."""
        # E222 s1
        return DocumentClient(self)

    @property
    def table_kinds(self) -> TableKindClient:
        """The project's kinds of table: declare, list, show (ophiolite.table_kinds.TableKindClient).

        A file exported from a version published as one is checked without the server by ophiolite.table_kinds.check.
        """
        # E203 s1
        from .table_kinds import TableKindClient
        return TableKindClient(self)

    def import_storage(self,connection,prefix=None,*,keep_copy=False,attribution,rights_confirmed,audience=(),well_notes='',declare=None,skip_decisions=False,
                       link_wellbore=False,new=False,progress=None) -> Report:
        """Add every file below a folder of a storage connection to the project in one upload.

        The server reads each file with your own sign-in; no key is given here.

        Parameters
        ----------
        connection
            The storage connection's id.
        prefix
            The folder in that storage; None is all of it.
        keep_copy
            False reads each file from your storage each time; True adds it as a copy, when the organisation
            allows copies.
        attribution
            Who the files are attributed to.
        rights_confirmed
            True: you confirm that you may keep these files, make results from them and share them with the audience.
        audience
            The people who may see the files besides you; empty is no one else.
        well_notes, declare, skip_decisions, link_wellbore, new, progress
            As `upload` takes them.

        Returns
        -------
        Report
            What happened to each file; files the server does not read are in `left_out`
            (ophiolite.upload_runs.Report).

        Raises
        ------
        ValidationFailed
            When `rights_confirmed` is not True.
        """
        # E59
        return self.upload_runs.import_storage(connection,prefix,keep_copy=keep_copy,attribution=attribution,rights_confirmed=rights_confirmed,audience=audience,
                                               well_notes=well_notes,declare=declare,skip_decisions=skip_decisions,associate_matches=link_wellbore,new=new,progress=progress)

    def well_imports(self) -> WellImports:
        """Import a copy of an approved well table as wells.

        Returns
        -------
        WellImports
            The imports of this project (ophiolite.well_imports.WellImports).
        """
        # E42a
        from .well_imports import WellImports
        return WellImports(self)

    @property
    def imports(self) -> Imports:
        """Turn a table file into wells, well tops, deviation surveys, point sets or time-depth pairs in one call.

        `client.imports.from_table(path, target, mapping, dry_run=...)` (ophiolite.imports.Imports).
        """
        # E87
        from .imports import Imports
        return Imports(self)

    def exchange(self,work,**options) -> PresentedExchange:
        """Check for updates, get the latest versions and send to the project, from a folder of your own.

        Parameters
        ----------
        work
            The folder that holds your copies.
        **options
            As ophiolite.exchange.Exchange takes them: `application` (the program that holds the copies), `codes`,
            `lock_timeout` and `sentences`.

        Returns
        -------
        PresentedExchange
            The exchange; each outcome shows itself with a link to the Workspace.
        """
        # E70a; E104: the presented outcome
        from .exchange import ClientTransport
        from .presentation import PresentedExchange  # E104: the outcome shows itself with a link to this Workspace
        return PresentedExchange(ClientTransport(self),work,origin=self.url,**options)

    def close(self) -> None:
        """Close the connection, unless you gave the client your own httpx client."""
        if self._owns_http:self.http.close()
    def __enter__(self) -> Client:return self
    def __exit__(self,*args:object) -> None:self.close()

    def _get(self,path,limit,*,ranged=None,answer=None):
        headers=self._headers()
        if ranged is not None:headers={**headers,'Range':ranged}  # E54: one byte range of an original; 206 answers it
        categories={401:(AuthenticationRequired,'Sign in again.'),403:(PermissionRefused,'Check project access and the approved grant.'),
                    404:(Unavailable,'This exact revision is unavailable or not permitted.'),409:(IntegrityConflict,'Stored data failed an integrity check. Ask the deployment administrator.'),
                    413:(CapacityExceeded,'Representation exceeds the bounded size; partial reads are not supported.'),400:(Refused,'The request was refused. Check the selected input.'),
                    422:(Incompatible,'This scientific context is not supported.'),503:(Busy,'The service is busy or unavailable.'),429:(Busy,'The service is busy or unavailable.'),
                    416:(Refused,'This byte range is outside the file.')}
        for attempt in range(3):
            try:
                with self.http.stream('GET',self.url+path,headers=headers,follow_redirects=False) as response:
                    _deprecation.note(_deprecation.of(self),'GET',self.url+path,response)
                    delay=0
                    if response.status_code in (429,503):
                        try:delay=float(response.headers.get('Retry-After','0'))
                        except ValueError:delay=0
                        if not math.isfinite(delay) or delay<0 or delay>60:delay=0
                        if attempt<2:
                            time.sleep(delay);continue
                    if response.status_code!=(200 if ranged is None else 206):
                        from . import application_transport as policy
                        meta=policy.envelope(response)  # E31: the server's code, remedy, docs and request id, read with a bound
                        kind,message=categories.get(response.status_code,(Unavailable,'Scientific read failed. Check service access and retry.'))
                        if response.status_code==422 and meta.get('message'):message=meta['message']  # H48: the server's reason, not the generic sentence
                        if kind is Busy:raise Busy(message,meta.get('remedy',''),status=response.status_code,retry_after=delay,code=meta.get('code'),**policy.carried(meta))
                        raise kind(message,meta.get('remedy',''),status=response.status_code,code=meta.get('code'),**policy.carried(meta))
                    if answer is not None:answer.update({k.lower():v for k,v in response.headers.items() if k.lower() in ('content-range','x-content-sha256','etag','x-ophiolite-access-generation','x-ophiolite-revision','content-disposition','x-ophiolite-window','x-ophiolite-piece','x-ophiolite-header-positions')})  # E100a: window validators; E58b: a file's revision and name; E141: a piece's identity; E141 s2: the header positions
                    content=bytearray()
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if len(content)>limit:raise CapacityExceeded('Scientific response exceeds its bounded size limit.')
                    return bytes(content)
            except httpx.HTTPError:
                raise Unavailable('Cannot reach the service. Check its address and network connection.',code='unreachable') from None
        raise Unavailable('The service remains unavailable.')

    def _json(self,path,limit):
        try:return json.loads(self._get(path,limit))
        except (ValueError,UnicodeError) as exc:
            # Domain errors subclass ValueError; preserve their recovery category.
            from .errors import OphioliteError
            if isinstance(exc,OphioliteError):raise
            raise VerificationFailed('Scientific response is not valid JSON.') from None

    def assets(self) -> Iterator[AssetItem]:
        """Every item in this project that you may read, one page asked at a time.

        Returns
        -------
        Iterator[AssetItem]
            Each item as the catalogue lists it: its id, exact revision, name, curves and what you may do with it.

        Raises
        ------
        VerificationFailed
            When a page or its cursor is not one the catalogue can serve.

        Example
        -------
        for item in client.assets():
            print(item['name'], item['revision'])
        """
        cursor='';seen=set()
        while True:
            page=self._json(self.prefix+'?limit=100&cursor='+quote(cursor,safe=''),2_100_000)
            if not isinstance(page,dict) or not isinstance(page.get('items'),list):raise VerificationFailed('Invalid scientific catalogue response.')
            yield from page['items'];cursor=page.get('next_cursor')
            if cursor is None or cursor=='':return
            if not isinstance(cursor,str) or len(cursor)>2000 or cursor in seen:raise VerificationFailed('Invalid or repeated catalogue cursor.')
            seen.add(cursor)

    def find_log(self,*,curves:str|Sequence[str]=(),quantity:str|None=None,name:str|None=None,operation:str='use-as-input') -> AssetItem:
        """Find the one log in this project that matches every filter you give.

        The filters combine: a log matches only when it meets all of them. Nothing is renamed and there is no alias
        table. Of several matches the one with the most samples wins (an unknown count last), then by name, then by
        item id.

        Parameters
        ----------
        curves
            Mnemonics the log must carry, compared without case.
        quantity
            A quantity one of its curves must declare; a suggested quantity never matches.
        name
            The log's exact name.
        operation
            What you must be allowed to do with it: 'read', 'export' or 'use-as-input'.

        Returns
        -------
        AssetItem
            The catalogue item, as `assets()` lists it.

        Raises
        ------
        Refused
            When no log matches (the sentence names each filter), or `operation` is not one of the three.

        Example
        -------
        log = client.find_log(curves=['GR'], operation='read')
        curves = client.read(log['asset_id'], log['revision'], ['GR'])
        """
        # E126a
        if operation not in ('read','export','use-as-input'):raise Refused('Choose read, export or use-as-input.')
        if isinstance(curves,str):curves=[curves]
        wanted={c.upper() for c in curves}
        found=sorted((item for item in self.assets() if item.get('curves') and wanted<={c.upper() for c in item['curves']}
                      and (name is None or item.get('name')==name) and operation in (item.get('allowed_operations') or [])),
                     key=lambda item:(-(item['sample_count'] if item.get('sample_count') is not None else -1),item['name'],item['asset_id']))
        for item in found:
            if quantity is None or any(self._declares(item,curve,quantity) for curve in item['curves']):return item
        given=[f'curves {list(curves)}']*bool(curves)+[f'quantity {quantity!r}']*(quantity is not None)+[f'name {name!r}']*(name is not None)
        raise Refused(f'No log you may {operation} matches '+(' and '.join(given) or 'any curve')+'.')

    def _declares(self,item,curve,quantity):
        scientific=self.describe(item['asset_id'],item['revision'],curve).scientific
        return scientific.quantity==quantity and scientific.quantity_status=='declared'

    def _path(self,asset,revision,curve):
        if not all(isinstance(x,str) and x for x in (asset,revision,curve)):
            raise Refused('Choose an asset, exact revision and value curve.')
        return self.prefix+'/'+quote(asset,safe='')+'/revisions/'+quote(revision,safe=''),'?curve='+quote(curve,safe='')

    def describe(self,asset:str,revision:str,curve:str) -> ScientificAsset:
        """What the server states about one curve of an exact version, checked, without reading its values."""
        path,query=self._path(asset,revision,curve)
        return _core.verify_descriptor(self._json(path+query+PROFILES,256*1024),self.project,asset,revision,curve)

    def provenance(self,asset:str,revision:str) -> Provenance:
        """Where one exact version came from, as the server records it.

        Parameters
        ----------
        asset
            The item's id.
        revision
            The exact version.

        Returns
        -------
        Provenance
            `words` is the server's own sentence, passed on unchanged (nothing is composed here); `record` is None for
            a version stored before records began.

        Raises
        ------
        Refused
            When the item or the version is not named.
        VerificationFailed
            When the answer is not about the version asked.
        """
        # E122 s0
        if not all(isinstance(x,str) and x for x in (asset,revision)):
            raise Refused('Choose an asset and its exact revision.')
        return _provenance_of(self._json(_provenance_path(self.prefix,asset,revision),PROVENANCE_BYTES),asset,revision)

    def _provenance_parts(self,asset,revision,state):
        """E122 s5b: the bundle's `source_record` for one exact version, or None; E182 s2b: with its `sender`, or None,
        from the same one request. `state` is one export's own: after an older gateway's router 404 (`NOT_FOUND`, no
        provenance route) no further version is asked."""
        if state.get('omitted'):return None,None
        try:found=self.provenance(asset,revision)
        except Unavailable as error:
            if not _no_provenance_route(error):raise
            state['omitted']=NO_SOURCE_RECORDS;return None,None
        return _parts_of(found)

    def read(self,asset:str,revision:str,curves:list[str]|tuple[str,...],*,strict_interpretation:bool=False,form:str|None=None) -> CurveSet:
        """Read chosen curves of one exact version, each checked against what the server stored.

        Parameters
        ----------
        asset
            The log's item id.
        revision
            The exact version.
        curves
            The curves to read, by mnemonic, each once.
        strict_interpretation
            True raises InterpretationChanged when the reading recorded at upload and today's reading of the file
            differ; False warns and reads it, with both readings in the description.
        form
            'ophiolite.well-log-curve/1' reads each curve as the well log the server stored (a WellLogSet of WellLog
            views: the declared well, depth kind, unit and datum, and the header as received); a curve without that
            form is refused with the server's reasons, and nothing falls back. None reads the curves as before.

        Returns
        -------
        CurveSet
            The curves with their descriptions and the original file.

        Raises
        ------
        Refused
            When `curves` is empty or names a curve twice, `form` is another form, or a curve has no well log form.
        InterpretationChanged
            With `strict_interpretation`, when the recorded and today's reading of the file differ.

        Example
        -------
        curves = client.read('log-id', 'revision-id', ['GR', 'DT'])
        for curve in curves.curves:
            print(curve.curve, len(curve.values))
        """
        # E183 s2c: form
        if not isinstance(curves,(list,tuple)) or not curves or len(set(curves))!=len(curves):
            raise Refused('Choose distinct value curves explicitly.')
        if form is not None:return self._read_well_logs(asset,revision,curves,form,strict_interpretation)
        descriptors=[];views=[];artifact=None;wire_descriptors=[];wire_curves=[];wire_curve_bytes=[]
        for curve in curves:
            path,query=self._path(asset,revision,curve)
            data=self._json(path+query+PROFILES,256*1024)
            _core.refuse_windows_only(_core.verify_descriptor(data,self.project,asset,revision,curve))
            raw=_core.rules.artifact(data)
            normalized=next(r for r in data['representations'] if r['kind']=='normalized')
            if artifact is None:artifact=self._artifact(path+'/representations/'+quote(raw['id'],safe='')+query,raw['bytes'])
            _core.verify_bytes(raw,artifact)
            body=self._get(path+'/representations/'+quote(normalized['id'],safe='')+query,normalized['bytes'])
            model,view=_core.verify_pair(data,body,artifact,curve,strict_interpretation=strict_interpretation)
            descriptors.append(model);views.append(view)
            wire_descriptors.append(data);wire_curves.append(json.loads(body));wire_curve_bytes.append(body)
        result=CurveSet(descriptors,views,artifact,url=self.url,project=self.project,wire_descriptors=wire_descriptors,wire_curves=wire_curves,wire_curve_bytes=wire_curve_bytes)
        result._client=self  # E126a: ophiolite.lasio.to_lasio names the well linked to this revision
        return result

    def _read_well_logs(self,asset,revision,curves,form,strict_interpretation):
        """E183 s2c: `read(..., form=)`. The descriptor is asked with the gateway's `form`; its one normalized row is the
        stored `well-log-curve:<key>`, read and verified (`_core.verify_well_log`). A 422 is Refused with the gateway's
        sentence verbatim (`server_message` too); the application curve is never requested."""
        from .scientific import WellLog
        if form!=WELL_LOG_FORM:raise Refused(FORM_CHOICE)
        descriptors=[];views=[];artifact=None;wire_descriptors=[];wire_curves=[];wire_curve_bytes=[]
        for curve in curves:
            path,query=self._path(asset,revision,curve)
            try:data=self._json(path+query+'&form='+quote(form,safe='')+PROFILES,256*1024)
            except Incompatible as error:
                raise Refused(error.message,error.recovery,status=error.status,code=error.code,remedy=error.remedy,docs=error.docs,
                              request_id=error.request_id,server_message=error.message) from None
            _core.refuse_windows_only(_core.verify_descriptor(data,self.project,asset,revision,curve))
            raw=_core.rules.artifact(data)
            normalized=next(r for r in data['representations'] if r['kind']=='normalized')
            _core.well_log_row(normalized,curve)  # before any representation is asked for: never the application curve
            if artifact is None:artifact=self._artifact(path+'/representations/'+quote(raw['id'],safe='')+query,raw['bytes'])
            _core.verify_bytes(raw,artifact)
            body=self._get(path+'/representations/'+quote(normalized['id'],safe='')+query,normalized['bytes'])
            model,view=_core.verify_well_log(data,body,artifact,curve,strict_interpretation=strict_interpretation)
            descriptors.append(model);views.append(WellLog(view))
            wire_descriptors.append(data);wire_curves.append(json.loads(body));wire_curve_bytes.append(body)
        result=WellLogSet(descriptors,views,artifact,url=self.url,project=self.project,wire_descriptors=wire_descriptors,wire_curves=wire_curves,wire_curve_bytes=wire_curve_bytes)
        result._client=self
        return result

    def _artifact(self,path,size):
        """E100d1: an original above the whole-answer bound is read by ranges (the caller verifies its digest)."""
        if size<=_ranges.WHOLE_BYTES:return self._get(path,size)
        parts,out=_ranges.Parts(size=size),bytearray()
        while parts.pending():
            answer={}
            out.extend(parts.accept(self._get(path,parts.part_bytes,ranged=parts.range(),answer=answer),answer))
        return bytes(out)

    def curve_window(self,asset:str,revision:str,curve:str,top:float,base:float,*,level:int|None=None,rows:int|None=None,max_pages:int=64) -> CurveWindow:
        """The part of one exact curve between two depths, for display (ophiolite.windows.CurveWindow).

        Give exactly one of `level` (0 = every sample, exact; 1..17 = blocks of up to 2**level samples with
        their extrema) or `rows` (the server picks the finest level that fits). Pages are followed until the
        window is complete, at most `max_pages`; each is verified against this curve's descriptor.
        """
        # E100a
        from .windows import Window,PAGE_BYTES
        window=Window(self.project,asset,revision,curve,top,base,level,rows,max_pages)
        path,query=self._path(asset,revision,curve)
        data=self._json(path+query+PROFILES,256*1024)
        _core.verify_descriptor(data,self.project,asset,revision,curve);window.bind(data)
        while True:
            answer={}
            if not window.accept(self._get(window.path(path),PAGE_BYTES,answer=answer),answer):return window.result()

    def read_data(self,asset:str,revision:str) -> TypedData:
        """Read well tops, a trajectory, a surface or another kind of data at one exact version, checked.

        A seismic volume is described here and not downloaded; `read_slice` and `read_window` read its samples.

        Parameters
        ----------
        asset
            The item's id.
        revision
            The exact version.

        Returns
        -------
        TypedData
            The data in its own kind's form (ophiolite.typed), with its description and the original file.

        Raises
        ------
        Refused
            When the item or the version is not named.

        Example
        -------
        tops = client.read_data('tops-id', 'revision-id')
        print(type(tops).__name__)
        """
        # E11; E16: a volume is described only
        if not all(isinstance(x,str) and x for x in (asset,revision)):raise Refused('Choose an asset and exact revision.')
        path=self.prefix+'/'+quote(asset,safe='')+'/revisions/'+quote(revision,safe='')
        data=self._json(path+'?'+PROFILES[1:],256*1024)
        _core.verify_typed_descriptor(data,self.project,asset,revision)
        raw=_core.rules.artifact(data)
        normalized=next(r for r in data['representations'] if r['kind']=='normalized')
        # E16: a seismic volume is described, never downloaded here; read_slice reads its samples.
        # E139 s2: above the whole-answer bound (a point set's columns or its original) both are read by ranges
        artifact=None if data['scientific'].get('type')=='seismic-volume' else self._artifact(path+'/representations/'+quote(raw['id'],safe=''),raw['bytes'])
        body=self._artifact(path+'/representations/'+quote(normalized['id'],safe=''),normalized['bytes'])
        result=_core.typed_result(data,body,artifact)
        result._client=self  # E58b: a kept table downloads itself as a file
        return result

    def export_file(self,asset:str,revision:str,destination:str|os.PathLike[str],*,format:str='parquet',curves:list[str]|tuple[str,...]|None=None) -> Path:
        """Save one exact version as a single Parquet, GeoParquet or CSV file, written by the server.

        The server writes it from what it stored for that version: a kept table, well tops, a trajectory, a point set
        (GeoParquet) or a LAS log. The file's own `ophiolite.export` metadata names the version, the units and the
        missing-value markers. No pyarrow is needed to download. A version published as a kind of table carries the
        kind's declaration and digest in a Parquet file; a CSV file gets it beside it, as `<file>.table-kind.json`.
        `ophiolite data table-kinds check FILE` checks either without the server.

        Parameters
        ----------
        asset
            The item's id.
        revision
            The exact version.
        destination
            Where the file is saved.
        format
            'parquet', 'geoparquet' (point sets) or 'csv'.
        curves
            For a LAS log, the curves to write; None writes every stored curve.

        Returns
        -------
        Path
            The saved file.

        Raises
        ------
        Refused
            When the item, the version, the format or the curves are not given as above.
        VerificationFailed
            When the server wrote the file from another version; nothing is saved.
        IntegrityConflict
            When the file does not match the digest the server stated; nothing is saved.
        """
        # E58b; E203 s1: the kind of table beside a CSV file
        if not all(isinstance(x,str) and x for x in (asset,revision)):raise Refused('Choose an asset and exact revision.')
        if format not in FILE_FORMATS:raise Refused('Download as one of %s.' % ', '.join(FILE_FORMATS))
        if curves is not None and (isinstance(curves,str) or not all(isinstance(c,str) and c for c in curves)):raise Refused('Give curves as a list of curve names.')
        query='format='+format+''.join('&curves='+quote(c,safe='') for c in curves or ())
        answer={}
        raw=self._get(self.prefix+'/'+quote(asset,safe='')+'/revisions/'+quote(revision,safe='')+'/export?'+query,FILE_BYTES,answer=answer)
        if answer.get('x-ophiolite-revision')!=revision:
            raise VerificationFailed('The server wrote the file from another revision than the one asked for; nothing was saved.')
        kind=self._exported_kind(asset,revision) if format=='csv' else None
        saved=save_verified(destination,written(raw,answer.get('x-content-sha256')))
        if kind is not None:Path(str(saved)+'.table-kind.json').write_text(json.dumps(kind,indent=1,ensure_ascii=False)+'\n',encoding='utf-8')
        return saved

    def _exported_kind(self,asset,revision):
        """E203 s1 (D5): the `<file>.table-kind.json` of a CSV export of a version published as a kind of table: the
        reference its story node records, that version of the kind (checked against its digest) and the columns as the
        file is written; None for any other version."""
        from . import table_kinds
        nodes=self.story(asset,revision).get('nodes') or []
        ref=next((n.get('table_kind') for n in nodes if (n.get('asset_id'),n.get('revision'))==(asset,revision)),None)
        if not ref:return None
        shown=self._post('table-kinds','show',{'word':ref['word'],'version':ref['version']},retry=True)
        try:block=table_kinds.block_of({**{k:ref[k] for k in table_kinds.REF},'declaration':shown.get('declaration')})
        except table_kinds.Unreadable:raise VerificationFailed('The kind of table this version was published as answered another declaration; nothing was saved.') from None
        if shown.get('id')!=block['id']:raise VerificationFailed('The kind of table this version was published as answered another declaration; nothing was saved.')
        table=self.read_data(asset,revision)
        notes=table.declarations.get('columns') or {}
        columns=[{'name':c['name'],'logical':c['logical'],**{k:v for k,v in (notes.get(c['name']) or {}).items() if k in ('unit','missing') and v is not None}}
                 for c in table.columns if c['read']]
        return table_kinds.sidecar(block,columns)

    def read_window(self,asset:str,revision:str,*,inline=None,crossline=None,trace=None,sample=None,by:str|None=None,description=None) -> VolumeWindowResult:
        """Read part of a seismic volume or of a 2D line at one exact version, checked piece by piece.

        Ranges are n, (first, last) or 'first:last', both ends included. The window is checked before any piece is
        asked, and each piece against its headers and digest. The whole window is held decoded (about 8-9 x its
        stored bytes); `iter_window` holds one piece at a time.

        Parameters
        ----------
        asset
            The volume's or line's item id.
        revision
            The exact version.
        inline, crossline
            A volume's range of inlines and crosslines; each needs `by`.
        trace
            A line's range of traces, by position in file order.
        sample
            The range of samples.
        by
            'label' (the numbers in the trace headers) or 'ordinal' (positions), for inline and crossline.
        description
            A previous result's `.description` of the same version, to skip asking for it again.

        Returns
        -------
        VolumeWindowResult
            `.values` in C order, `.window_digest` and `.to_numpy()` (ophiolite.volume_windows).

        Raises
        ------
        WindowRefused
            When the range is not well formed or the server refuses the window, with its reason.
        Refused
            When the item or the version is not named.
        """
        # E141
        reader=self.iter_window(asset,revision,inline=inline,crossline=crossline,trace=trace,sample=sample,by=by,description=description)
        from .volume_windows import VolumeWindowResult
        traces=[]
        for piece in reader:traces.extend(piece.values)
        return VolumeWindowResult(reader.window,traces)

    def iter_window(self,asset:str,revision:str,*,inline=None,crossline=None,trace=None,sample=None,by:str|None=None,description=None) -> WindowReader:
        """Read the window `read_window` reads, one checked piece at a time.

        The window is asked and checked now; each piece when you iterate, asked once more after a network failure.

        Parameters
        ----------
        asset, revision, inline, crossline, trace, sample, by, description
            As `read_window` takes them.

        Returns
        -------
        WindowReader
            An iterator of WindowPiece(index, count, traces, values); `.complete` and `.window_digest` once the last
            piece is checked (ophiolite.volume_windows).

        Raises
        ------
        WindowRefused
            When the range is not well formed or the server refuses the window, with its reason.
        Refused
            When the item or the version is not named.
        """
        # E141
        from .volume_windows import Window,WindowReader,asked,check_document,parse_window,window_path
        if not all(isinstance(x,str) and x for x in (asset,revision)):raise Refused('Choose an asset and exact revision.')
        query=parse_window(inline=inline,crossline=crossline,trace=trace,sample=sample,by=by)
        base=window_path(self.prefix,asset,revision)
        description=self._window_description(asset,revision,description)  # E140 s3: first, so a native cube asks windows=2 (R5)
        request=asked(query,description)
        document=self._window_json(base+('?'+urlencode(request) if request else ''))
        return WindowReader(self,Window(check_document(document,asset=asset,revision=revision,query=query,description=description),query,description,base))

    def _window_get(self,path,limit,answer=None):
        """A window read: a server `window-refused` answer raises WindowRefused with its reason and sentence."""
        from .volume_windows import server_refusal
        try:return self._get(path,limit,answer=answer)
        except OphioliteError as error:
            refused=server_refusal(error)
            if refused is not None:raise refused from None
            raise

    def _window_json(self,path):
        from .volume_windows import DOCUMENT_BYTES
        try:return json.loads(self._window_get(path,DOCUMENT_BYTES))
        except (ValueError,UnicodeError) as exc:
            if isinstance(exc,OphioliteError):raise
            raise VerificationFailed('The window document is not valid JSON.') from None

    def _window_description(self,asset,revision,description):
        """What the window's axes are checked against: the volume's described context, or the line's stored description
        (representations/data, verified against its digest); the original is never asked."""
        from .volume_windows import WindowDescription,describe_line,describe_volume,line_representation
        if description is not None:
            if not isinstance(description,WindowDescription) or (description.asset,description.revision)!=(asset,revision):raise Refused('description= is a window description of this exact revision.')
            return description
        path=self.prefix+'/'+quote(asset,safe='')+'/revisions/'+quote(revision,safe='')
        descriptor=self._window_descriptor(asset,revision)
        found=describe_volume(asset,revision,descriptor)
        if found is not None:return found
        rep=line_representation(descriptor)
        raw=self._artifact(path+'/representations/'+quote(rep['id'],safe=''),rep['bytes'])
        _core.verify_bytes(rep,raw)
        return describe_line(asset,revision,raw)

    def _window_descriptor(self,asset,revision):
        """The verified typed descriptor of an exact revision (metadata only; no representation is asked)."""
        path=self.prefix+'/'+quote(asset,safe='')+'/revisions/'+quote(revision,safe='')
        descriptor=self._json(path+'?'+PROFILES[1:],256*1024)
        _core.verify_typed_descriptor(descriptor,self.project,asset,revision)
        return descriptor

    def _window_file_header(self,base,query,document):
        """E141 s2 (D-H): the original's 3,600-byte file header for a checked window, with the answer's headers (its
        identity, digest and X-Ophiolite-Header-Positions); checked by volume_windows.check_file_header."""
        from .volume_windows import FILE_HEADER
        answer={}
        body=self._window_get(base+'/file-header?'+urlencode(list(query)+[('window',document['window_id'])]),FILE_HEADER,answer)
        return body,answer

    def _window_headers(self,base,query,document,index,length):
        """E141 s2 (D-H): headers answer `index` of a checked window (`length` bytes: 240 per trace), with its headers;
        checked by volume_windows.check_headers."""
        answer={}
        body=self._window_get(base+'/headers/%d?' % index+urlencode(list(query)+[('window',document['window_id'])]),length,answer)
        return body,answer

    def read_slice(self,asset:str,revision:str,axis:str,label:int,*,volume=None) -> SeismicSlice:
        """Read one slice of a seismic volume at one exact version, checked against the volume's description.

        Only the parts holding the slice are read on the server.

        Parameters
        ----------
        asset
            The volume's item id.
        revision
            The exact version.
        axis
            'inline', 'crossline' or 'sample'.
        label
            The inline or crossline number from the trace headers, or the sample number counted from 0.
        volume
            The volume as `read_data` returned it, to read its description once for many slices.

        Returns
        -------
        SeismicSlice
            The slice's values with its place in the volume (ophiolite.typed).

        Raises
        ------
        Refused
            When `axis` or `label` is not one of the above, or the item is not a seismic volume at this version.
        """
        # E16
        volume=self._volume(asset,revision,axis,label,volume)
        path=self.prefix+'/'+quote(asset,safe='')+'/revisions/'+quote(revision,safe='')+'/slices/'+quote(axis,safe='')+'/'+str(label)
        return _core.slice_result(volume,self._get(path,32*1024*1024),asset,revision,axis,label)

    def _volume(self,asset,revision,axis,label,volume):
        if axis not in ('inline','crossline','sample') or type(label) is not int:raise Refused('Choose an inline, crossline or sample slice by its whole number.')
        if volume is None:volume=self.read_data(asset,revision)
        if getattr(volume,'type',None)!='seismic-volume' or (volume.descriptor.asset_id,volume.descriptor.revision)!=(asset,revision):raise Refused('Slices come from a seismic volume at this exact revision.')
        return volume

    def export_slices(self,asset:str,revision:str,slices,destination:str|os.PathLike[str]) -> Bundle:
        """Export chosen slices of one exact version of a seismic volume into a new portable bundle.

        The bundle carries the volume's description and each slice; the original volume is named by its digest and
        not included.

        Parameters
        ----------
        asset
            The volume's item id.
        revision
            The exact version.
        slices
            [(axis, label), ...], 1 to 64 slices, each once, as `read_slice` takes them.
        destination
            The new bundle's folder.

        Returns
        -------
        Bundle
            The bundle, opened once it checks as a reader would.

        Raises
        ------
        Refused
            When the slices are not 1 to 64 distinct slices of a seismic volume.
        """
        # E16: bundle 2.3
        from .bundle import write_bundle
        chosen=self._slice_choice(slices)
        volume=self.read_data(asset,revision)
        read=[self.read_slice(asset,revision,axis,label,volume=volume) for axis,label in chosen]
        state={}
        volume.source_record,volume.sender=self._provenance_parts(asset,revision,state)  # E122 s5b; E182 s2b
        _warn_source_records_omitted(state.get('omitted'))
        return write_bundle(destination,[({'asset_id':asset,'revision':revision,'curves':[],'slices':[{'axis':a,'label':l} for a,l in chosen]},(volume,read))],
                            source_records_omitted=state.get('omitted'))

    @staticmethod
    def _slice_choice(slices):
        if not isinstance(slices,(list,tuple)) or not slices or len(slices)>64:raise Refused('Choose between 1 and 64 slices.')
        chosen=[tuple(s) for s in slices]
        if len(set(chosen))!=len(chosen):raise Refused('Each slice is chosen once.')
        return chosen

    def read_many(self,selections,**options) -> list[CurveSet]:
        """Read several exact versions' curves, one `read` each, in the order given.

        Parameters
        ----------
        selections
            [(asset, revision, curves), ...].
        **options
            As `read` takes them, for every read.

        Returns
        -------
        list[CurveSet]
            One per selection.
        """
        return [self.read(asset,revision,curves,**options) for asset,revision,curves in selections]

    def export(self,selections,destination:str|os.PathLike[str],*,groups:bool=True,entities:bool=True,citation=None) -> Bundle:
        """Export exact versions into a new portable bundle that anyone can check without the server.

        Every item is read through the ordinary exact read, so the server's current permissions apply to each one;
        one refusal fails the whole export and nothing is written. The bundle becomes visible only after it checks as
        a reader would.

        Parameters
        ----------
        selections
            [(asset, revision, [curves] or None), ...]; None for data without curves (well tops, trajectories,
            surfaces). A seismic volume is exported with `export_slices`.
        destination
            The new bundle's folder.
        groups
            True includes the result groups the items belong to.
        entities
            True includes the wells and wellbores the items name.
        citation
            {title, description[, version]} makes a cited bundle: the creators are the people the versions' stories
            name, the publisher the project's organisation and the licence the files' one open licence, or a notice.

        Returns
        -------
        Bundle
            The opened bundle.

        Raises
        ------
        Refused
            When nothing is chosen, or a selection is a whole seismic volume.
        """
        # E147 s2: citation (bundle 2.15); E11: items without curves
        from .bundle import write_bundle
        from . import export_citation
        if not isinstance(selections,(list,tuple)) or not selections:raise Refused('Choose at least one exact revision to export.')
        if citation is not None:  # E147 s2 (D1-D3): the words first, then the organisation and the makers, before any read
            words=export_citation.given(citation);organisation=export_citation.publisher(self)
            makers=export_citation.creators(export_citation.stories(self,selections),organisation)
        items=[];state={}  # E122 s5b: this export's own record state, never the client's
        copies=None  # E162 s2a: the kept copies, listed only once an exact read refuses
        for asset,revision,curves in selections:
            if not curves:  # E11: well tops, trajectories and grids have no curves (bundle 2)
                try:read=self.read_data(asset,revision)
                except Incompatible as error:  # the exact read does not serve a kept wells table (422); every other refusal stays as it was
                    if copies is None:
                        from .well_sources import KeptCopies
                        copies=KeptCopies(self)
                    items.append(({'asset_id':asset,'revision':revision,'curves':[]},self._kept_well_table(asset,revision,copies,error)));continue
                if read.type=='seismic-volume':raise Refused('A seismic volume is exported as chosen slices (export_slices); the complete volume is not exported.')
                if read._wire_descriptor.get('package') is not None:read.package_rows=self._package_rows(asset,revision,read._wire_descriptor)  # E23c (C4)
                read.provenance=self._kept_original(asset,revision,read._wire_descriptor)  # E107a C6b
                read.source_record,read.sender=self._provenance_parts(asset,revision,state)  # E122 s5b; E182 s2b
                items.append(({'asset_id':asset,'revision':revision,'curves':[]},read));continue
            read=self.read(asset,revision,list(curves))
            read.provenance=self._kept_original(asset,revision,read._wire_descriptors[0])  # E107a C6b
            read.source_record,read.sender=self._provenance_parts(asset,revision,state)  # E122 s5b; E182 s2b
            items.append(({'asset_id':asset,'revision':revision,'curves':list(curves)},read))
        _warn_source_records_omitted(state.get('omitted'))
        found,omitted=self._bundle_groups(items) if groups else (None,None)
        graph,left_out=self._bundle_graph(items) if entities else (None,'not requested')
        if left_out and left_out!='not requested':
            import warnings
            warnings.warn('Wells and wellbores were left out of this bundle: '+left_out+'.',UserWarning,stacklevel=2)
        cited=None
        if citation is not None:  # E147 s2 (D4): the licence from the files read
            licence,notice=export_citation.licence_of(items)
            cited=export_citation.check(export_citation.complete(words,creators=makers,publisher=organisation,licence=licence,notice=notice))
        return write_bundle(destination,items,groups=found,groups_omitted=omitted,graph=graph,entities_omitted=left_out,
                            source_records_omitted=state.get('omitted'),citation=cited)

    def _kept_well_table(self,asset,revision,copies,error):
        """E162 s2a (bundle 2.17): the wells table a wells import kept (sql-wells/1), which the exact read does not serve:
        its bytes as kept and its source manifest as served, read through the package routes (ophiolite.well_sources)
        and verified (bundle.WellTable). For anything else the exact read's own ERROR is raised unchanged."""
        from .bundle import WellTable,WELL_TABLE_PROFILE
        try:found=copies.captures().get(asset)
        except OphioliteError:found=None
        if found is None:raise error
        got=copies.kept(asset,revision)
        if isinstance(got,str):raise Refused(got+' Nothing was written.')
        payload,row=got
        source=row.get('source') if isinstance(row,dict) else None
        if not isinstance(source,dict) or (source.get('reference') or {}).get('profile')!=WELL_TABLE_PROFILE:raise error
        return WellTable(payload,source,row.get('name'))

    def _kept_original(self,asset,revision,descriptor):
        """E107a C6b (B1): the original a file read on a computer was read from, when it was kept: the revision manifest
        lists a `provenance` row. Read with the caller's own credential right after the data (a grant revoked in between
        fails the export) and checked against that row; None when nothing was kept."""
        from .errors import IntegrityConflict
        listed={r['id']:(r['sha256'],r['bytes']) for r in (descriptor.get('manifest') or {}).get('representations',[])}
        if 'provenance' not in listed:return None
        path=self.prefix+'/'+quote(asset,safe='')+'/revisions/'+quote(revision,safe='')
        raw=self._get(path+'/representations/provenance',listed['provenance'][1])
        if (hashlib.sha256(raw).hexdigest(),len(raw))!=listed['provenance']:
            raise IntegrityConflict('The original kept beside this revision is not the one its record names. Nothing was written.')
        return raw

    def _package_rows(self,asset,revision,descriptor):
        """E23c (C4): the rows a package read travels with in a bundle (package manifest, interpretation, each companion's exact
        bytes), read right after the data with the caller's own credential and the same authorization as the artifact, so a grant
        revoked in between fails the export. Each row is checked against the record the descriptor names: a companion against its
        member record, the package and interpretation rows against the revision manifest listing when there is one."""
        from .bundle import MAX_FILE_BYTES
        from .bundle_package import rows_needed
        from .errors import IntegrityConflict
        path=self.prefix+'/'+quote(asset,safe='')+'/revisions/'+quote(revision,safe='')
        listed={r['id']:(r['sha256'],r['bytes']) for r in (descriptor.get('manifest') or {}).get('representations',[])}
        records={'companion:'+m['name']:(m['sha256'],m['bytes']) for m in descriptor['package']['members']}
        rows={}
        for ident in rows_needed(descriptor):
            expected=records.get(ident) or listed.get(ident)
            raw=self._get(path+'/representations/'+quote(ident,safe=''),expected[1] if expected else MAX_FILE_BYTES)
            if expected is not None and (hashlib.sha256(raw).hexdigest(),len(raw))!=expected:
                raise IntegrityConflict('A package file of this revision is not the one its record names. Nothing was written.')
            rows[ident]=raw
        return rows

    def _bundle_graph(self,items):
        """E20: the wells and wellbores (you may read) that exported revisions belong to, their wells one
        part-of hop up, and those associations with their evidence, with why none travel when they
        cannot (E22b: recorded in the bundle, never silent). (None, None) when there are none."""
        from .errors import Unavailable,PermissionRefused
        selected={(chosen['asset_id'],chosen['revision']) for chosen,_ in items}
        try:visible={e.entity_id:e for e in self.entities()}
        except PermissionRefused:return None,'this sign-in may not read wells and wellbores'
        except Unavailable as error:
            if getattr(error,'status',None)==404:return None,'this server has no wells and wellbores'
            raise
        included,edges={},[]
        for e in visible.values():
            for item in self.data(e):
                if (item['asset_id'],item['revision']) in selected:
                    included[e.entity_id]=e
                    edges.append({'predicate':'of-entity','subject':{'kind':'revision','asset_id':item['asset_id'],'revision':item['revision'],**({'row':item['row']} if item.get('row') else {})},  # E29: the row of a table of wells
                                  'object':{'kind':e.kind,'entity_id':e.entity_id},'evidence':item['association']['evidence']})
        for e in list(included.values()):
            link=e.document.get('part_of')
            if e.kind=='wellbore' and link and link['entity_id'] in visible:
                included[link['entity_id']]=visible[link['entity_id']]
                edges.append({'predicate':'part-of','subject':{'kind':'wellbore','entity_id':e.entity_id},'object':{'kind':'well','entity_id':link['entity_id']},
                              'evidence':None})  # the statement stays with the deployment; the link is what the bundle records
        if not included:return None,None
        entities=[{k:e.document[k] for k in ('entity_id','kind','name','identity')} for e in sorted(included.values(),key=lambda x:x.entity_id)]
        return {'entities':entities,'relationships':sorted(edges,key=lambda r:json.dumps(r,sort_keys=True))},None

    def _bundle_groups(self,items):
        """Result groups (as this account sees them now) that contain selected results, by bundle position."""
        from datetime import datetime,timezone
        selected=[(chosen['asset_id'],chosen['revision']) for chosen,_ in items]
        if not any(getattr(read,'descriptors',None) and read.descriptors[0].origin=='managed-derived' for _,read in items):return None,None
        from .errors import Unavailable,PermissionRefused
        try:groups=self.result_groups()
        except Unavailable as error:
            if getattr(error,'status',None)==404:return None,'This server does not offer result groups'
            raise
        except PermissionRefused:return None,'This credential may not list result groups'  # stated in the bundle, never silently empty
        observed=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ');out=[]
        for g in groups:
            members=[i for i,(asset,_) in enumerate(selected) if asset in {m.asset_id for m in g.members}]
            if not members:continue
            rec=g.recommended;recommended=None
            if rec and rec.asset_id and (rec.asset_id,rec.revision) in selected:
                recommended={'asset_position':selected.index((rec.asset_id,rec.revision)),'revision':rec.revision,'by':rec.by,'at':float(rec.at),'reason':rec.reason}
            out.append({'name':g.name,'observed_at':observed,'meaning':'observation-at-export','members':members,'recommended':recommended})
        return out or None,None

    def _headers(self):
        return _client_header.stamp(self.credential.headers(self.url,self.project) if self.credential else {},self._sender)  # E93, E182 s1

    def _post_bytes(self,area,operation,raw,*,extra_headers=None,headers=None,retry=False,expected_context=None,timeout=None,answer_bytes=False):
        from . import publish as planning,application_transport as policy
        from .errors import RecoveryUnavailable
        url,project=self.url,self.project
        if expected_context is not None and (url,project)!=expected_context:raise RecoveryUnavailable('The gateway or project changed during this operation.')
        path=planning.operation_path(project,area,operation)
        if extra_headers and any(key.lower() not in ('content-type','x-ophiolite-upload') for key in extra_headers):raise Refused('Saved request headers cannot replace authorization.')
        captured=_client_header.stamp(self._headers() if headers is None else headers,self._sender)
        captured.update(extra_headers or {'Content-Type':'application/json'})
        attempts=3 if operation!='share' and (retry or operation in planning.READ_OPERATIONS) else 1
        for attempt in range(attempts):
            if (self.url,self.project)!=(url,project):raise RecoveryUnavailable('The gateway or project changed during this operation.')
            try:
                with self.http.stream('POST',url+path,content=raw,headers=captured,follow_redirects=False,**({'timeout':timeout} if timeout else {})) as response:
                    _deprecation.note(_deprecation.of(self),'POST',url+path,response)
                    refusal=None if response.is_success else policy.head_bytes(response)
                    if response.status_code in (429,503) and attempt+1<attempts and policy.retried(response,refusal):
                        time.sleep(policy.delay(response));continue
                    policy.status(response,operation,refusal)
                    content=bytearray()
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if len(content)>policy.MAX_RESPONSE:raise policy.too_large()
                    return bytes(content) if answer_bytes else policy.decode(bytes(content))  # E91: a template is a file, never decoded
            except httpx.HTTPError:
                if attempt+1<attempts:continue
                policy.disconnected(operation)

    def _post_file(self,area,operation,body,answer):
        """E58b: an operation that answers a file: its bytes (bounded), with its revision, digest and name in `answer`.
        A refusal is raised exactly as for any operation, and no bytes are returned with it."""
        from .publish import json_bytes,operation_path
        from . import application_transport as policy
        raw=json_bytes({'project_id':self.project,**body});path=self.url+operation_path(self.project,area,operation)
        headers={**_client_header.stamp(self._headers(),self._sender),'Content-Type':'application/json'}
        for attempt in range(3):
            try:
                with self.http.stream('POST',path,content=raw,headers=headers,follow_redirects=False) as response:
                    _deprecation.note(_deprecation.of(self),'POST',path,response)
                    refusal=None if response.is_success else policy.head_bytes(response)
                    if response.status_code in (429,503) and attempt<2 and policy.retried(response,refusal):
                        time.sleep(policy.delay(response));continue
                    policy.status(response,operation,refusal)
                    answer.update({k.lower():v for k,v in response.headers.items() if k.lower() in ('x-content-sha256','x-ophiolite-revision','content-disposition','content-type')})
                    content=bytearray()
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if len(content)>FILE_BYTES:raise CapacityExceeded('The file exceeds its bounded size; nothing was saved.')
                    return bytes(content)
            except httpx.HTTPError:
                if attempt<2:continue
                policy.disconnected(operation)

    def _post(self,area,operation,body,**options):
        from .publish import json_bytes,MAX_REQUEST_BYTES,CHECK_REQUEST_BYTES,FIGURE_REQUEST_BYTES
        if 'project_id' in body and body['project_id']!=self.project:raise Refused('The request belongs to another project.')
        limit=CHECK_REQUEST_BYTES if (area,operation) in (('checks','publish'),('checks','compare')) else FIGURE_REQUEST_BYTES if (area,operation) in (('attachments','add'),('documents','add')) else MAX_REQUEST_BYTES
        return self._post_bytes(area,operation,json_bytes({'project_id':self.project,**body},limit),**options)

    def configure(self,asset:str|None=None,revision:str|None=None,*,curve:str,name:str,command_id:str|None=None,publication_profile:str='las-derived-curves/1',release_id=None,asset_index:int=0,runners=None) -> Binding:
        """Configure an application's run on one exact curve, as a binding.

        Without a WorkFolder this is not recoverable after a restart.
        """
        import uuid
        from . import publish as planning
        from .models.api import Binding
        body=planning.configure_body(asset,revision,curve,name,command_id or uuid.uuid4().hex,publication_profile=publication_profile,release_id=release_id,asset_index=asset_index,runners=runners)
        return planning.verify_application_reply('configure',body,self._post('applications','configure',body),self.project,self)

    def start(self,binding,*,application_version,parameters,command_id:str|None=None) -> Run:
        """Start a run of a binding with the application version and parameters you give.

        Without a WorkFolder this is not recoverable after a restart.
        """
        import uuid
        from . import publish as planning
        body=planning.start_body(binding,command_id or uuid.uuid4().hex,application_version,parameters)
        return planning.verify_application_reply('start',body,self._post('applications','start',body),self.project,self)

    def run_input(self,run) -> tuple[bytes, ApplicationCurve]:
        """The original file and the curve a run reads, each checked against what the run names."""
        from . import publish as planning
        from .models.generated import ApplicationCurve
        result=self._post('applications','original',{'id':run.id})
        if result.get('source')!=run.input_reference.model_dump():raise VerificationFailed('The run input refers to another source.')
        original=planning.decode_payload(result,sha256=run.input_sha256)
        value=self._post('applications','read',{'id':run.id})
        view=planning.parse(ApplicationCurve,value);_core.rules.curve(value)
        if view.source_sha256!=run.input_sha256 or view.source.model_dump()!=run.input_reference.model_dump() or view.curve!=run.binding.curve:
            raise VerificationFailed('The run input refers to another source or selected curve.')
        run._view_wire=value
        run._original,run._view=original,view
        run._original_reference={k:v for k,v in result.items() if k!='payload_base64'}
        return original,view

    def publish(self,run,*,derived_curves=None,changes=None,new_version_of=None) -> Receipt:
        """Publish the values you reviewed for a run as a result.

        Without a WorkFolder this is not recoverable after a restart.

        Parameters
        ----------
        run
            The run whose input you read with `run_input`.
        derived_curves
            The curves you derived (a run configured for 'las-derived-curves/1'); give this or `changes`.
        changes
            The sample changes you made (a run configured for 'curve-edits/1'); give this or `derived_curves`.
        new_version_of
            A receipt or exact result you author, or one your project lets you add versions to: the values become
            its next version, with its revision as the expected parent.

        Returns
        -------
        Receipt
            What was published.

        Raises
        ------
        Refused
            When the run's input was not read first, or the values do not fit how the run was configured.
        ValidationFailed
            When both or neither of `derived_curves` and `changes` are given, or they do not check.
        VerificationFailed
            When the input or the publication names another input than the run's.
        """
        # E70c: a version of a colleague's result
        from . import publish as planning
        if run._original is None or run._view is None:raise Refused('Read the exact run input before validating and publishing values.')
        body=planning.publication_body(run,run._original,run._view,derived_curves=derived_curves,changes=changes,new_version_of=new_version_of)
        published=planning.verify_application_reply('publish',body,self._post('applications','publish',body),self.project,self)
        if published.input_reference!=run.input_reference or published.input_sha256!=run.input_sha256:raise VerificationFailed('Publication changed the resolved scientific input.')
        return published.receipt

    def download(self,receipt) -> bytes:
        """The published file of a receipt, checked against the digest and size the receipt names."""
        from . import publish as planning
        result=self._post('applications','download',{'id':receipt.publication_id})
        return planning.decode_payload(result,sha256=receipt.manifest.sha256,length=receipt.manifest.bytes)

    def results(self) -> list[ResultSummary | RestrictedResultSummary]:
        """The results in this project you may see, each with only what you may open of it."""
        from . import publish as planning
        value=self._post('applications','result-list',{})
        if not isinstance(value.get('results'),list):raise VerificationFailed('Invalid result catalogue response.')
        return [planning.parse_result(item) for item in value['results']]

    def ai_use(self,asset:str) -> dict[str, Any]:
        """Who may use this item for AI (as its owner) or your own permission (as a reader)."""
        return self._post('ai-use','get',{'asset_id':asset})

    def grant_ai_use(self,asset:str,grants,*,expected_generation,command_id:str|None=None) -> dict[str, Any]:
        """Allow people who can read an item you own to use it for AI.

        `grants` is {person: ['embedding'|'training'|'evaluation', ...]}; `expected_generation` the one `ai_use`
        returned.
        """
        import uuid
        return self._post('ai-use','grant',{'asset_id':asset,'grants':grants,'expected_generation':expected_generation,'command_id':command_id or uuid.uuid4().hex})

    def grant_own_ai_use(self,asset,purpose,granted=True,*,command_id=None) -> dict[str, Any]:
        """Allow your own work in an item you uploaded or made to be used for AI, or stop allowing it.

        Parameters
        ----------
        asset
            The item's id.
        purpose
            'training' or 'evaluation'.
        granted
            True allows it; False stops allowing it from now on.
        command_id
            The same id makes a retry return the first answer; None makes a new one.

        Returns
        -------
        dict[str, Any]
            {asset_id, purpose, state, sequence, at} as the server recorded it.
        """
        # E134 s2
        import uuid
        return self._post('ai-use','self-grant',{'asset_id':asset,'purpose':purpose,'state':'granted' if granted else 'withdrawn','command_id':command_id or uuid.uuid4().hex})

    def search(self,text,*,method=None,limit=20) -> dict[str, Any]:
        """Find what you may read in this project by its description, best match first.

        Parameters
        ----------
        text
            What you look for, in your own words.
        method
            'words', or 'embedding' with the deployment's own local model; None is the server's default.
        limit
            The most matches to return.

        Returns
        -------
        dict[str, Any]
            The matches, ranked, as the server answered.
        """
        return self._post('search','query',{'text':text,'limit':limit,**({'method':method} if method else {})})

    def find(self,organization:str,text:str|None=None,*,method:str|None=None,kinds=None,well=None,bbox=None,since=None,until=None,published_by=None,projects=None,include_archived:bool=False,limit:int=20,cursor:str|None=None) -> SearchAnswer | SearchAnswerByMeaning:
        """One page of the versions you may read in every project of an organisation that match your question.

        The answer is an ophiolite.search/2 page, or /3 when answered by meaning. A field left None is the server's
        default; the server checks the question. `bbox` is {'minx','miny','maxx','maxy'[,'crs']}. `find_all` follows
        `next_cursor`.
        """
        # E145 s3
        from . import publish as planning
        from .models.generated import SearchAnswer,SearchAnswerByMeaning
        given={'text':text,'method':method,'kinds':None if kinds is None else list(kinds),'well':well,'bbox':bbox,'since':since,'until':until,
               'published_by':published_by,'projects':None if projects is None else list(projects),'cursor':cursor}
        body={'organization_id':organization,**{k:v for k,v in given.items() if v is not None},**({'include_archived':True} if include_archived else {}),'limit':limit}
        from .errors import OphioliteError
        try:answer=self._organization_search(body)
        except OphioliteError as refused:  # the server's sentence (the filter it names; E14's without a model), not the transport's generic one
            if not refused.server_message or refused.server_message==refused.message:raise
            raise type(refused)(refused.server_message,refused.recovery,status=refused.status,code=refused.code,remedy=refused.remedy,
                                docs=refused.docs,request_id=refused.request_id,server_message=refused.server_message,details=refused.details) from None
        by_meaning=isinstance(answer,dict) and answer.get('schema')=='ophiolite.search/3'
        return planning.parse(SearchAnswerByMeaning if by_meaning else SearchAnswer,answer)

    def _organization_search(self,body):
        """find's one POST (adhoc-async-client-find: the asynchronous client's worker sends it on its own loop)."""
        from .access_history import _headers,_post  # the organisation-level read of person_history (no project in the body or headers)
        return _post(self.http,self.url,'/api/v1/organizations/search',body,_headers(self.credential,self.url,None,self._sender),notifier=getattr(self,'_notifier',None))

    def find_all(self,organization:str,text:str|None=None,*,limit:int=50,**filters) -> Iterator[SearchRow]:
        """Every row `find` answers, in the server's order, with one page held at a time."""
        # E145 s3
        cursor=None
        while True:
            page=self.find(organization,text,limit=limit,cursor=cursor,**filters)
            yield from page.results
            cursor=page.next_cursor
            if not cursor:return

    def export_corpus(self,selections,destination,*,purpose,seed=0,fractions=(0.8,0.1,0.1),groups=None) -> dict[str, Any]:
        """Write a corpus for AI from exact curves the server allows you to use for that purpose.

        Parameters
        ----------
        selections
            [(asset, revision, [curves]), ...]; every item names its curves.
        destination
            A new folder for the corpus.
        purpose
            What the corpus is for, such as 'training' or 'evaluation'; the server allows each item for it or not.
        seed
            The seed that splits the items: the same seed splits them the same way.
        fractions
            The shares of the train, validation and test splits, adding up to 1.
        groups
            {asset_id: group name}: the group an item stays with in one split, instead of its LAS well.

        Returns
        -------
        dict[str, Any]
            The summary of the corpus as written and checked (ophiolite.corpus).

        Raises
        ------
        Refused
            When the destination exists, nothing is chosen, an item names no curves or has no well or group to split
            by, or the fractions do not add up to 1.
        VerificationFailed
            When the corpus as written does not check against itself and its bundle.
        """
        from .corpus import export_corpus
        return export_corpus(self,selections,destination,purpose=purpose,seed=seed,fractions=fractions,groups=groups)

    def result_groups(self) -> list[ResultGroup]:
        """Project result groups you can see, with only the members and recommendation you may open."""
        from . import publish as planning
        from .models.api import ResultGroup
        return [planning.parse(ResultGroup,g) for g in self._post('result-groups','list',{})['groups']]

    def diff(self,a,b) -> ResultDiff:
        """Changes between two exact result versions: parameters, input and (when comparable) samples."""
        from . import publish as planning
        from .models.api import ResultDiff
        pick=lambda x:{k:v for k,v in planning.selection(x).items() if k in ('asset_id','revision')} if not isinstance(x,(tuple,list)) else {'asset_id':x[0],'revision':x[1]}
        return planning.parse(ResultDiff,self._post('result-groups','diff',{'a':pick(a),'b':pick(b)}))

    # --- E142 s1: surveys, one unit to a script ---------------------------------------------------------------------

    def _pages(self,operation,body,items):
        """Every page of a cursor read, guarded like assets(): a repeated or over-long cursor stops the read."""
        cursor=None;seen=set()
        for _ in range(_surveys.MAX_PAGES):
            page=self._post('surveys',operation,{**body,**({'cursor':cursor} if cursor else {})},retry=True)
            if not isinstance(page,dict) or not isinstance(page.get(items),list):raise VerificationFailed('Invalid survey response.')
            yield page;cursor=page.get('next_cursor')
            if cursor is None:return
            if not isinstance(cursor,str) or len(cursor)>1024 or cursor in seen:raise VerificationFailed('Invalid or repeated survey cursor.')
            seen.add(cursor)
        raise VerificationFailed('The survey read did not end.')

    def surveys(self) -> Iterator[dict[str, Any]]:
        """The project's surveys you may see, oldest first.

        You see a survey with a member you may read, or your own. Each is a dict with survey_id, name, identity,
        revision and count (the members you may read).
        """
        for page in self._pages('list',{},'surveys'):yield from page['surveys']

    def holder_pages(self,item:str|None=None,*,limit:int|None=None) -> Iterator[dict[str, Any]]:
        """Which member's application holds which version of the items you may read, page by page.

        Each page is an ophiolite.held-copies/1 document, checked, first page first; `item` names one item alone.
        """
        # E171 s1
        from . import publish as planning
        from .models.generated import HeldCopies
        body={**({'item':item} if item is not None else {}),**({'limit':limit} if limit else {})}
        cursor,seen=None,set()
        for _ in range(_surveys.MAX_PAGES):
            raw=self._post('exchange','holders',{**body,**({'cursor':cursor} if cursor else {})},retry=True)
            page=planning.parse(HeldCopies,raw)
            if page.project!=self.project or page.item!=item:raise VerificationFailed('The holders page names another project or item.')
            yield raw;cursor=page.next
            if cursor is None:return
            if cursor in seen:raise VerificationFailed('Invalid or repeated holders cursor.')
            seen.add(cursor)
        raise VerificationFailed('The holders read did not end.')

    def holders(self,item:str|None=None) -> dict[str, Any]:
        """Who holds which version, read whole: the first page's document with every page's rows and no `next`.

        Plain words (who, which application, how far behind) are the CLI's `ophiolite data holders`.
        """
        # E171 s1
        whole=None
        for page in self.holder_pages(item):
            if whole is None:whole=dict(page,rows=list(page['rows']))
            else:whole['rows']+=page['rows']
        whole['next']=None
        return whole

    def receipt_pages(self,item:str,revision:str,*,limit:int|None=None) -> Iterator[dict[str, Any]]:
        """What the send that made a version and each get of it kept, changed and did not carry, page by page.

        Each page is an ophiolite.transfer-receipts/1 document, checked, first page first. Read by the item's
        audience; an unknown and an unreadable version answer alike.
        """
        # E184 s0a
        from . import publish as planning
        from .models.generated import TransferReceipts
        body={'item':item,'revision':revision,**({'limit':limit} if limit else {})}
        cursor,seen=None,set()
        for _ in range(_surveys.MAX_PAGES):
            raw=self._post('exchange','receipts',{**body,**({'cursor':cursor} if cursor else {})},retry=True)
            page=planning.parse(TransferReceipts,raw)
            if page.item!=item or page.revision!=revision:raise VerificationFailed('The receipts page names another item or version.')
            yield raw;cursor=page.next
            if cursor is None:return
            if cursor in seen:raise VerificationFailed('Invalid or repeated receipts cursor.')
            seen.add(cursor)
        raise VerificationFailed('The receipts read did not end.')

    def receipts(self,item:str,revision:str) -> dict[str, Any]:
        """One version's receipts read whole: the first page's document with every page's gets and no `next`."""
        # E184 s0a
        whole=None
        for page in self.receipt_pages(item,revision):
            if whole is None:whole=dict(page,got=list(page['got']))
            else:whole['got']+=page['got']
        whole['next']=None
        return whole

    def affected_pages(self,item:str,*,against:str='head',limit:int|None=None) -> Iterator[dict[str, Any]]:
        """What rests on the versions of an item other than its newest, page by page.

        With against='next' its newest version counts too, before a new version is published. Each page is an
        ophiolite.affected/1 document, checked, first page first.
        """
        # E177 s1
        from . import publish as planning
        from .models.generated import Affected
        body={'asset_id':item,'against':against,**({'limit':limit} if limit else {})}
        cursor,seen=None,set()
        for _ in range(_surveys.MAX_PAGES):
            raw=self._post('changes','affected',{**body,**({'cursor':cursor} if cursor else {})},retry=True)
            page=planning.parse(Affected,raw)
            if page.project!=self.project or page.asked!=item or page.against!=against:raise VerificationFailed('The affected page names another project, item or question.')
            yield raw;cursor=page.next
            if cursor is None:return
            if cursor in seen:raise VerificationFailed('Invalid or repeated affected cursor.')
            seen.add(cursor)
        raise VerificationFailed('The affected read did not end.')

    def affected(self,item:str,*,against:str='head') -> dict[str, Any]:
        """What rests on the versions of an item other than its newest, read whole.

        A plain dict, not an ophiolite.affected/1 document: `rows` from every page; `item`, `as_of`, `counts` and
        `without_inputs` from the last page read; `restricted` when any page said so; `complete` only when every page
        did; `pages` the number of pages. Plain words are the CLI's `ophiolite results affected`.
        """
        # E177 s1
        return affected_whole(self.affected_pages(item,against=against))

    def survey_pages(self,survey_id:str,revision=None,*,view:str='revision',limit:int|None=None) -> Iterator[SurveyPage]:
        """The pages of one survey revision (ophiolite.survey/1), first page first; see survey()."""
        from . import publish as planning
        from .models.generated import SurveyPage
        body={'survey_id':survey_id,'view':view,**({'revision':revision} if revision is not None else {}),**({'limit':limit} if limit else {})}
        for page in self._pages('get',body,'members'):yield planning.parse(SurveyPage,page)

    def survey(self,survey_id:str,revision=None,*,view:str='revision') -> Survey:
        """A survey revision, the latest when none is named, with every member and relation you may read.

        It is read page by page. view='latest' serves each member's newest revision you may read where its role still
        holds.
        """
        return _surveys.gathered(self.survey_pages(survey_id,revision,view=view))

    def survey_history(self,survey_id:str) -> Iterator[dict[str, Any]]:
        """The survey's events, newest first, each only when you may read every version it names."""
        for page in self._pages('history',{'survey_id':survey_id},'events'):yield from page['events']

    def _survey_command(self,kind,body,command_id):
        return self._post('surveys',kind,_surveys.command(body,command_id),retry=True)  # one command id across the retry

    def create_survey(self,name,members,*,relations=(),identity=None,context=None,source=None,command_id=None) -> dict[str, Any]:
        """A new survey of MEMBERS ({role, asset_id, revision}); identity {authority, key}, else provisional."""
        body={'name':name,'identity':identity or {'provisional':True},'context':context or {},'members':list(members),'relations':list(relations),
              **({'source':source} if source is not None else {})}
        return self._survey_command('create',body,command_id)

    def add_survey_members(self,survey_id,expected_revision,members,*,command_id=None) -> dict[str, Any]:
        """Add members ({role, asset_id, revision}) to the survey revision you read, in one new revision."""
        return self._survey_command('add',{'survey_id':survey_id,'expected_revision':expected_revision,'members':list(members)},command_id)

    def remove_survey_members(self,survey_id,expected_revision,members,*,command_id=None) -> dict[str, Any]:
        """Removes members (their relations close in the same revision)."""
        return self._survey_command('remove',{'survey_id':survey_id,'expected_revision':expected_revision,'members':[_surveys.key(m) for m in members]},command_id)

    def replace_survey_member(self,survey_id,expected_revision,old,new,*,command_id=None) -> dict[str, Any]:
        """Replaces OLD with NEW ({role, asset_id, revision}); relations are re-pointed and checked again."""
        return self._survey_command('replace',{'survey_id':survey_id,'expected_revision':expected_revision,'from':_surveys.key(old),'to':new},command_id)

    def relate_survey_members(self,survey_id,expected_revision,relations,*,command_id=None) -> dict[str, Any]:
        """Add relations between members of the survey revision you read, checked, in one new revision."""
        return self._survey_command('relate',{'survey_id':survey_id,'expected_revision':expected_revision,'relations':list(relations)},command_id)

    def unrelate_survey_members(self,survey_id,expected_revision,relations,*,command_id=None) -> dict[str, Any]:
        """Close relations between members of the survey revision you read, in one new revision."""
        return self._survey_command('unrelate',{'survey_id':survey_id,'expected_revision':expected_revision,'relations':list(relations)},command_id)

    def rename_survey(self,survey_id,expected_revision,name,*,command_id=None) -> dict[str, Any]:
        """Give the survey revision you read a new name, in one new revision."""
        return self._survey_command('rename',{'survey_id':survey_id,'expected_revision':expected_revision,'name':name},command_id)

    def identify_survey(self,survey_id,expected_revision,identity,*,command_id=None) -> dict[str, Any]:
        """Gives a provisional survey its identity {authority, key}; once per project and identity."""
        return self._survey_command('identify',{'survey_id':survey_id,'expected_revision':expected_revision,'identity':identity},command_id)

    def restate_survey(self,survey_id,expected_revision,members,relations=(),*,name=None,command_id=None) -> dict[str, Any]:
        """State the survey's complete new lists of members and relations in one revision.

        What is absent closes, what is new opens, unchanged members stay; members you cannot read are kept. The same
        lists and name answer changed: False, with no new revision.
        """
        # E142 s2a
        body={'survey_id':survey_id,'expected_revision':expected_revision,'members':list(members),'relations':list(relations),
              **({'name':name} if name is not None else {})}
        return self._survey_command('restate',body,command_id)

    def link_survey_members(self,survey_id,expected_revision,members,*,command_id=None) -> dict[str, Any]:
        """Make items already in the project members, as add does, recorded as a person's linking (kind link)."""
        # E142 s2a
        return self._survey_command('link',{'survey_id':survey_id,'expected_revision':expected_revision,'members':list(members)},command_id)

    def withdraw_survey(self,survey_id,expected_revision,*,command_id=None) -> dict[str, Any]:
        """Withdraws the survey: no longer listed or read; nothing it names is changed."""
        return self._survey_command('withdraw',{'survey_id':survey_id,'expected_revision':expected_revision},command_id)

    def history(self,asset) -> History:
        """Every version of a result you can read, oldest first.

        Parameters
        ----------
        asset
            A result or derived publication: its receipt, or {asset_id, revision, authority}.

        Returns
        -------
        History
            `head_revision`, `count` and `revisions`, each with its number, parent and who published it.

        Raises
        ------
        Refused
            For an uploaded original, whose versions are not listed here, or for a selection that is not exact.

        Example
        -------
        result = {'asset_id': 'result-id', 'revision': 'revision-id', 'authority': 'ophiolite:derived'}
        history = client.history(result)
        print(history.head_revision, history.count)
        """
        from . import publish as planning
        from .models.api import History
        target=planning.selection(asset)
        if target.get('authority')=='ophiolite:uploaded':  # H4 (E32 F4): the server would answer with a misleading refusal
            raise Refused('history lists the versions of results and derived publications; the versions of an uploaded original are not listed. '
                          'Read the exact revision you were given, or ask its uploader.')
        return planning.parse(History,self._post('applications','result-history',{'asset_id':target['asset_id']}))

    def _sharing_target(self,asset):
        """H5b: one classification for grants and share. A derived item (a catalogue entry or a descriptor carries
        `ophiolite:derived`) that is not an application result is a derived publication when publications/info names
        the same asset; its recipients are set on its current version."""
        from . import publish as planning
        asset=planning.selection(asset)
        if asset['authority']=='ophiolite:uploaded':return asset,self._post('las-uploads','info',{'asset_id':asset['asset_id']})
        if asset['authority']=='ophiolite:publication':return asset,self._post('publications','info',{'asset_id':asset['asset_id']})  # E31
        results=self._post('applications','result-list',{})
        items=results.get('results') if isinstance(results,dict) else None
        if not isinstance(items,list) or any(i.get('asset_id')==asset['asset_id'] for i in items if isinstance(i,dict)):return asset,results
        try:info=self._post('publications','info',{'asset_id':asset['asset_id']})
        except (PermissionRefused,Unavailable):return asset,results  # neither: the result refusal below explains it
        if not isinstance(info,dict) or info.get('asset_id')!=asset['asset_id']:raise VerificationFailed('Sharing returned a different publication.')
        if info.get('revision')!=asset['revision']:raise Refused('Recipients are set on the publication as a whole and share every version; select its current version to review them.')
        return {**asset,'authority':'ophiolite:publication'},info

    def grants(self,asset) -> Grants:
        """Who an item is shared with, as you would review it before `share`.

        Parameters
        ----------
        asset
            A result, a derived publication or an uploaded original: its receipt, or {asset_id, revision, authority}.

        Returns
        -------
        Grants
            The recipients and the `generation` to pass to `share`.

        Raises
        ------
        Refused
            When the selection is not exact, or names an earlier version of a derived publication (recipients are
            set on the publication as a whole and share every version).
        """
        from . import publish as planning
        asset,result=self._sharing_target(asset)
        return planning.grants(asset,result)

    def share(self,asset,*,read,expected_generation:int,reuse=None,command_id:str|None=None,project:bool|None=None) -> Grants | UploadResult | ResultSummary | RestrictedResultSummary:
        """Replace who an item is shared with, only if no one changed it since you reviewed it.

        Recipients belong to the result or derived publication as a whole: sharing
        shares every version of it, earlier and later; an uploaded original has one.
        The request carries a command id; after an unknown outcome it is replayed
        once, which returns the applied result or refuses with IntegrityConflict if
        anyone changed the recipients meanwhile (a revocation is never undone).
        Servers refuse an unconditional replacement (428).

        Parameters
        ----------
        asset
            A result, a derived publication or an uploaded original, as `grants` takes it.
        read
            The account names of the people who may read it from now on, each once.
        expected_generation
            The `generation` of the `client.grants(asset)` snapshot you reviewed.
        reuse
            Those of them who may also reuse it; None is no one.
        command_id
            1-64 characters; None makes a new one.
        project
            True also shares a derived publication with everyone in the project, including people who join
            later; False withdraws that; None leaves it as it is. Either explicit value needs a server that
            reports it, is refused before anything is sent otherwise, and is checked in the answer.

        Returns
        -------
        Grants | UploadResult | ResultSummary | RestrictedResultSummary
            The derived publication's recipients, or the uploaded original or result as shared.

        Raises
        ------
        ValidationFailed
            When `read` or `reuse` is not a list of distinct names, or `reuse` names someone not in `read`.
        Refused
            When an argument is not as above, or the server cannot share conditionally or with the whole project.
        IntegrityConflict
            When someone changed the recipients since your snapshot.
        VerificationFailed
            When the answer names another item or project audience.
        """
        # E7: unconditional replacement ended with its transition release
        import uuid
        from . import publish as planning
        from .errors import ShareOutcomeUnknown
        from .models.api import UploadResult
        reuse=[] if reuse is None else reuse
        planning.validate_recipients(read,reuse)
        if type(expected_generation) is not int or expected_generation<0:raise Refused('expected_generation must be a non-negative integer from client.grants(asset).')
        if command_id is not None and (not isinstance(command_id,str) or not 0<len(command_id)<=64):raise Refused('command_id must be 1-64 characters.')
        if project is not None and type(project) is not bool:raise Refused('project must be True, False or None.')
        asset,_=self._sharing_target(asset)  # H5b: the same target as grants; validated input first, nothing sent before
        uploaded=asset['authority']=='ophiolite:uploaded';publication=asset['authority']=='ophiolite:publication'
        body={'asset_id' if uploaded or publication else 'id':asset['asset_id'],'audience':read,'reuse_audience':reuse}
        area='las-uploads' if uploaded else 'publications' if publication else 'applications'
        # Never infer support: an older server would apply the request unconditionally.
        snapshot=self.grants(asset)
        if snapshot.generation is None:raise Refused('This server does not support conditional sharing.')
        if project is not None:  # E78: only a derived publication can be shared with the whole project; never sent unverified
            if not publication:raise Refused('Only a derived publication can be shared with everyone in the project; share this by name.')
            if snapshot.project is None:raise Refused('This server does not support sharing with everyone in the project.')
            body['project_audience']='read' if project else 'none'
        body.update(expected_generation=expected_generation,command_id=command_id or uuid.uuid4().hex)
        try:result=self._post(area,'share',body)
        except ShareOutcomeUnknown:result=self._post(area,'share',body)  # identical replay: idempotent or refused
        if publication:  # E31: a derived publication answers its sharing view; its grants are the result
            # H5b: recipients belong to the publication as a whole; a version appended meanwhile is the same publication
            parsed=planning.grants({**asset,'revision':result.get('revision')},{k:v for k,v in result.items() if k!='sharing_contract'})
            if parsed.asset_id!=asset['asset_id']:raise VerificationFailed('Sharing returned a different publication.')
            if project is not None and parsed.project is not project:raise VerificationFailed('Sharing returned a different project audience.')
            return parsed
        parsed=planning.parse(UploadResult,result) if uploaded else planning.parse_result(result)
        # Recipients belong to a result as a whole (every version, E8); an upload has one revision.
        if parsed.asset_id!=asset['asset_id'] or uploaded and parsed.revision!=asset['revision']:raise VerificationFailed('Sharing returned a different exact asset.')
        return parsed

    def bindings(self) -> list[Binding]:
        """The application bindings configured in this project that you may see."""
        from . import publish as planning
        from .models.api import Binding
        data=self._post('applications','list',{})
        if not isinstance(data.get('bindings'),list):raise VerificationFailed('Invalid application binding list.')
        return [planning.parse(Binding,item) for item in data['bindings']]

    def options(self) -> dict[str, Any]:
        """What an application binding may be configured with in this project, as the server answers."""
        return self._post('applications','options',{})

    def inspect(self,asset:str|None=None,revision:str|None=None,*,curve:str='',name:str='',release_id=None,asset_index:int=0) -> dict[str, Any]:
        """What configuring a binding on this exact curve, or on an item of a release, would use, before you configure it."""
        body={'curve':curve,'name':name}
        if release_id is not None:body.update(release_id=release_id,asset_index=asset_index)
        else:body.update(asset_id=asset,asset_revision=revision)
        return self._post('applications','inspect',body)


    def _grant_status(self,headers):
        from .auth import request
        return request(self.url+'/api/v1/application-access/status',{'id':headers['X-Ophiolite-Application-Grant']},_client_header.stamp(headers,self._sender),http=self.http,notifier=_deprecation.of(self))

    def work_folder(self,path:str|os.PathLike[str],**options) -> WorkFolder:
        """A private folder that keeps each request, so the work can be recovered after a restart.

        No sign-in is saved in it.

        Parameters
        ----------
        path
            The folder; it is made private when it does not exist.
        **options
            `lock_timeout`, the seconds to wait for another process using the folder.

        Returns
        -------
        WorkFolder
            The folder, whose calls save each request before sending it (ophiolite.publish.WorkFolder).
        """
        from .publish import WorkFolder
        return WorkFolder(self,path,**options)

    def recover(self,path:str|os.PathLike[str],through:str|None=None) -> Binding | Run | Receipt | UploadResult | None:
        """Finish the requests a work folder saved before a restart, and return the last answer.

        Parameters
        ----------
        path
            The work folder.
        through
            The saved operation to recover through: 'configure', 'start', 'publish' or 'upload'; None is all.

        Returns
        -------
        Binding | Run | Receipt | UploadResult | None
            The answer of the last request sent again; None when every saved request already had its answer.

        Raises
        ------
        RecoveryUnavailable
            When the path is not the original work folder, it holds no saved request, or `through` is not one of
            the above.
        VerificationFailed
            When a saved upload's answer names another file than the one saved.
        """
        from .errors import RecoveryUnavailable
        path=Path(path)
        if not path.is_dir() or not (path/'owner.json').is_file():raise RecoveryUnavailable('Recovery requires the original private SDK work folder.')
        return self.work_folder(path).recover(through)

    def upload_las(self,source,*,name,attribution,audience,rights_confirmed,filename=None,well_notes='',command_id=None,curve_declaration=None) -> UploadResult:
        """Upload a LAS file as a new private original in this project.

        Without a WorkFolder this is not recoverable after a restart; with the same `command_id`, a file sent in parts
        continues where it stopped.

        Parameters
        ----------
        source
            The file's path, or its bytes.
        name
            The name the item is listed by.
        attribution
            Who the file is attributed to.
        audience
            The account names of the people who may see it besides you, each once.
        rights_confirmed
            True: you confirm that you may keep this file, make results from it and share it with the audience.
        filename
            The file name to record; by default the path's name, or 'input.las' for bytes.
        well_notes
            A note kept with the well the file names.
        command_id
            The same id makes a retry return the same item; None makes a new one.
        curve_declaration
            {'well', 'depth_kind': 'MD'|'TVD'|'TVDSS', 'depth_datum'}, all three (the datum may be 'unknown'): the
            curves' well, depth kind and datum, so the version also holds their well log form. Only what you give is
            sent: nothing is read from the file's header.

        Returns
        -------
        UploadResult
            The new item and its exact revision, the file's digest.

        Raises
        ------
        ValidationFailed
            When the rights are not confirmed, or the name, attribution or audience is not one the server takes.
        VerificationFailed
            When the revision the server answers is not the file's digest.
        """
        # E54: parts; E183 s2b: curve_declaration
        import uuid
        from . import publish as planning
        filename=filename or (Path(source).name if not isinstance(source,bytes) else 'input.las')
        declared=dict(curve_declaration=curve_declaration) if curve_declaration is not None else {}
        body,extra=planning.upload_metadata(self.project,command_id or uuid.uuid4().hex,filename=filename,name=name,attribution=attribution,audience=audience,rights_confirmed=rights_confirmed,well_notes=well_notes,**declared)
        return self._send(source,body,extra)

    def upload_data(self,source,*,profile,name,attribution,audience,rights_confirmed,declared=None,filename=None,well_log=None,well_notes='',command_id=None,origin=None,
                    append_to=None,expected_parent=None,provenance=None,application_source=None,represents=None,holder=None,application=None,receipt=None,
                    curve_declaration=None,made_for=None) -> UploadResult:
        """Upload a file of any supported kind as a new private original, with the context you declare.

        Nothing is inferred: units, coordinate system and meanings are what you declare. A repeated command id
        returns the same item.

        Parameters
        ----------
        source
            The file's path, or its bytes.
        profile
            The kind of file, as the server names it (for example 'las2/1' or 'points-csv/1').
        name, attribution, audience, rights_confirmed, well_notes, command_id
            As `upload_las` takes them.
        declared
            What the file's kind needs you to state: units, coordinate system and meanings.
        filename
            The file name to record; by default the path's name, or 'upload' for bytes.
        well_log
            {asset_id, revision}: the well log this file belongs to.
        origin
            Where the file came from, recorded as provenance (a bundle import records the bundle's item).
        append_to, expected_parent
            Your uploaded wavelet, model or section and its current revision: the file becomes that result's next
            version, and its audience stays the result's.
        provenance
            The original kept beside this file, as staged by a bundle import.
        application_source
            {system: 'application:<client id>', instance, container, id}: the application object the file came from,
            as a send's `source` records it.
        represents
            'horizon' marks a point set (points-csv/1, petrel-points-attributes/1) as a horizon; a later version
            keeps the mark without naming it.
        holder, application
            A work folder's holder id, and 'application:<word>' or 'script': the folder holds the version this
            upload adds. Neither changes what a retry with the same command id matches.
        receipt
            An `ophiolite.transfer-receipt/1`, kept with the version by a project whose capabilities list its codes
            version (`transfer_codes_kept`); send it only to such a project.
        curve_declaration
            As `upload_las` takes it, with profile 'las2/1' only.
        made_for
            1-32 exact versions ({asset_id, revision} or (asset_id, revision)) you may read that the file was made
            for, recorded as stated by you, never as what it was made from. Such a file goes in one request; a
            project whose release does not record it refuses the whole upload.

        Returns
        -------
        UploadResult
            The new item, or the result's new version, and its exact revision, the file's digest.

        Raises
        ------
        ValidationFailed
            When the rights are not confirmed, a detail is not one the server takes, or only one of `append_to` and
            `expected_parent` is given.
        Refused
            When a file too large for one request carries `made_for` or a kept original, or `made_for` is refused.
        VerificationFailed
            When the revision the server answers is not the file's digest.
        """
        # E11, E18; E53: append_to; E122 s6: application_source; E173 s0b: represents; E171 s1: holder; E184 s0: receipt;
        # E183 s2b: curve_declaration; E192 s2: made_for
        import uuid
        from . import publish as planning
        filename=filename or (Path(source).name if not isinstance(source,bytes) else 'upload')
        body,extra=planning.upload_metadata(self.project,command_id or uuid.uuid4().hex,filename=filename,name=name,attribution=attribution,audience=audience,
                                            rights_confirmed=rights_confirmed,well_notes=well_notes,profile=profile,declared=declared,well_log=well_log,origin=origin,
                                            append_to=append_to,expected_parent=expected_parent,provenance=provenance,application_source=application_source,
                                            represents=represents,holder=holder,application=application,receipt=receipt,curve_declaration=curve_declaration,
                                            made_for=made_for)
        try:return self._send(source,body,extra)
        except Refused as error:raise planning.made_for_refused(error,body) from None

    def _described(self):
        """The deployment's capabilities answer, read once (its limits and what a folder upload may declare)."""
        if getattr(self,'_capabilities_answer',None) is None:self._capabilities_answer=self._post('capabilities','describe',{},retry=True)
        return self._capabilities_answer

    def transfer_codes_kept(self,version) -> bool:
        """Whether this deployment keeps transfer receipts of that version of the code document.

        It reads the capabilities' `transfer_receipts.codes`; an older deployment states none, and this SDK then
        sends no receipt.
        """
        # E184 s0 (D-6)
        member=self._described().get('transfer_receipts')
        return isinstance(member,dict) and isinstance(member.get('codes'),list) and version in member['codes']

    def upload_reads(self) -> bool:
        """Whether this deployment lets a folder upload name the tools that read its files.

        It reads the capabilities' `upload_runs.reads`; without that member this SDK never sends `reads`, and an older
        deployment answers as it always did.
        """
        # E107a (R5-8): the read procedures
        member=self._described().get('upload_runs')
        return isinstance(member,dict) and 'procedures' in (member.get('reads') or [])

    def served_limits(self) -> dict[str, Any]:
        """This deployment's size limits, as it states them, read once per client.

        Returns
        -------
        dict[str, Any]
            The capabilities' `limits`: at least `upload_bytes` (the largest request) and `file_bytes` (the largest
            file), each a whole number of bytes.

        Raises
        ------
        VerificationFailed
            When the deployment does not state its upload limits.
        """
        # E54
        if getattr(self,'_served_limits',None) is None:
            value=self._described().get('limits')
            if not isinstance(value,dict) or not all(isinstance(value.get(k),int) for k in ('upload_bytes','file_bytes')):
                raise VerificationFailed('The deployment did not state its upload limits.')
            self._served_limits=value
        return self._served_limits

    def _send(self,source,body,extra):
        """E54: a file within the request limit goes in one request, as before; a larger one in parts, read from the
        path one part at a time (bytes in memory are sliced). Either way the revision must be the file's digest."""
        import hashlib
        from . import publish as planning
        from .models.api import UploadResult
        size=len(source) if isinstance(source,(bytes,bytearray)) else Path(source).stat().st_size
        if size<=planning.SINGLE or size<=self.served_limits()['upload_bytes']:
            raw=planning.upload_bytes(source);digest=hashlib.sha256(raw).hexdigest()
            result=planning.parse(UploadResult,self._post_bytes('las-uploads','upload',raw,extra_headers=extra))
        else:
            if 'made_for' in body:raise Refused(planning.MADE_FOR_ONE_REQUEST%(max(planning.SINGLE,self.served_limits()['upload_bytes'])//(1024*1024)))  # E192 s2: sessions take no made_for
            if 'provenance' in body:raise Refused('This file is too large to send in one request with the original kept beside it; this deployment does not take one in parts.')
            file=planning.FileSource(source);digest=file.sha256()
            result=planning.parse(UploadResult,self._upload_parts(file,digest,body))
        from .publish import receipt_matches
        if not receipt_matches(result,digest):raise VerificationFailed('The uploaded original has a different checksum revision.')  # E108 (N2, Q2)
        return result

    def _upload_parts(self,file,digest,body):
        """begin (the same command continues), the parts not yet received, finish, the check (polled), publish."""
        begin={'command_id':body['command_id'],'filename':body['filename'],'profile':body.get('profile','las2/1'),'declared':body.get('declared',{}),
               'bytes':file.size,'sha256':digest,**{k:body[k] for k in ('append_to','expected_parent','represents','curve_declaration') if k in body}}  # E173 s0b: the mark goes with begin; E183 s2b: the declaration too, never with publish
        view=self._transfer_parts(file,self._post('las-uploads','begin',begin,retry=True))
        if view['state'] not in ('checked','published'):raise session_refusal(view)
        fields={k:body[k] for k in ('name','attribution','audience','rights_confirmed','well_notes','well_log','source') if k in body}  # E122 s6: the item's source
        return self._post('las-uploads','publish',{'upload_id':view['upload_id'],**fields},retry=True)

    def _transfer_parts(self,file,view):
        """The parts a begun session has not received, finish, and its check (polled); the session's last state.
        E55: a folder upload's large file is begun by the run and saved by it, so only this middle is shared."""
        from . import publish as planning
        ref={'upload_id':view['upload_id']}
        if view['state']=='open':
            have={p['index'] for p in view['received']}
            for index in range(view['parts']):
                if index in have:continue
                raw=file.read(index*view['part_bytes'],view['part_bytes'])
                for attempt in (0,1):  # a part damaged on the way is sent once more
                    try:self._post_bytes('las-uploads','part',raw,extra_headers=planning.part_header(self.project,view['upload_id'],index,raw),retry=True);break
                    except Refused as error:
                        if error.code!='part-corrupt' or attempt:raise
                del raw;gc.collect(1)  # httpx keeps a response in a reference cycle with its request (and so the part) until collected
            view=self._post('las-uploads','finish',ref,retry=True)
        wait=0.2
        while view['state']=='finishing':
            time.sleep(wait);wait=min(wait*2,5.0)
            view=self._post('las-uploads','state',ref,retry=True)
        return view

    def download_original(self,asset:str,revision:str,destination:str|os.PathLike[str],*,part_bytes:int=8*1024*1024) -> Path:
        """Save the original file of one exact version, checked byte for byte against the digest the server states.

        Nothing is left at `destination` unless every byte matched. An original restored from a public dataset is
        saved with `<destination>.NOTICE.txt` beside it (its licence and credits, from the version's describe); when
        the notice cannot be written, nothing is saved.

        Parameters
        ----------
        asset
            The item's id.
        revision
            The exact version.
        destination
            Where the file is saved.
        part_bytes
            The size of each part asked for.

        Returns
        -------
        Path
            The saved file.

        Raises
        ------
        IntegrityConflict
            When the file does not match the one the server holds; nothing is saved.
        """
        return self._save_original(asset,revision,destination,part_bytes)

    def _save_original(self,asset,revision,destination,part_bytes=8*1024*1024,*,described=True):
        """`download_original`. DESCRIBED=False (E212 s1): the caller knows the revision's profile is served as its
        original alone (`procedures.original_only`), which no describe serves, so no describe is asked and no notice
        written."""
        # E54; E212 s1: the notice from the version's describe
        base=self.prefix+'/'+quote(asset,safe='')+'/revisions/'+quote(revision,safe='')
        path=base+'/representations/artifact'
        def fill(out):
            parts=_ranges.Parts(part_bytes)
            while parts.pending():
                answer={}
                out.write(parts.accept(self._get(path,part_bytes,ranged=parts.range(),answer=answer),answer))
            return parts.digest(),parts.expected
        saved=save_verified(destination,fill,mismatch='The downloaded original does not match the file the deployment holds; nothing was saved.')
        if not described:return saved
        notice=saved.with_name(saved.name+'.NOTICE.txt')
        try:
            link=self._public_dataset(base,saved)
            if link is not None:
                from .export_citation import notice_text
                try:save_text(notice,notice_text(link))
                except OSError as error:raise Refused(NOTICE_UNWRITTEN%(notice,error)) from None
        except BaseException:
            saved.unlink(missing_ok=True);raise
        return saved

    def _public_dataset(self,base,saved):
        """E212 s1: the `public_dataset` the exact revision's describe answers, or None. A LAS file is described by one of
        its curves (read from the saved file's header), as the deployment describes no LAS file without one."""
        try:described=self._json(base+'?'+PROFILES[1:],256*1024)
        except Incompatible as refused:
            from .checks import las_curves
            with open(saved,'rb') as f:curves=las_curves(f.read(256*1024))
            if not curves:
                # an original of a profile the scientific routes do not serve (a kept wells table, sql-wells/1) has no
                # describe, so no public_dataset and no notice; the original itself is saved as before E212 s1
                if UNSERVED_PROFILE in (refused.server_message or refused.message or ''):return None
                raise
            described=self._json(base+'?curve='+quote(curves[0][0],safe='')+PROFILES,256*1024)
        from .export_citation import link_of
        return link_of(described)

    def publish_derived(self,written,*,name,from_,method,command_id,of_entity=None,new_version_of=None,expected_parent=None,procedure=None,source=None,
                        holder=None,application=None,receipt=None,made_for=None,figures=None) -> PresentedReceipt:
        """Publish a file you made from exact versions you may reuse, with the method you declare.

        A network retry with the same `command_id` is safe (the same receipt comes back); a fresh id on retry can
        create a second item. WorkFolder.publish_derived recovers by itself: it saves a stable command id and the
        file's digest before sending.

        Parameters
        ----------
        written
            The file, a `WrittenOriginal` from ophiolite.writers.
        name
            The name the result is listed by.
        from_
            1-32 parents it was made from: objects with asset_id and revision, or (asset_id, revision).
        method
            How you made it, in your words.
        command_id
            Required; the same id returns the same receipt.
        of_entity
            The well or wellbore the result is of.
        new_version_of, expected_parent
            An earlier publication of the same lineage and its current revision: the file becomes its next version.
            It may be your own, or a colleague's when the project names you both; its author stays the author.
        procedure
            {'id': run id, 'role': output role}: publishes one output of a reported run of a tool; for a run made
            again the receipt may be the earlier result, with its `outcome`. With 'for_outcome' (an outcome id) the
            same result is published again for that outcome, and the receipt is the earlier result with
            `republished`.
        source
            {system: 'application:<client id>', instance, container, id, as_new}: the application object the file
            came from. The version keeps it; without `new_version_of` or `as_new` the server compares the send with
            what that object sent before (receipt `source_change`: new, changed, or unchanged with nothing published).
        holder, application
            Record that a work folder holds the version published; a person's send only (an assistant naming a
            holder is refused).
        receipt
            As `upload_data` takes it.
        made_for
            As `upload_data` takes it; none of them also in `from_`.
        figures
            [{label, file, file_name?}] (a path or bytes), attached to the published version after its answer, one
            request each with a command id made from `command_id`, so a retry adds none.

        Returns
        -------
        PresentedReceipt
            The receipt, which shows itself with a link to the Workspace. With `figures` it carries `figures` (each
            a record, or {label, refused}) and, when one was refused, `figures_line` naming it by its label: the
            version stands.

        Raises
        ------
        Refused
            When `made_for` is refused.
        """
        # E30b; E70c: a colleague's lineage; E106: procedure (a run's output); E120: for_outcome; E122 s4a: source;
        # E171 s1: holder; E184 s0: receipt; E192 s2: made_for; E191 s1: figures; E104: the presented receipt
        from . import publish as planning
        from .models.api import PublicationReceipt
        body,extra=planning.derive_request(self.project,written,name=name,from_=from_,method=method,command_id=command_id,of_entity=of_entity,
                                           new_version_of=new_version_of,expected_parent=expected_parent,procedure=procedure,source=source,
                                           holder=holder,application=application,receipt=receipt,made_for=made_for)
        from .presentation import PresentedReceipt,publication_recipe
        recipe=publication_recipe(name=name,from_=from_,method=method,of_entity=of_entity,made_for=body.get('made_for'))  # E104: "Send again", at call time
        verify=planning.verify_derived if procedure is None else planning.verify_run_output
        try:answer=self._post_bytes('publications','derive',written.bytes,extra_headers=extra,retry=True)
        except Refused as error:raise planning.made_for_refused(error,body) from None
        receipt=verify(body,planning.parse(PublicationReceipt,answer))
        if figures:  # E191 s1 (Q2): after the version's answer; a refused figure never undoes the version
            from .figures import refused_line
            attached=self.figures.attach_each({'asset_id':receipt.asset_id,'revision':receipt.revision},figures,command_id)
            receipt=PublicationReceipt.model_construct(receipt.model_fields_set,**dict(receipt),figures=attached,
                                                       **({'figures_line':refused_line(attached)} if refused_line(attached) else {}))
        return PresentedReceipt.present(receipt,{'origin':self.url,'project':self.project,'family':'m','recipe':recipe})

    def preview_change(self,asset_id,revision,change) -> dict[str, Any]:
        """Show what changing the coordinates or units of one exact version would make, without storing anything.

        Parameters
        ----------
        asset_id
            The item's id.
        revision
            The exact version.
        change
            {'kind': 'coordinates', 'to': 'EPSG:25831', 'values': 'bilinear'} or {'kind': 'units', 'curves':
            {'DT': 'us/m'}}.

        Returns
        -------
        dict[str, Any]
            {'profile', 'method', 'method_key', 'samples', 'declared'} as the server answered.

        Raises
        ------
        OphioliteError
            When the change cannot be made, with the sentence the Workspace shows.
        """
        # E64
        from .entities import _in_its_words
        return _in_its_words(lambda:self._post('publications','transform-preview',{'asset_id':asset_id,'revision':revision,'change':change},retry=True))

    def _change(self,asset_id,revision,change,name,command_id):
        from . import publish as planning
        from .models.api import PublicationReceipt
        preview=self.preview_change(asset_id,revision,change)
        body={'asset_id':asset_id,'revision':revision,'change':change,'name':name,'command_id':command_id,'previewed':preview['method_key']}
        from .entities import _in_its_words
        return planning.parse(PublicationReceipt,_in_its_words(lambda:self._post('publications','transform',body,retry=True)))

    def change_coordinates(self,asset_id:str,revision:str,*,to:str,name:str,command_id:str,values:str='bilinear') -> PublicationReceipt:
        """Make a new version of the same kind in another coordinate system, on the server.

        The server uses the one operation it selects for these points; the method record names it, its published
        accuracy, area and any grid with its SHA-256. The original is never changed.

        Parameters
        ----------
        asset_id
            The item's id.
        revision
            The exact version.
        to
            The coordinate system, such as 'EPSG:25831'.
        name
            The new version's name.
        command_id
            Required; a retry with the same id returns the same receipt.
        values
            How a grid is resampled once onto cell centres: 'bilinear' or 'nearest'.

        Returns
        -------
        PublicationReceipt
            The new version.

        Raises
        ------
        OphioliteError
            When the change cannot be made, with the sentence the Workspace shows.
        """
        # E64
        return self._change(asset_id,revision,{'kind':'coordinates','to':to,'values':values},name,command_id)

    def change_units(self,asset_id:str,revision:str,*,curves:Mapping[str,str],name:str,command_id:str) -> PublicationReceipt:
        """Make a new version of a LAS log with chosen curves converted to other units, on the server.

        The one units table converts them; the method record keeps the coefficients. Nothing is guessed.

        Parameters
        ----------
        asset_id
            The log's item id.
        revision
            The exact version.
        curves
            {mnemonic: unit}; the depth axis by its own mnemonic.
        name
            The new version's name.
        command_id
            Required; a retry with the same id returns the same receipt.

        Returns
        -------
        PublicationReceipt
            The new version.

        Raises
        ------
        OphioliteError
            When a curve's unit is not stated, of another kind or not in the table, with its sentence.
        """
        # E64
        return self._change(asset_id,revision,{'kind':'units','curves':dict(curves)},name,command_id)

    def import_bundle(self,bundle,*,audience,attribution,rights_confirmed,well_logs=None) -> list[dict[str, Any]]:
        """Upload every original file a portable bundle carries as your own new, private upload.

        Each keeps the context the bundle declares, and its origin is recorded as provenance (not authority).
        History, groups, grants and lineage stay behind. Safe to repeat: each item's upload uses a stable command, so
        a retry after a lost answer returns the same item.

        Parameters
        ----------
        bundle
            The opened bundle.
        audience
            The account names of the people who may see the uploads besides you.
        attribution
            Who the files are attributed to.
        rights_confirmed
            True: you confirm that you may keep these files, make results from them and share them with the audience.
        well_logs
            {exported well log id: (asset_id, revision)}: the imported well log each dependent item belongs to.

        Returns
        -------
        list[dict[str, Any]]
            One row per item of the bundle: its `state` ('imported' with its `destination`, or why not).

        Raises
        ------
        ValidationFailed
            When `rights_confirmed` is not True.
        ImportIncomplete
            When an upload fails; the rows so far are in `details['assets']`, and repeating continues the import.
        """
        # E18
        from .bundle import import_plan
        from .errors import ImportIncomplete,ValidationFailed
        if rights_confirmed is not True:raise ValidationFailed(['Confirm that you may retain these files, derive results and share them within the audience; holding a bundle grants no rights.'])
        plan=import_plan(bundle,well_logs or {})
        results=[]
        for position,step in enumerate(plan):
            if step['state']!='ready':results.append(step);continue
            try:results.append(self._import_step(step,audience=audience,attribution=attribution,rights_confirmed=rights_confirmed))
            except Exception as error:
                results.append({**_public(step),'state':'failed','reason':str(error)[:300]})
                results+=[{**_public(s),'state':'not attempted' if s['state']=='ready' else s['state']} for s in plan[position+1:]]
                raise ImportIncomplete('The import stopped; repeat it to continue (finished assets are not duplicated).',details={'assets':results}) from error
        return [_public(r) if 'original' in r else r for r in results]

    def _import_step(self,step,*,audience,attribution,rights_confirmed):
        """E18: one ready step of an import plan uploaded; its result row (E162 s2a: extracted from import_bundle unchanged,
        so ophiolite.restore uploads the same way). Raises what the upload raises."""
        kept=None
        if step.get('provenance') is not None:  # E107a C6b (B2): stage the kept original under the step's own command, then upload with it
            kept=self._stage_kept(step['command_id'],step['provenance'])
            if kept is None:return {**_public(step),'state':'refused','reason':IMPORTED_WITHOUT}  # I1: imports never upgrade
        done=self.upload_data(step['original'],profile=step['profile'],name=step['name'],attribution=attribution,audience=list(audience),
                              rights_confirmed=rights_confirmed,declared=step['declared'] or None,filename=step['filename'],well_log=step['well_log'],
                              command_id=step['command_id'],origin=step['origin'],provenance=kept)
        return {**_public(step),'state':'imported','destination':{'asset_id':done.asset_id,'revision':done.revision}}

    def _stage_kept(self,command_id,raw):
        """E107a C6b: las-uploads/provenance-stage. The upload's `provenance` reference, or None when the item was imported
        before without its original (I1: the deployment stages nothing and refuses; the rest of the bundle continues)."""
        import base64
        from . import publish as planning
        from .errors import IntegrityConflict
        reference={'stage':command_id,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
        header=base64.b64encode(planning.json_bytes({'project_id':self.project,'command_id':command_id,'sha256':reference['sha256'],'bytes':len(raw)})).decode()
        try:answer=self._post_bytes('las-uploads','provenance-stage',raw,extra_headers={'Content-Type':'application/octet-stream','X-Ophiolite-Upload':header},retry=True)
        except IntegrityConflict as error:
            if error.server_message==IMPORTED_WITHOUT:return None
            raise
        if (answer.get('command_id'),answer.get('sha256'),answer.get('bytes'))!=(command_id,reference['sha256'],len(raw)) or answer.get('state') not in ('staged','attached'):
            raise VerificationFailed('The deployment staged another original than the one sent.')
        return reference

    def inspect_las(self,source) -> dict[str, Any]:
        """What the server reads in a LAS file, its well and curves, without keeping the file."""
        import base64
        from . import publish as planning
        raw=planning.upload_bytes(source)
        header=base64.b64encode(planning.json_bytes({'project_id':self.project})).decode()
        return self._post_bytes('las-uploads','inspect',raw,extra_headers={'Content-Type':'application/octet-stream','X-Ophiolite-Upload':header})

    def upload_info(self,asset) -> UploadResult:
        """The record of one exact uploaded original, checked to be the one you named."""
        from . import publish as planning
        from .models.api import UploadResult
        chosen=planning.selection(asset)
        result=planning.parse(UploadResult,self._post('las-uploads','info',{'asset_id':chosen['asset_id']}))
        if result.asset_id!=chosen['asset_id'] or result.revision!=chosen['revision']:raise VerificationFailed('The upload response refers to a different exact asset.')
        return result

    def members(self) -> dict[str, Any]:
        """The account names of the project's members, for an upload's audience: {'members': [...]}."""
        return self._post('las-uploads','members',{})

    def proposals(self) -> list[dict[str, Any]]:
        """What your agents wait for you on in this project, newest first.

        Every pending plan, and every job waiting at a step for your choice. Each is a dict of ophiolite.agent-proposals/1 (`plan`, `operation`,
        `summary`, `evidence`, `budget`, `expires_at`, `review_url`; a waiting job also `question`, `choices` and
        `choice_token`). The answer is checked against that contract (VerificationFailed otherwise). Only a person's
        credential reads it; an agent's is refused by the gateway."""
        # E151 s2
        from . import publish as planning
        return planning.parse_proposals(self._post('agents','proposals',{},retry=True))

    def answer(self,choice_token:str,choice:str) -> dict[str, Any]:
        """Answer the question a job of your agent waits on, with one of the choices it offered.

        The choice is its id ('c1' ... 'c8'); the token is the `choice_token` of `proposals()` or of the agent's
        `ChoiceRequired`. Returns {plan, step, state: 'running',
        choice}; the agent's `resume(plan)` then carries on from that step. A used, foreign or stale token, or one of
        another person's job, raises ChoiceRefused with the gateway's reason in `details['reason']` (token-used,
        token-foreign, token-stale, not-the-delegator). Only the job's delegator answers; an agent's credential is
        refused by the gateway."""
        # E151 s2
        return self._post('jobs','answer',{'choice_token':choice_token,'choice':choice})

    def result_preview(self,asset) -> ResultPreview | RestrictedResultPreview:
        """A preview of one exact result, with only what you may open of its input."""
        from . import publish as planning
        from .models.api import ResultPreview,RestrictedResultPreview
        chosen=planning.selection(asset)
        data=self._post('applications','result-preview',{'id':chosen['asset_id']})
        model=RestrictedResultPreview if 'input' in data and data['input'] is None else ResultPreview
        result=planning.parse(model,data)
        if result.asset_id!=chosen['asset_id'] or result.revision!=chosen['revision']:raise VerificationFailed('The preview refers to a different exact result.')
        return result

    def result_download(self,asset) -> tuple[bytes, Receipt | RestrictedReceipt, Run | RestrictedRun]:
        """The file of one exact result with its receipt and run, checked against the receipt's digest."""
        from . import publish as planning
        from .models.api import RestrictedRun,Receipt,RestrictedReceipt
        chosen=planning.selection(asset)
        data=self._post('applications','result-download',{'id':chosen['asset_id']})
        run=planning.parse_run(data.get('run',{}),self)
        receipt=planning.parse(RestrictedReceipt if isinstance(run,RestrictedRun) else Receipt,{k:v for k,v in data.items() if k not in ('run','payload_base64')})
        if receipt.asset!= {key:chosen[key] for key in ('asset_id','revision','authority')}:raise VerificationFailed('The download refers to a different exact result.')
        raw=planning.decode_payload(data,sha256=receipt.manifest.sha256,length=receipt.manifest.bytes)
        return raw,receipt,run


def written(raw,stated):
    """E58b: a `fill` for save_verified of a body already read whole, with the digest its response stated."""
    def fill(out):
        import hashlib
        out.write(raw);return hashlib.sha256(raw).hexdigest(),stated
    return fill


def save_verified(destination,fill,*,mismatch=DOWNLOAD_MISMATCH):
    """E54, E58b: the one way a downloaded file reaches `destination`. `fill(out)` writes it to a private partial file
    beside `destination` and returns (the SHA-256 of what it wrote, the SHA-256 the deployment stated); the file
    replaces `destination` only when the two are equal and it is fsynced. Otherwise, or on any error, nothing is left."""
    import uuid
    destination=Path(destination)
    partial=destination.with_name('.'+destination.name+'.'+uuid.uuid4().hex[:12]+'.partial')
    try:
        with partial.open('xb') as out:
            written,stated=fill(out)
            out.flush();os.fsync(out.fileno())
        if not stated or written!=stated:raise IntegrityConflict(mismatch)
        os.replace(partial,destination)
    except BaseException:
        partial.unlink(missing_ok=True);raise
    return destination


NOTICE_UNWRITTEN='The licence notice %s could not be written (%s), so the downloaded original was not saved.'  # E212 s1
UNSERVED_PROFILE='serves registered profiles only'  # E212 s1: the gateway's refusal of a profile its scientific routes do not serve


def save_text(destination,text):
    """E212 s1: TEXT at DESTINATION, whole or not at all (a private partial file, fsynced, then renamed)."""
    import uuid
    destination=Path(destination)
    partial=destination.with_name('.'+destination.name+'.'+uuid.uuid4().hex[:12]+'.partial')
    try:
        with partial.open('x',encoding='utf-8') as out:
            out.write(text);out.flush();os.fsync(out.fileno())
        os.replace(partial,destination)
    except BaseException:
        partial.unlink(missing_ok=True);raise
    return destination


IMPORTED_WITHOUT='This was imported before without its original; the original was not added.'  # E107a I1, the deployment's sentence


def _rights_target(kind,ref,key):
    """E35a: what a rights basis is attached to: 'upload' (the original's asset id), 'release' (its id) or 'connection'
    (the connection id, with the target's key)."""
    if kind not in ('upload','release','connection') or not ref or (kind=='connection')!=(key is not None):
        raise Refused('Name an upload, a release, or a connection with its key.')
    return {'target_kind':kind,'target_ref':ref,**({'key':key} if key is not None else {})}


def _public(step):
    return {k:v for k,v in step.items() if k not in ('original','declared','profile','filename','well_log','command_id','name','provenance')}


def session_refusal(view):
    """E54: the error for a file sent in parts that ended without being saved, with the deployment's sentence."""
    reason=view.get('reason') or {}
    code=reason.get('code') if isinstance(reason.get('code'),str) else 'unknown-upload'
    message=reason.get('message') if isinstance(reason.get('message'),str) else 'This upload is no longer known to this deployment. Start it again.'
    kind={'not-a-volume':Refused,'file-mismatch':IntegrityConflict,'access-lost':PermissionRefused}.get(code,Unavailable)
    return kind(message,status=None,code=code)
