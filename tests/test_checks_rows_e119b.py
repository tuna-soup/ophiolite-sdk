"""D-9 (taken by E119b slice 3): `ophiolite checks compare` prints one row per differing pick of a residual comparison
(wellbore, surface, pick MD, residual, class), not only the aggregate sentence, and the rows read back.

The route answers are written by hand in the shape the Platform's `checks/compare` stores for C3 t2 at 0.01 m (B2's
residual 2.02 m in the file against 2.0 m in the result; `test_compare_residual.py` asserts the same record through
the route). Mutation: print the aggregate only; these tests go red."""
from ophiolite import checks
from test_cli_checks import AT, Recorded, record, run

B1, B2 = 'wellbore-' + '1' * 32, 'wellbore-' + '2' * 32
OTHER = 'wellbore-' + 'f' * 32


def residual_record(differences, outcome='differed', tolerance=0.01):
    return record('personal', outcome=outcome, at=AT, subject={'kind': 'result', 'asset_id': 'a' * 64, 'revision': 'b' * 64}, fixture=None,
                  reference={'kind': 'reference-file', 'name': 'second.json', 'version': '1', 'digest': 'd' * 64, 'rights': None},
                  rules_id='residual-compare/1', tolerance={'kind': 'absolute', 'value': tolerance, 'unit': 'm'}, request_digest=None,
                  differences=differences, bound='Within %s metres' % tolerance, interpretation=None,
                  sentence='Compared: %d of %d rows differ.' % (differences['count'], differences['total']))


def pair(wellbore, k, md, result, reference, result_reason=None, reference_reason=None):
    return {'wellbore': wellbore, 'occurrence': k, 'md': md, 'result_residual': result, 'reference_residual': reference,
            'result_reason': result_reason, 'reference_reason': reference_reason}


T2 = {'count': 1, 'total': 5, 'largest': 0.01999999999998181, 'missing': 0, 'extra': 0, 'reasons_differ': 0, 'formation': 'DCC',
      'first': [pair(B2, 1, 1302.0, 2.0, 2.019999999999982)]}


def printed(tmp_path, differences, *more):
    (tmp_path / 'second.json').write_bytes(b'{"schema": "ophiolite.well-residual/1"}')
    client = Recorded({'compare': residual_record(differences)})
    text, payload = run(client, 'compare', '--asset', 'a' * 64, '--revision', 'b' * 64, '--file', str(tmp_path / 'second.json'),
                        '--tolerance', '0.01', '--unit', 'm', *more)
    return text.splitlines(), payload


def rows_of(lines):
    """The printed rows read back: each row's five columns, the residual column split into its two sides."""
    at = lines.index(checks.ROWS_HEADING)
    found = []
    for line in lines[at + 1:]:
        if not line.startswith('  wellbore-'): break
        wellbore, surface, md, residuals, kind = line.strip().split(' | ')
        result, reference = residuals.split(' / ')
        found.append({'wellbore': wellbore, 'surface': surface, 'md': md, 'result': result, 'reference': reference, 'class': kind})
    return found


def test_d9_the_t2_case_at_0_01_m_prints_its_one_differing_pick_and_it_reads_back(tmp_path):
    lines, _ = printed(tmp_path, T2)
    assert lines[0] == 'Differs by at most 0.02 metres, at 1 of 5 rows.'
    assert rows_of(lines) == [{'wellbore': B2, 'surface': 'DCC', 'md': '1302 m', 'result': '2 m', 'reference': '2.02 m', 'class': 'residual differs'}]
    assert lines[-2:] == ['Saved on this result only.', 'This is not a check of the method that made this result.']


def test_d9_reasons_and_rows_on_one_side_print_as_their_class(tmp_path):
    d = {'count': 3, 'total': 6, 'largest': None, 'missing': 1, 'extra': 1, 'reasons_differ': 1, 'formation': 'DCC',
         'first': [pair(B1, 2, 1250.5, 3.0, None), pair(B2, 1, 1302.0, 2.0, None, None, 'grazing'), pair(OTHER, 0, None, None, None, None, 'no-top')]}
    lines, _ = printed(tmp_path, d)
    assert [(r['wellbore'], r['md'], r['result'], r['reference'], r['class']) for r in rows_of(lines)] == [
        (B1, '1250.5 m', '3 m', '-', 'only in the result'),
        (B2, '1302 m', '2 m', 'grazing', 'reason differs'),
        (OTHER, '-', '-', 'no-top', 'only in the reference')]


def test_d9_more_differing_pairs_than_listed_say_how_many_more(tmp_path):
    lines, _ = printed(tmp_path, {**T2, 'count': 25, 'total': 30})
    assert len(rows_of(lines)) == 1 and '  and 24 more (--json lists the first 1).' in lines


def test_d9_json_keeps_the_rows_and_a_passed_comparison_prints_no_rows(tmp_path):
    _, payload = printed(tmp_path, T2, '--json')
    assert payload['differences']['first'] == T2['first']
    passed = {**T2, 'count': 0, 'first': []}
    lines = checks.compare_lines(residual_record(passed, outcome='passed'))
    assert checks.ROWS_HEADING not in lines and lines[0] == 'Within 0.01 metres.'


def test_the_residual_gates_read_as_sentences():
    for reason in ('ambiguous_rows', 'correspondence_mismatch', 'inputs_differ'):
        found = residual_record(T2, outcome='not_compared')
        found.update(reason=reason, differences=None)
        del found['sentence']
        assert checks.compare_lines(found)[0] == checks.FILE_REASON[reason] and checks.FILE_REASON[reason].startswith('Not compared: ')
