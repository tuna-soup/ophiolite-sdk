"""E110 slice 1 (7-7): `checks list` and `checks compare` name picks and stations and say what has no partner; a rule this
SDK does not know counts "values", never depths. Literals are written out; mutations, each red here: drop a PLACES row
(tops read "depths"), drop the unknown-rule fallback (it reads "depths"), drop the outside sentence."""
from ophiolite import checks

AT = 1791849600  # 13 October 2026
METRE = {'kind': 'absolute', 'value': 1.0, 'unit': 'm'}
TOPS = {'witness': 'personal', 'at': AT, 'outcome': 'differed', 'rules_id': 'tops-compare/1', 'tolerance': METRE,
        'differences': {'count': 3, 'total': 6, 'largest': -2.0, 'missing': 1, 'extra': 1, 'first': []}}
SURVEY = {'witness': 'personal', 'at': AT, 'outcome': 'differed', 'rules_id': 'trajectory-compare/1', 'tolerance': {'kind': 'absolute', 'value': 5.0, 'unit': 'm'},
          'differences': {'count': 6, 'total': 8, 'largest': 51.00077574219124, 'outside': 1, 'first': []}}


def test_a_tops_comparison_names_picks_and_the_unpaired():
    assert checks.record_lines(TOPS) == ['Compared with a file on 13 October 2026: differed.', 'Largest difference -2 metres, at 3 of 6 picks.',
                                         '1 pick only in the reference.', '1 pick only in the result.', 'Allowed: within 1 metres.', 'Saved on this result only.']
    assert checks.compare_lines(TOPS)[:3] == ['Differs by at most -2 metres, at 3 of 6 picks.', '1 pick only in the reference.', '1 pick only in the result.']


def test_a_survey_comparison_names_stations_and_those_beyond_the_reference():
    assert checks.record_lines(SURVEY)[1:3] == ['Largest distance 51.00077574 metres, at 6 of 8 stations.', '1 station beyond the reference survey.']
    only_missing = {**SURVEY, 'differences': {'count': 2, 'total': 2, 'largest': None, 'outside': 2, 'first': []}}
    assert checks.compare_lines(only_missing)[:2] == ['Different at 2 of 2 stations.', '2 stations beyond the reference survey.']


def test_gates_read_as_sentences_and_an_unknown_rule_counts_values():
    assert checks.compare_lines({'outcome': 'not_compared', 'rules_id': 'trajectory-compare/1', 'reason': 'grid_unknown'})[0] == \
        'Not compared: grid north is compared only on one known projected grid.'
    assert checks.compare_lines({'outcome': 'not_compared', 'rules_id': 'tops-compare/1', 'reason': 'unreadable'})[0] == 'Not compared: the file could not be read as a tops file.'
    assert checks.record_lines({**TOPS, 'outcome': 'not_compared', 'reason': 'wellbore_mismatch'})[1] == 'The file names another well.'
    future = {**TOPS, 'rules_id': 'horizon-compare/1', 'differences': {'count': 2, 'total': 9, 'largest': 0.5, 'first': []}}
    assert checks.record_lines(future)[1] == 'Largest difference 0.5 metres, at 2 of 9 values.'
    assert checks.compare_lines({**TOPS, 'rules_id': None, 'differences': {'count': 1, 'total': 3, 'largest': 0.5}})[0] == 'Differs by at most 0.5 metres, at 1 of 3 depths.'
