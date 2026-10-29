"""E120: outcomes — what a project accepts for a kind of result, by a built-in rule and its settings, and where an
accepted result is delivered. A project administrator declares, revises, enables, disables and withdraws them; every
member lists and reads them. Each change is a new version on the server that is never altered.

A declaration is `ophiolite.outcome/1` (`ophiolite/contracts/outcomes/v1/`); the server checks it and refuses it with
one reason (`error.details['reason']`). From slice 1 the server evaluates every enabled outcome over a residual result
after it is published, with the declarer's reading rights, and keeps an acceptance record (`ophiolite.outcome-check/1`);
`outcome_states` reads a result version's states as sentences ("Accepted on ... under Tops within 5 m version 1").
From slice 3 `ophiolite deliver NAME --as OUTCOME` (`Client.deliver(..., as_=...)`) asks the project's gate first: the
delivery runs only when the version is accepted under the outcome's current version and goes to its declared
destination; every claim, claimed or refused, is kept on the server (`ophiolite.outcome-claim/1`, `outcome_claims`).
"""
import uuid

KIND = 'well-residual/1'
RULE = 'well-residual-within/1'
INPUTS = ['deviation-csv/1', 'esri-ascii-grid/1', 'well-set/1', 'well-tops-csv/1']  # what a residual result is made from


def residual_declaration(label, tolerance, unit, procedure, destination, not_computed='allowed'):
    """The declaration of an outcome over residual results: every computed residual within `tolerance` `unit`."""
    return {'schema': 'ophiolite.outcome/1', 'label': label, 'kind': KIND,
            'rule': {'name': RULE, 'settings': {'tolerance': {'value': tolerance, 'unit': unit}, 'not_computed': not_computed}},
            'inputs': list(INPUTS), 'destination': {'procedure': procedure, 'label': destination}}


def state_lines(answer):
    """A result version's outcome states in words: one line per outcome, its earlier publications and versions below."""
    lines = []
    for o in answer['outcomes']:
        lines.append('%s: %s' % (o['label'], o['line']))
        lines += ['  ' + more for more in o['earlier_publications'] + o['earlier_versions']]
    return '\n'.join(lines) or 'No outcome is declared over this kind of result.'


def summary_line(o):
    """One outcome in words: its name, state and version, what it accepts and where it delivers."""
    return '"%s" (%s, version %d): %s, %s; delivered to %s.' % (o['label'], o['state'], o['version'], o['words']['kind'], o['words']['rule'], o['words']['destination'])


class OutcomeClient:
    """Mixed into `Client` (uses its `_post`). Each write sends a new command id unless one is given; the same id with
    the same body answers the stored result."""

    def outcome_list(self):
        """The project's outcomes in the order they were first declared, withdrawn ones included."""
        return self._post('outcomes', 'list', {}, retry=True)['outcomes']

    def outcome_get(self, outcome_id):
        """One outcome with every version and every action on it."""
        return self._post('outcomes', 'get', {'outcome_id': outcome_id}, retry=True)

    def outcome_named(self, label):
        """The outcome that is not withdrawn and carries this name (names are compared without case)."""
        from .errors import Refused
        found = [o for o in self.outcome_list() if o['state'] != 'withdrawn' and o['label'].casefold() == label.casefold()]
        if not found: raise Refused('This project has no outcome named "%s".' % label)
        return found[0]

    def _outcome_write(self, operation, body, command_id):
        return self._post('outcomes', operation, {'command_id': command_id or '%s-%s' % (operation, uuid.uuid4().hex), **body}, retry=True)

    def outcome_declare(self, declaration, *, command_id=None):
        """Declare an outcome (project administrators); it is enabled at version 1."""
        return self._outcome_write('declare', {'declaration': declaration}, command_id)

    def outcome_revise(self, outcome_id, declaration, *, command_id=None):
        """Its next version, when anything differs (refused `unchanged` otherwise); earlier versions stay as they were."""
        return self._outcome_write('revise', {'outcome_id': outcome_id, 'declaration': declaration}, command_id)

    def outcome_enable(self, outcome_id, *, command_id=None):
        return self._outcome_write('enable', {'outcome_id': outcome_id}, command_id)

    def outcome_disable(self, outcome_id, *, command_id=None):
        return self._outcome_write('disable', {'outcome_id': outcome_id}, command_id)

    def outcome_withdraw(self, outcome_id, *, command_id=None):
        """Withdraw for good; the name is free again."""
        return self._outcome_write('withdraw', {'outcome_id': outcome_id}, command_id)

    # --- E120 s1: the states of a result version ---------------------------------------------------------------------

    def outcome_states(self, asset_id, revision):
        """{asset_id, revision, outcomes: [{outcome_id, label, version, state, reason, check_id, line,
        earlier_publications, earlier_versions}]} for a result version you can read (refused `result` otherwise)."""
        return self._post('outcomes', 'states', {'asset_id': asset_id, 'revision': revision}, retry=True)

    def outcome_evaluate(self, asset_id, revision):
        """Evaluate again where no record exists yet (a missed evaluation), then the states; a record is never changed."""
        return self._post('outcomes', 'evaluate', {'asset_id': asset_id, 'revision': revision}, retry=True)

    # --- E120 s3: the claims "Deliver as" made -------------------------------------------------------------------------

    def outcome_claims(self):
        """The project's "Deliver as" claims you may see now, oldest first: {claim_id, state, reason, sentence,
        delivery_id, outcome, result, check, destination, by, delivery}. `state` is the gate's (claimed or refused) and
        never changes; `delivery` {state, line} is what became of a claimed claim's delivery, as the result's story
        tells it (claimed, confirmed, not-sent, unknown or mismatch; adhoc-e121-claims)."""
        return self._post('outcomes', 'claims', {}, retry=True)['claims']

    def result_version(self, text):
        """(asset_id, revision) of `ITEM[@N]`: the project item by its name and its version number (default its latest),
        as `procedures again --item` names one; or of `@ASSET:REVISION`, exactly that version when it is one you can
        see (adhoc-e121-identity, E121 B10)."""
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
