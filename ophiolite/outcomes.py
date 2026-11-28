"""E120: outcomes — what a project accepts for a kind of result, by a built-in rule and its settings, and where an
accepted result is delivered. A project administrator declares, revises, enables, disables and withdraws them; every
member lists and reads them. Each change is a new version on the server that is never altered.

A declaration is `ophiolite.outcome/1` (`ophiolite/contracts/outcomes/v1/`); the server checks it and refuses it with
one reason (`error.details['reason']`). From slice 1 the server evaluates every enabled outcome over a residual result
after it is published, with the declarer's reading rights, and keeps an acceptance record (`ophiolite.outcome-check/1`);
`outcome_states` reads a result version's states as sentences ("Accepted on ... under Tops within 5 m version 1").
From slice 3 `ophiolite exchange deliver NAME --as OUTCOME` (`Client.deliver(..., as_=...)`) asks the project's gate first: the
delivery runs only when the version is accepted under the outcome's current version and goes to its declared
destination; every claim, claimed or refused, is kept on the server (`ophiolite.outcome-claim/1`, `outcome_claims`).
"""
from __future__ import annotations  # E217 s0 (D1): annotations stay strings; nothing below is imported to run

import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # E217 s0 (D1): read by a type checker only
    from typing import Any

KIND = 'well-residual/1'
RULE = 'well-residual-within/1'
INPUTS = ['deviation-csv/1', 'esri-ascii-grid/1', 'well-set/1', 'well-tops-csv/1']  # what a residual result is made from


def residual_declaration(label, tolerance, unit, procedure, destination, not_computed='allowed', data_rules=None):
    """The declaration of an outcome over residual results: every computed residual within `tolerance` `unit`. E144 s4:
    `data_rules`, the data rule ids run on the inputs first (sorted, once each); None names none and sends no key."""
    rule = {'name': RULE, 'settings': {'tolerance': {'value': tolerance, 'unit': unit}, 'not_computed': not_computed}}
    if data_rules is not None: rule['data_rules'] = list(data_rules)
    return {'schema': 'ophiolite.outcome/1', 'label': label, 'kind': KIND, 'rule': rule,
            'inputs': list(INPUTS), 'destination': {'procedure': procedure, 'label': destination}}


TOOL_RULE = 'tool-check/1'


def tool_declaration(label, kind, digest, manifest, settings, procedure, destination):
    """E179 s1: the declaration of an outcome whose rule is a tool version (`digest`, a verified check tool of the
    project): the tool's answer decides. Its inputs are the kinds the tool's manifest reads; `settings` go to the tool
    as it declares them. `OutcomeClient.tool_declaration` resolves the digest and manifest from the catalogue."""
    inputs = sorted({k for i in manifest['inputs'] if isinstance(i, dict) and i.get('class') == 'version' for k in i['kinds']})
    return {'schema': 'ophiolite.outcome/1', 'label': label, 'kind': kind, 'rule': {'name': TOOL_RULE, 'tool': {'digest': digest}, 'settings': dict(settings)},
            'inputs': inputs, 'destination': {'procedure': procedure, 'label': destination}}


def state_lines(answer):
    """A result version's outcome states in words: one line per outcome, its earlier publications and versions below."""
    lines = []
    for o in answer['outcomes']:
        lines.append('%s: %s' % (o['label'], o['line']))
        lines += ['  ' + more for more in o['earlier_publications'] + o['earlier_versions']]
    return '\n'.join(lines) or 'No outcome is declared over this kind of result.'


def _checks():
    """The words of a record's reason (`outcome-reasons.json` `checks`), as `state_lines` reads them from the server."""
    import importlib.resources
    import json
    return json.loads(importlib.resources.files('ophiolite').joinpath('contracts/vocabulary/v1/outcome-reasons.json').read_bytes())['checks']


def _reason_words(reason):
    """A reason's words; a phrase that needs the record (the kinds, the units) keeps its words before the colon."""
    text = _checks()[reason]
    if '{' not in text: return text
    return text.split(':')[0] if ':' in text else 'made without an input kind it reads'


def trial_lines(answer):
    """E176 s1: a trial in words, one line per outcome; no row identifiers or reason codes (those are in --json)."""
    if not answer['outcomes']: return answer['sentence']
    lines = []
    for o in answer['outcomes']:
        if o['would'] == 'accepted': said = 'would be accepted'
        elif o['would'] == 'rejected' and o['reason'] is None:
            rows = o['rows']  # E176 s2a (R4): the not-computed list is capped at 20, so required rows are counted from the counts
            missing = rows['passing'] + rows['failing_count'] - rows['computed'] if any(not r['pass'] for r in rows['not_computed']) else 0
            over = rows['failing_count'] - missing
            limit = (rows['failing'] or rows['not_computed'])[0]
            parts = ['%d %s over %s %s' % (over, 'row' if over == 1 else 'rows', '%g' % limit['limit'], limit['unit'])] if over else []
            parts += ['%d required %s not computed' % (missing, 'row' if missing == 1 else 'rows')] if missing else []
            said = 'would be rejected: ' + ', '.join(parts)
        elif o['would'] == 'rejected': said = 'would be rejected: ' + _reason_words(o['reason'])
        elif o['would'] == 'not_compared': said = 'would not be compared: ' + _reason_words(o['reason'])
        elif o['would'] == 'not_evaluated': said = 'would not be evaluated: ' + o['sentence'].removeprefix('Would not be evaluated: ')
        else: said = 'not tried: ' + o['sentence'].removeprefix('Not tried: ')
        lines.append('%s: %s' % (o['label'], said))
    return '\n'.join(lines)


def summary_line(o):
    """One outcome in words: its name, state and version, what it accepts and where it delivers."""
    return '"%s" (%s, version %d): %s, %s; delivered to %s.' % (o['label'], o['state'], o['version'], o['words']['kind'], o['words']['rule'], o['words']['destination'])


class OutcomeClient:
    """Mixed into `Client` (uses its `_post`). Each write sends a new command id unless one is given; the same id with
    the same body answers the stored result."""

    def outcome_list(self) -> list[dict[str, Any]]:
        """The project's outcomes in the order they were first declared, withdrawn ones included."""
        return self._post('outcomes', 'list', {}, retry=True)['outcomes']

    def outcome_get(self, outcome_id: str) -> dict[str, Any]:
        """One outcome with every version and every action on it."""
        return self._post('outcomes', 'get', {'outcome_id': outcome_id}, retry=True)

    def outcome_named(self, label: str) -> dict[str, Any]:
        """The outcome that is not withdrawn and carries this name (names are compared without case)."""
        from .errors import Refused
        found = [o for o in self.outcome_list() if o['state'] != 'withdrawn' and o['label'].casefold() == label.casefold()]
        if not found: raise Refused('This project has no outcome named "%s".' % label)
        return found[0]

    def tool_declaration(self, label: str, tool: str, version: int, settings, procedure, destination, kind: str = KIND) -> dict[str, Any]:
        """The tool declaration of an outcome, for "<tool> version <version>" of the catalogue (by the tool's name).

        It is refused before anything is sent when the project lists no such version or more than one.
        """
        # E179 s1
        from .errors import Refused
        found = [v for v in self.procedure_list(tool) if v['version'] == version]
        if not found: raise Refused('This project lists no version %d of the tool "%s".' % (version, tool))
        if len(found) > 1: raise Refused('This project lists more than one version %d of the tool "%s"; declare it through the API by its digest.' % (version, tool))
        digest = found[0]['digest']
        return tool_declaration(label, kind, digest, self.procedure_get(digest)['manifest'], settings, procedure, destination)

    def _outcome_write(self, operation, body, command_id):
        return self._post('outcomes', operation, {'command_id': command_id or '%s-%s' % (operation, uuid.uuid4().hex), **body}, retry=True)

    def outcome_declare(self, declaration, *, command_id: str | None = None) -> dict[str, Any]:
        """Declare an outcome (project administrators); it is enabled at version 1."""
        return self._outcome_write('declare', {'declaration': declaration}, command_id)

    def outcome_revise(self, outcome_id: str, declaration, *, command_id: str | None = None) -> dict[str, Any]:
        """Its next version, when anything differs (refused `unchanged` otherwise); earlier versions stay as they were."""
        return self._outcome_write('revise', {'outcome_id': outcome_id, 'declaration': declaration}, command_id)

    def outcome_enable(self, outcome_id: str, *, command_id: str | None = None) -> dict[str, Any]:
        """Enable a disabled outcome again, so results of its kind are judged against it (project administrators)."""
        return self._outcome_write('enable', {'outcome_id': outcome_id}, command_id)

    def outcome_disable(self, outcome_id: str, *, command_id: str | None = None) -> dict[str, Any]:
        """Disable an outcome until it is enabled again; nothing is judged against it meanwhile (project administrators)."""
        return self._outcome_write('disable', {'outcome_id': outcome_id}, command_id)

    def outcome_withdraw(self, outcome_id: str, *, command_id: str | None = None) -> dict[str, Any]:
        """Withdraw for good; the name is free again."""
        return self._outcome_write('withdraw', {'outcome_id': outcome_id}, command_id)

    # --- E120 s1: the states of a result version ---------------------------------------------------------------------

    def outcome_states(self, asset_id: str, revision: str) -> dict[str, Any]:
        """What each outcome says about a result version you can read (refused `result` otherwise).

        The answer is {asset_id, revision, outcomes: [{outcome_id, label, version, state, reason, check_id, line,
        earlier_publications, earlier_versions}]}.
        """
        return self._post('outcomes', 'states', {'asset_id': asset_id, 'revision': revision}, retry=True)

    def outcome_evaluate(self, asset_id: str, revision: str) -> dict[str, Any]:
        """Evaluate again where no record exists yet (a missed evaluation), then the states; a record is never changed."""
        return self._post('outcomes', 'evaluate', {'asset_id': asset_id, 'revision': revision}, retry=True)

    # --- E176 s1: try a result before publishing it ---------------------------------------------------------------------

    def try_output(self, raw: bytes, header, *, report=None, role: str | None = None, outcome_ids=None) -> dict[str, Any]:
        """What each enabled outcome of the result's kind would say about these bytes, were they published.

        The answer is `ophiolite.outcome-trial/1`. `header` is the publications/derive header (`publish.derive_request`'s
        body): with its `run` for a reported run, or without it and with `report` (the procedure-runs/report body) and
        `role` for a run not yet reported. Nothing is published, reported or kept."""
        import base64
        from .publish import json_bytes
        body = {'header': base64.b64encode(json_bytes(header)).decode(), 'content_base64': base64.b64encode(raw).decode()}
        if report is not None: body['run'] = {'report': report, 'role': role}
        if outcome_ids is not None: body['outcome_ids'] = list(outcome_ids)
        return self._post('outcomes', 'try', body, retry=True)

    def try_result(self, folder, *, role: str | None = None, outcomes=None) -> dict[str, dict[str, Any]]:
        """Try a run folder's outputs against the project's outcomes before you publish them.

        The folder is read as `procedure_publish` reads it (each output's SHA-256 checked), and for each output whose
        kind outcomes are declared over (or the one `role` names) the header publication would carry and the report it
        would send are tried. `outcomes` names outcomes (by name) to try; every enabled one of the
        kind when None. Nothing is reported, so the folder and a later `procedure_publish` of it are unchanged.
        Returns {role: the outcome-trial answer}."""
        import uuid
        from pathlib import Path
        from .procedures import local_run, method_of, report_inputs, run_parents
        from .publish import derive_request
        from .writers import WrittenOriginal
        folder = Path(folder)
        record, outputs = local_run(folder)
        version = self.procedure_get(record['procedure']['digest'])
        report = {'command_id': 'try-' + uuid.uuid4().hex, 'procedure': {'digest': record['procedure']['digest']}, 'settings': record['settings'],
                  'inputs': report_inputs(record), 'outputs': outputs}
        method, parents = method_of(version, record['settings']), run_parents(version['manifest'], record)
        ids = None if outcomes is None else [self.outcome_named(name)['outcome_id'] for name in outcomes]
        chosen = [o['role'] for o in outputs if (o['role'] == role if role is not None else record['outputs'][o['role']]['profile'] == KIND)]
        answers = {}
        for name in chosen:
            local = record['outputs'][name]
            raw = (folder / local['file']).read_bytes()
            title = (version['label'] if len(outputs) == 1 else '%s: %s' % (version['label'], name))[:160]
            header, _ = derive_request(self.project, WrittenOriginal(raw, local['profile'], dict(local['declared'] or {})), name=title, from_=parents,
                                       method=method, command_id='try-' + uuid.uuid4().hex)
            answers[name] = self.try_output(raw, header, report=report, role=name, outcome_ids=ids)
        return answers

    # --- E120 s3: the claims "Deliver as" made -------------------------------------------------------------------------

    def outcome_claims(self) -> list[dict[str, Any]]:
        """The project's "Deliver as" claims you may see now, oldest first.

        Each is {claim_id, state, reason, sentence, delivery_id, outcome, result, check, destination, by, delivery}.
        `state` is the gate's (claimed or refused) and
        never changes; `delivery` {state, line} is what became of a claimed claim's delivery, as the result's story
        tells it (claimed, confirmed, not-sent, unknown or mismatch; adhoc-e121-claims)."""
        return self._post('outcomes', 'claims', {}, retry=True)['claims']

    def result_version(self, text: str) -> tuple[str, str]:
        """The (asset_id, revision) of a version named as `ITEM[@N]` or `@ASSET:REVISION`.

        `ITEM[@N]` is the project item by its name and its version number (default its latest), as
        `procedures again --item` names one; `@ASSET:REVISION` is exactly that version when it is one you can see.
        """
        # adhoc-e121-identity, E121 B10
        import tempfile
        from .errors import Refused
        from .exchange import ClientTransport, Exchange
        from .procedures import ITEM, PROJECT_INPUT, candidates
        exact, found = PROJECT_INPUT.match(text or ''), ITEM.match(text or '')
        if not (exact or found): raise Refused('Name a result as ITEM, ITEM@N or @ASSET:REVISION, such as "Residuals DCC@2".')
        transport = ClientTransport(self)
        inventory = list(transport.inventory())
        with tempfile.TemporaryDirectory() as scratch:
            held = Exchange(transport, scratch)
            if exact:  # the plain "no item" sentence for a pair you cannot see, so it never says whether the pair exists
                asset, revision = exact.groups()
                item = next((i for i in inventory if i.get('asset_id') == asset), None)
                if item is None or revision not in (item.get('revision'), *(v.get('revision') for v in held._history(item) or [])):
                    raise Refused('This project has no item named "%s".' % text)
                return asset, revision
            name, number = found.group(1), int(found.group(2)) if found.group(2) else None
            matches = [i for i in inventory if i.get('name') == name]
            if not matches: raise Refused('This project has no item named "%s".' % name)
            if len(matches) > 1: raise Refused('More than one item is named "%s": %s. Name one as @ASSET:REVISION.' % (name, candidates(held, matches)))
            item, revision = matches[0], matches[0].get('revision')
            if number is not None:
                revision = next((v.get('revision') for v in held._history(item) or [] if v.get('number') == number), None)
                if revision is None: raise Refused('"%s" has no version %d.' % (name, number))
        return item['asset_id'], revision
