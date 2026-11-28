"""E217 s0 (D10): every public name says what it returns, and what it says is this literal inventory.

Each RETURNS entry was written by hand from the method's own `return` (or `yield`) statements and the helpers they
call, never read back from the annotation; the test compares the annotation text with it exactly. The names are those
defined on each checked class itself: methods, property getters (through `fget`), class and static methods and aliases.
A name missing from the inventory, or an entry for a name that no longer exists, fails.

`Any` may appear only in ANY_ALLOWED, each entry with its reason; a name the documents' journeys call (JOURNEY) may not
be there, except the 23 the supervisor's ruling of 26 Nov allows (JOURNEY_ANY, exact): their honest return is decoded
JSON with no contract schema.
"""
import inspect
import re

import pytest
from ophiolite import aio
from ophiolite.access_history import AccessHistoryClient
from ophiolite.aio import AsyncClient
from ophiolite.checks import CheckClient
from ophiolite.client import Client, CurveSet, WellLogSet
from ophiolite.entities import Entity, EntityClient
from ophiolite.locations import LocationClient, Well, Wells
from ophiolite.navigation import Navigation
from ophiolite.outcomes import OutcomeClient
from ophiolite.procedures import ProcedureClient
from ophiolite.rule_results import RuleResultsClient
from ophiolite.sources import SourceClient
from ophiolite.tools import VERBS, ToolClient
from ophiolite.trajectories import TrajectoryClient
from ophiolite.verdicts import VerdictClient

# The twelve classes Client mixes in (C4), in its MRO order.
MIXINS = [Navigation, EntityClient, LocationClient, SourceClient, CheckClient, ProcedureClient, ToolClient, AccessHistoryClient, OutcomeClient,
          VerdictClient, TrajectoryClient, RuleResultsClient]

# D8: the distinct `client.<name>(` calls of the README, the SDK guide and the web guides, from the strategy's text.
JOURNEY = frozenset('''assets associations audience browse change_coordinates change_units create_entity dependents
download_original entities entity exchange export export_corpus export_file export_slices export_trajectories extent
find_log grant_own_ai_use grants history import_bundle import_storage iter_window layouts lineage new_data_defaults
of_entity preview_change provenance publish publish_derived read read_data read_many read_slice read_window recover remake
remake_save search served_limits set_audience set_new_data_defaults share source sources start_sample story sync template
templates upload upload_data upload_las well_imports wells what_changed work_folder'''.split())

RETURNS = {
    Client: {
        'add_survey_members': 'dict[str, Any]',
        'affected': 'dict[str, Any]',
        'affected_pages': 'Iterator[dict[str, Any]]',
        'ai_use': 'dict[str, Any]',
        'answer': 'dict[str, Any]',
        'assets': 'Iterator[AssetItem]',
        'attach_rights': 'dict[str, Any]',
        'bindings': 'list[Binding]',
        'chains': 'ChainClient',
        'change_coordinates': 'PublicationReceipt',
        'change_units': 'PublicationReceipt',
        'close': 'None',
        'configure': 'Binding',
        'create_survey': 'dict[str, Any]',
        'curve_window': 'CurveWindow',
        'describe': 'ScientificAsset',
        'diff': 'ResultDiff',
        'documents': 'DocumentClient',
        'download': 'bytes',
        'download_original': 'Path',
        'exchange': 'PresentedExchange',
        'export': 'Bundle',
        'export_file': 'Path',
        'export_slices': 'Bundle',
        'figures': 'FigureClient',
        'find': 'SearchAnswer | SearchAnswerByMeaning',
        'find_all': 'Iterator[SearchRow]',
        'find_log': 'AssetItem',
        'from_configuration': 'Client',
        'grant_ai_use': 'dict[str, Any]',
        'grants': 'Grants',
        'history': 'History',
        'holder_pages': 'Iterator[dict[str, Any]]',
        'holders': 'dict[str, Any]',
        'identify_survey': 'dict[str, Any]',
        'import_storage': 'Report',
        'imports': 'Imports',
        'inspect': 'dict[str, Any]',
        'inspect_las': 'dict[str, Any]',
        'iter_window': 'WindowReader',
        'layouts': 'Layouts',
        'link_survey_members': 'dict[str, Any]',
        'members': 'dict[str, Any]',
        'options': 'dict[str, Any]',
        'proposals': 'list[dict[str, Any]]',
        'provenance': 'Provenance',
        'public_repositories': 'PublicRepositories',
        'publish': 'Receipt',
        'publish_derived': 'PresentedReceipt',
        'read': 'CurveSet',
        'read_data': 'TypedData',
        'read_many': 'list[CurveSet]',
        'read_slice': 'SeismicSlice',
        'read_window': 'VolumeWindowResult',
        'receipt_pages': 'Iterator[dict[str, Any]]',
        'receipts': 'dict[str, Any]',
        'recover': 'Binding | Run | Receipt | UploadResult | None',
        'relate_survey_members': 'dict[str, Any]',
        'remove_survey_members': 'dict[str, Any]',
        'rename_survey': 'dict[str, Any]',
        'renew_rights': 'dict[str, Any]',
        'replace_survey_member': 'dict[str, Any]',
        'restate_survey': 'dict[str, Any]',
        'result_download': 'tuple[bytes, Receipt | RestrictedReceipt, Run | RestrictedRun]',
        'result_groups': 'list[ResultGroup]',
        'result_preview': 'ResultPreview | RestrictedResultPreview',
        'results': 'list[ResultSummary | RestrictedResultSummary]',
        'rights': 'dict[str, Any]',
        'run_input': 'tuple[bytes, ApplicationCurve]',
        'share': 'Grants | UploadResult | ResultSummary | RestrictedResultSummary',
        'start': 'Run',
        'survey': 'Survey',
        'survey_history': 'Iterator[dict[str, Any]]',
        'survey_pages': 'Iterator[SurveyPage]',
        'surveys': 'Iterator[dict[str, Any]]',
        'sync': 'Sync',
        'table_kinds': 'TableKindClient',
        'template': 'Template',
        'transfer_codes_kept': 'bool',
        'unrelate_survey_members': 'dict[str, Any]',
        'upload': 'Report',
        'upload_data': 'UploadResult',
        'upload_info': 'UploadResult',
        'upload_las': 'UploadResult',
        'upload_reads': 'bool',
        'upload_runs': 'UploadRuns',
        'well_imports': 'WellImports',
        'well_names': 'WellNames',
        'well_sets': 'WellSets',
        'withdraw_survey': 'dict[str, Any]',
        'work_folder': 'WorkFolder',
    },
    CurveSet: {
        'evidence': 'dict[str, str]',
        'save': 'None',
        'to_frame': 'tuple[pd.DataFrame, Descriptor]',
        'to_numpy': 'tuple[npt.NDArray[np.float64], Descriptor]',
        'workspace_url': 'str | None',
    },
    WellLogSet: {
        'to_frame': 'tuple[pd.DataFrame, WellLogDescriptor]',
        'to_numpy': 'tuple[npt.NDArray[np.float64], WellLogDescriptor]',
    },
    Wells: {
        'to_frame': 'pd.DataFrame',
        'to_geojson': 'dict[str, Any]',
        'with_source': 'pd.DataFrame',
    },
    Well: {},
    # C4: the mixins. Most answers are a `_post` answer handed on as decoded JSON (dict[str, Any], on ANY_ALLOWED).
    Navigation: {
        'data': 'list[dict[str, Any]]',  # _follow('of-entity'): every page's items gathered
        'part_of': 'dict[str, Any]',  # _associate: entities/associate as served
        'parts': 'list[Entity]',  # _follow('part-of'): e.wellbores()
    },
    Entity: {
        'assets': 'list[dict[str, Any]]',  # self._client.data(...): _follow's items
        'well': 'Entity | None',  # self._client.entity(link) or None
        'wellbores': 'list[Entity]',  # [] or [self._client.entity(p) ...]
    },
    EntityClient: {
        'create_entity': 'Entity',
        'dissociate': 'dict[str, Any]',
        'entities': 'Iterator[Entity]',  # yields Entity(self, doc)
        'entity': 'Entity',  # the Entity given, or Entity(self, entities/get)
        'identify': 'Entity',
        'share_entity': 'dict[str, Any]',
    },
    LocationClient: {
        'wells': 'Wells',
    },
    SourceClient: {
        'org_connections': 'list[dict[str, Any]]',  # page['connections'] of a checked OrgConnectionsPage answer
        'source': 'Source',  # found[0] of sources()
        'sources': 'list[Source]',
    },
    CheckClient: {
        'check_compare': 'dict[str, Any]',
        'check_list': 'dict[str, Any]',
        'check_publish': 'dict[str, Any]',
        'check_publishers': 'dict[str, Any]',
    },
    ProcedureClient: {
        'accepted_results': 'dict[str, Any]',
        'deliver': 'dict[str, Any]',  # _set_aside, _delivery_again or _deliver_once: each builds {sentence, delivery_id, state, ...}
        'procedure_again': 'dict[str, Any]',  # {**published, 'ran': ...}
        'procedure_bundle': 'bytes',  # base64.b64decode(out['archive'])
        'procedure_enable': 'dict[str, Any]',
        'procedure_get': 'dict[str, Any]',
        'procedure_list': 'list[dict[str, Any]]',  # answer['versions']
        'procedure_prepare_again': 'dict[str, Any]',
        'procedure_publish': 'dict[str, Any]',  # {sentence, run, outputs}
        'procedure_register': 'dict[str, Any]',
        'procedure_run': 'PresentedRun',  # run(...) -> _presented -> PresentedRun.present
        'procedure_run_get': 'dict[str, Any]',
        'procedure_sandbox_enable': 'dict[str, Any]',
        'procedure_sandbox_job': 'dict[str, Any]',  # the runners/job answer as last seen
        'procedure_sandbox_run': 'dict[str, Any]',  # the job, or procedure_sandbox_job(...)
        'procedure_trust': 'dict[str, Any]',
        'procedure_verifications': 'dict[str, Any]',
        'procedure_verify': 'dict[str, Any]',
        'procedure_version': 'dict[str, Any]',  # max(chosen) of procedure_list's rows
        'procedure_withdraw': 'dict[str, Any]',
        'reference_cases_declare': 'dict[str, Any]',
        'reference_cases_get': 'dict[str, Any]',
        'reference_cases_withdraw': 'dict[str, Any]',
        'reference_run_get': 'dict[str, Any]',
        'reference_run_list': 'dict[str, Any]',
        'reference_run_start': 'dict[str, Any]',
        'source_run': 'dict[str, Any]',  # {sentence, run, report, kept} or _source_send's
    },
    AccessHistoryClient: {
        'access_history': 'list[dict[str, Any]]',  # _pages: every page's entries
        'access_teams': 'list[dict[str, Any]]',  # page['teams']
        'export_access_history': 'Path',  # _export: Path(dest)
    },
    OutcomeClient: {
        'outcome_claims': 'list[dict[str, Any]]',  # answer['claims']
        'outcome_declare': 'dict[str, Any]',
        'outcome_disable': 'dict[str, Any]',
        'outcome_enable': 'dict[str, Any]',
        'outcome_evaluate': 'dict[str, Any]',
        'outcome_get': 'dict[str, Any]',
        'outcome_list': 'list[dict[str, Any]]',  # answer['outcomes']
        'outcome_named': 'dict[str, Any]',  # found[0] of outcome_list()
        'outcome_revise': 'dict[str, Any]',
        'outcome_states': 'dict[str, Any]',
        'outcome_withdraw': 'dict[str, Any]',
        'result_version': 'tuple[str, str]',  # (asset, revision)
        'tool_declaration': 'dict[str, Any]',  # outcomes.tool_declaration builds the ophiolite.outcome/1 dict
        'try_output': 'dict[str, Any]',
        'try_result': 'dict[str, dict[str, Any]]',  # {role: try_output(...)}
    },
    VerdictClient: {
        'record_verdict': 'dict[str, Any]',
        'verdicts': 'dict[str, Any]',
        'withdraw': 'dict[str, Any]',
    },
    TrajectoryClient: {},
    RuleResultsClient: {
        'rule_results': 'dict[str, Any]',
    },
}
# D3: each twin returns what its procedure_<verb> returns (it calls it); the annotations are copied by functools.wraps.
RETURNS[ToolClient] = {'tool_' + verb: RETURNS[ProcedureClient]['procedure_' + verb] for verb in VERBS}

# Attributes a reader of the checked classes uses, as declared in each class body (inspect.get_annotations).
ATTRIBUTES = {
    CurveSet: {'descriptors': 'list[ScientificAsset]', 'curves': 'list[ApplicationCurve]', 'artifact': 'bytes', 'url': 'str',
               'project': 'str'},
    WellLogSet: {'curves': 'list[WellLog]'},
    Wells: {'crs': 'str | None', 'untransformed': 'int'},
    Well: {'document': 'dict[str, Any]', 'entity_id': 'str', 'name': 'str', 'location': 'dict[str, Any] | None'},
    Entity: {'document': 'dict[str, Any]', 'entity_id': 'str', 'kind': 'str', 'name': 'str', 'identity': 'dict[str, Any]', 'generation': 'int'},
}

SERVER_JSON = 'the server answer as decoded JSON; the SDK has no contract type for it'
ANY_ALLOWED = {
    **{(Client, name): SERVER_JSON for name in (
        'ai_use', 'answer', 'attach_rights', 'grant_ai_use', 'inspect', 'inspect_las', 'members', 'options', 'rights',
        'renew_rights')},
    **{(Client, name): 'a survey command answer (surveys/<kind>), decoded JSON with no contract type in the SDK' for name in (
        'add_survey_members', 'create_survey', 'identify_survey', 'link_survey_members', 'relate_survey_members',
        'remove_survey_members', 'rename_survey', 'replace_survey_member', 'restate_survey', 'unrelate_survey_members',
        'withdraw_survey')},
    (Client, 'surveys'): "each survey row of surveys/list as served (page['surveys'])",
    (Client, 'survey_history'): "each event of surveys/history as served (page['events'])",
    (Client, 'affected'): 'affected_whole: rows and counts of every validated page gathered into a plain dict',
    (Client, 'affected_pages'): 'each raw page, validated against ophiolite.affected/1 (Affected) and yielded as served',
    (Client, 'holder_pages'): 'each raw page, validated against ophiolite.held-copies/1 (HeldCopies) and yielded as served',
    (Client, 'holders'): "the first holders page as a dict with every page's rows",
    (Client, 'receipt_pages'): 'each raw page, validated against ophiolite.transfer-receipts/1 and yielded as served',
    (Client, 'receipts'): "the first receipts page as a dict with every page's gets",
    (Client, 'proposals'): "data['proposals'] of a validated ophiolite.agent-proposals/1 envelope, each as served",
    (Wells, 'to_geojson'): 'a GeoJSON FeatureCollection built here from the wells',
    (Well, 'document'): 'the well listing item as served: EntityPage.entities is list[dict], no contract schema (D4)',
    (Well, 'location'): "the listing item's location as served (x, y, crs, source, ambiguous), no contract schema",
    # C4: the mixins
    (Navigation, 'data'): "each association item of entities/assets as served (page['items'] of every page)",
    (Navigation, 'part_of'): SERVER_JSON + ' (entities/associate)',
    (Entity, 'assets'): "Navigation.data's items: each association item of entities/assets as served",
    (Entity, 'document'): 'the entity document as served (entities/get, list, create, identify), no contract type in the SDK',
    (Entity, 'identity'): "document['identity'] as served: {provisional} or {authority, key}",
    (EntityClient, 'dissociate'): SERVER_JSON + ' (entities/dissociate)',
    (EntityClient, 'share_entity'): SERVER_JSON + ' (entities/share)',
    (SourceClient, 'org_connections'): "page['connections'] of an answer checked against OrgConnectionsPage, each connection as served",
    **{(CheckClient, name): SERVER_JSON + ' (checks/<operation>)' for name in ('check_compare', 'check_list', 'check_publish', 'check_publishers')},
    **{(ProcedureClient, name): SERVER_JSON for name in (
        'accepted_results', 'procedure_enable', 'procedure_get', 'procedure_prepare_again', 'procedure_register', 'procedure_run_get',
        'procedure_sandbox_enable', 'procedure_sandbox_job', 'procedure_sandbox_run', 'procedure_trust', 'procedure_verifications',
        'procedure_verify', 'procedure_withdraw', 'reference_cases_declare', 'reference_cases_get', 'reference_cases_withdraw',
        'reference_run_get', 'reference_run_list', 'reference_run_start')},
    (ProcedureClient, 'procedure_list'): "answer['versions'] of procedures/list, each version row as served",
    (ProcedureClient, 'procedure_version'): "one version row of procedures/list as served",
    (ProcedureClient, 'deliver'): 'a delivery answer built here ({sentence, delivery_id, state, items, destination, reported}) whose '
                                  'state and items come from the writer or the server as decoded JSON',
    (ProcedureClient, 'procedure_publish'): '{sentence, run, outputs} built here around procedure-runs/get and each receipt as decoded JSON',
    (ProcedureClient, 'procedure_again'): "procedure_publish's answer with the run's sentence added",
    (ProcedureClient, 'source_run'): '{sentence, run, report, kept} (or outcome and outcome_sentence) built here; the run record is local JSON',
    (AccessHistoryClient, 'access_history'): "every entry of access/history as served (page['entries'] of every page)",
    (AccessHistoryClient, 'access_teams'): "page['teams'] of access/teams as served",
    **{(OutcomeClient, name): SERVER_JSON + ' (outcomes/<operation>)' for name in (
        'outcome_declare', 'outcome_disable', 'outcome_enable', 'outcome_evaluate', 'outcome_get', 'outcome_revise', 'outcome_states',
        'outcome_withdraw', 'try_output')},
    (OutcomeClient, 'outcome_claims'): "answer['claims'] of outcomes/claims, each claim as served",
    (OutcomeClient, 'outcome_list'): "answer['outcomes'] of outcomes/list, each outcome as served",
    (OutcomeClient, 'outcome_named'): "one outcome row of outcomes/list as served",
    (OutcomeClient, 'tool_declaration'): "an ophiolite.outcome/1 declaration built here; its settings are the caller's values",
    (OutcomeClient, 'try_result'): "{role: try_output's answer}, each the outcome-trial answer as served",
    **{(VerdictClient, name): SERVER_JSON for name in ('record_verdict', 'verdicts', 'withdraw')},
    (RuleResultsClient, 'rule_results'): SERVER_JSON + ' (rule-results/get: {asset_id, revision, results, lines})',
}
ANY_ALLOWED.update({(ToolClient, 'tool_' + verb): 'the twin answers what procedure_%s answers: ' % verb + ANY_ALLOWED[(ProcedureClient, 'procedure_' + verb)]
                    for verb in VERBS if (ProcedureClient, 'procedure_' + verb) in ANY_ALLOWED})

# C4b (supervisor ruling, 26 Nov): the 23 journey names whose honest return is decoded JSON are typed so and allowed Any.
# Each entry was written from its return statements (the comment names them). JOURNEY_ANY below freezes the names: a
# 24th journey name on ANY_ALLOWED fails.
RULED = 'decoded JSON, no contract schema'
JOURNEY_JSON_RETURNS = {
    (Client, 'audience'): 'dict[str, Any]',  # new_data.audience -> _audience_snapshot builds a dict from las-uploads/audience
    (Client, 'export_corpus'): 'dict[str, Any]',  # corpus.export_corpus -> verify(destination), a summary dict
    (Client, 'grant_own_ai_use'): 'dict[str, Any]',  # _post('ai-use', 'self-grant') as served
    (Client, 'import_bundle'): 'list[dict[str, Any]]',  # [_public(r) or r for r in results], one dict per asset
    (Client, 'new_data_defaults'): 'dict[str, Any]',  # new_data.defaults -> _snapshot of context/new-data
    (Client, 'preview_change'): 'dict[str, Any]',  # _in_its_words(_post('publications', 'transform-preview'))
    (Client, 'search'): 'dict[str, Any]',  # _post('search', 'query') as served
    (Client, 'served_limits'): 'dict[str, Any]',  # self._served_limits: the capabilities answer's `limits` dict
    (Client, 'set_audience'): 'dict[str, Any]',  # new_data.save -> _audience_snapshot of las-uploads/audience-save
    (Client, 'set_new_data_defaults'): 'dict[str, Any]',  # new_data.set_defaults -> _snapshot of context/new-data-save
    (Client, 'start_sample'): 'dict[str, Any]',  # table_templates.start_sample builds {run_id, log, wells, statement}
    (Client, 'templates'): 'list[dict[str, Any]]',  # table_templates.listing: the served template rows
    (Navigation, 'of_entity'): 'dict[str, Any]',  # _associate: entities/associate as served
    (EntityClient, 'associations'): 'Iterator[dict[str, Any]]',  # yield from page['items'] of entities/associations
    (EntityClient, 'dependents'): 'dict[str, Any]',  # _post('results', 'dependents')
    (EntityClient, 'lineage'): 'dict[str, Any]',  # _entities('lineage')
    (EntityClient, 'remake'): 'dict[str, Any]',  # _in_its_words(_post('results', 'remake-run'))
    (EntityClient, 'remake_save'): 'dict[str, Any]',  # _in_its_words(_post('results', 'remake-save'))
    (EntityClient, 'story'): 'dict[str, Any]',  # _post('results', 'story')
    (EntityClient, 'what_changed'): 'dict[str, Any]',  # _post('results', 'what-changed')
    (LocationClient, 'extent'): 'dict[str, Any]',  # checked(EntityExtent, entities/extent) hands the answer on
    (SourceClient, 'browse'): 'dict[str, Any]',  # _checked(SourceBrowsePage, sources/discover) hands the answer on
    (TrajectoryClient, 'export_trajectories'): 'dict[str, Any]',  # trajectories.export builds {episodes, values, destination, parquet}
}
for (_cls, _name), _text in JOURNEY_JSON_RETURNS.items():
    assert _name not in RETURNS[_cls]
    RETURNS[_cls][_name] = _text
    ANY_ALLOWED[(_cls, _name)] = RULED
del _cls, _name, _text

# The only journey names allowed Any, frozen as a literal (ruling 26 Nov).
JOURNEY_ANY = frozenset('''associations audience browse dependents export_corpus export_trajectories extent grant_own_ai_use
import_bundle lineage new_data_defaults of_entity preview_change remake remake_save search served_limits set_audience
set_new_data_defaults start_sample story templates what_changed'''.split())

# C6: AsyncClient's own names, each written from its own `return` (or `yield`): what an awaited call gives. A paged read
# is gathered into a list by `_listed` (one worker), so it is the list of the Client iterator's items.
RETURNS[AsyncClient] = {
    'aclose': 'None',  # aclose = close
    'affected_pages': 'list[dict[str, Any]]',  # _listed('affected_pages', ...)
    'assets': 'AsyncIterator[AssetItem]',  # yields each catalogue item
    'close': 'None',
    'curve_window': 'CurveWindow',  # window.result()
    'describe': 'ScientificAsset',  # _core.verify_descriptor
    'export_slices': 'Bundle',  # write_bundle, in a worker
    'find_all': 'list[SearchRow]',  # _listed('find_all', ...)
    'holder_pages': 'list[dict[str, Any]]',  # _listed('holder_pages', ...)
    'iter_window': 'AsyncWindowReader',
    'provenance': 'Provenance',  # _provenance_of
    'read': 'CurveSet',
    'read_data': 'TypedData',  # _core.typed_result
    'read_many': 'list[CurveSet]',  # one read each, in order
    'read_slice': 'SeismicSlice',  # _core.slice_result
    'read_window': 'VolumeWindowResult',
    'source': 'AsyncSource',
    'sources': 'list[AsyncSource]',
    'survey_history': 'list[dict[str, Any]]',  # _listed('survey_history', ...)
    'survey_pages': 'list[SurveyPage]',  # _listed('survey_pages', ...)
    'surveys': 'list[dict[str, Any]]',  # _listed('surveys')
    'work_folder': 'AsyncWorkFolder',
}
# D2: each coroutine the loop attaches answers, awaited, what its Client method returns (functools.wraps copies the
# annotation; tests/test_async_declarations.py holds the declarations to the same text).
ASYNC_ATTACHED = '''add_survey_members affected configure create_survey download download_original export find find_log grants history
holders identify_survey inspect inspect_las link_survey_members members options publish receipts recover relate_survey_members
remove_survey_members rename_survey replace_survey_member restate_survey result_download result_preview results run_input
served_limits share start survey unrelate_survey_members upload_data upload_info upload_las withdraw_survey'''.split()
RETURNS[AsyncClient].update({name: RETURNS[Client][name] for name in ASYNC_ATTACHED})
# The names AsyncClient refuses at once (TypeError naming Client) have no return; tests/test_aio_parity.py keeps them exact.
ASYNC_REFUSED = frozenset(aio._SYNC_ONLY) | frozenset(aio._SYNC_ONLY_PROPERTIES)
ANY_ALLOWED.update({(AsyncClient, name): 'awaited, it answers what Client.%s answers: ' % name + ANY_ALLOWED[(Client, name)]
                    for name, text in RETURNS[AsyncClient].items() if re.search(r'\bAny\b', text)})

CLASSES = [Client, CurveSet, WellLogSet, Wells, Well, Entity, *MIXINS, AsyncClient]


def returns(cls):
    """Each public name defined on CLS itself → its return annotation as written (None when it has none)."""
    found = {}
    for name, raw in vars(cls).items():
        if name.startswith('_') or (cls is AsyncClient and name in ASYNC_REFUSED): continue
        if isinstance(raw, property): function = raw.fget
        elif isinstance(raw, (classmethod, staticmethod)): function = raw.__func__
        elif callable(raw): function = raw
        else: continue  # class data such as WellLogSet.form
        found[name] = inspect.get_annotations(function).get('return')
    return found


def says_any(text):
    return re.search(r'\bAny\b', text) is not None


@pytest.mark.parametrize('cls', CLASSES, ids=lambda c: c.__name__)
def test_every_public_name_returns_what_the_inventory_says(cls):
    """Mutations: an annotation deleted or changed, a new public name without an entry, an entry for a removed name."""
    found, frozen = returns(cls), RETURNS[cls]
    assert sorted(set(found) - set(frozen)) == [], 'public names with no inventory entry'
    assert sorted(set(frozen) - set(found)) == [], 'inventory entries for names that no longer exist'
    assert {name: found[name] for name in frozen} == frozen


@pytest.mark.parametrize('cls', list(ATTRIBUTES), ids=lambda c: c.__name__)
def test_the_attributes_readers_use_are_declared(cls):
    assert inspect.get_annotations(cls) == ATTRIBUTES[cls]


def test_any_appears_only_where_allowed():
    texts = {(cls, name): text for cls, names in RETURNS.items() for name, text in names.items()}
    texts.update({(cls, name): text for cls, names in ATTRIBUTES.items() for name, text in names.items()})
    assert sorted((cls.__name__, name) for (cls, name), text in texts.items() if says_any(text) and (cls, name) not in ANY_ALLOWED) == []
    assert sorted((cls.__name__, name) for (cls, name) in ANY_ALLOWED if not says_any(texts.get((cls, name), ''))) == [], 'stale'
    assert all(reason.strip() for reason in ANY_ALLOWED.values())


def test_every_class_the_client_mixes_in_is_inventoried():
    assert [c for c in Client.__mro__ if c.__module__.startswith('ophiolite.') and c is not Client] == MIXINS


def test_the_journey_names_allowed_any_are_exactly_the_ruled_ones():
    """Ruling 26 Nov: 23 journey names return decoded JSON. Mutation: a 24th journey name typed with Any and allowed."""
    # the journeys call `client.<name>(`: names of Client and of what it mixes in (Entity.assets is not one)
    allowed = {name for (cls, name) in ANY_ALLOWED if cls in (Client, *MIXINS) and name in JOURNEY}
    assert sorted(allowed) == sorted(JOURNEY_ANY)
    assert JOURNEY_ANY <= JOURNEY and len(JOURNEY_ANY) == 23
    assert {ANY_ALLOWED[key] for key in JOURNEY_JSON_RETURNS} == {RULED}
