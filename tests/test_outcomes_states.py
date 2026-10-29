"""E120 s1, offline: what the SDK sends for a result's outcome states, how it names a result version by ITEM[@N] or
@ASSET:REVISION (adhoc-e121-identity), and the words it prints. Literals by hand; the HTTP journeys are the Platform's
test_outcome_states.py and test_result_identity_e2e.py."""
import pytest

from ophiolite import outcomes
from ophiolite.errors import Refused

ANSWER = {'asset_id': 'r1', 'revision': 'b' * 64, 'outcomes': [
    {'outcome_id': 'o1', 'label': 'Tops within 5 m', 'version': 2, 'state': 'accepted', 'reason': None, 'check_id': 'c1',
     'line': 'Accepted on 23 October 2026 under Tops within 5 m version 2', 'earlier_publications': ['An earlier publication: Not checked: Not evaluated'],
     'earlier_versions': ['Rejected under version 1; published before version 2']},
    {'outcome_id': 'o2', 'label': 'Tops within 1 m', 'version': 1, 'state': 'withdrawn', 'reason': 'withdrawn', 'check_id': None,
     'line': 'Outcome withdrawn on 22 October 2026', 'earlier_publications': [], 'earlier_versions': []}]}


class Fake(outcomes.OutcomeClient):
    def __init__(self):
        self.sent = []

    def _post(self, area, operation, body, retry=False):
        self.sent.append((area, operation, body, retry))
        return ANSWER


def test_states_and_evaluate_send_the_exact_version_and_may_be_retried():
    fake = Fake()
    fake.outcome_states('r1', 'b' * 64)
    fake.outcome_evaluate('r1', 'b' * 64)
    assert fake.sent == [('outcomes', 'states', {'asset_id': 'r1', 'revision': 'b' * 64}, True), ('outcomes', 'evaluate', {'asset_id': 'r1', 'revision': 'b' * 64}, True)]


def test_the_states_read_as_one_line_per_outcome_with_the_earlier_ones_below():
    """Mutation: leave out the earlier versions -> the third line is missing -> red."""
    assert outcomes.state_lines(ANSWER) == ('Tops within 5 m: Accepted on 23 October 2026 under Tops within 5 m version 2\n'
                                            '  An earlier publication: Not checked: Not evaluated\n'
                                            '  Rejected under version 1; published before version 2\n'
                                            'Tops within 1 m: Outcome withdrawn on 22 October 2026')
    assert outcomes.state_lines({'outcomes': []}) == 'No outcome is declared over this kind of result.'


class Inventory(outcomes.OutcomeClient):
    url, project = 'http://gateway', 'p'

    def sync(self):
        items = [{'asset_id': 'r1', 'name': 'Residuals DCC', 'revision': 'c' * 64}, {'asset_id': 'r2', 'name': 'Twice', 'revision': 'd' * 64},
                 {'asset_id': 'r3', 'name': 'Twice', 'revision': 'e' * 64}]
        return type('Sync', (), {'inventory': lambda self: items})()


@pytest.fixture
def history(monkeypatch):
    from ophiolite import exchange
    versions = {'r1': [{'number': 1, 'revision': 'a' * 64}, {'number': 2, 'revision': 'c' * 64}], 'r2': [{'number': 1, 'revision': 'd' * 64}],
                'r3': [{'number': 1, 'revision': 'f' * 64}, {'number': 2, 'revision': 'e' * 64}]}
    monkeypatch.setattr(exchange.ClientTransport, 'history', lambda self, item: versions[item['asset_id']], raising=False)


def test_a_result_is_named_by_its_item_and_version_number(history):
    """Mutation: ignore @N -> the head ('c'...) instead of version 1 -> red."""
    client = Inventory()
    assert client.result_version('Residuals DCC@1') == ('r1', 'a' * 64)
    assert client.result_version('Residuals DCC') == ('r1', 'c' * 64)


def test_a_result_is_named_exactly_by_asset_and_revision_at_its_head_or_an_earlier_version(history):
    """adhoc-e121-identity (E121 B10). Mutation: resolve the exact form by its item's name -> "Twice" is ambiguous -> red."""
    client = Inventory()
    assert client.result_version('@r3:' + 'e' * 64) == ('r3', 'e' * 64)
    assert client.result_version('@r3:' + 'f' * 64) == ('r3', 'f' * 64)  # an earlier version, from its history
    assert client.result_version('@r2:' + 'd' * 64) == ('r2', 'd' * 64)


TWICE = ('More than one item is named "Twice": Twice version 1 (@r2:%s); Twice version 2 (@r3:%s). Name one as @ASSET:REVISION.'
         % ('d' * 64, 'e' * 64))
FORMAT = 'Name a result as ITEM, ITEM@N or @ASSET:REVISION, such as "Residuals DCC@2".'


@pytest.mark.parametrize('text,sentence', [('Nothing', 'This project has no item named "Nothing".'), ('Twice', TWICE),
                                           ('Residuals DCC@3', '"Residuals DCC" has no version 3.'), ('@1', FORMAT), ('@r1', FORMAT), ('@r1:', FORMAT),
                                           ('@r9:' + 'c' * 64, 'This project has no item named "@r9:%s".' % ('c' * 64)),
                                           ('@r1:' + 'e' * 64, 'This project has no item named "@r1:%s".' % ('e' * 64))])
def test_a_name_that_is_not_one_version_is_refused_with_its_sentence(history, text, sentence):
    with pytest.raises(Refused) as refused: Inventory().result_version(text)
    assert str(refused.value) == sentence
