"""adhoc-d17 (D-17 6-8, 6-9): the residual limits at their boundaries, each its own test.

6-8: a residual result has 1 to 10 000 rows (Connectors `well_residual.MAX_ROWS`). A run needs one row per occurrence of
the chosen formation in each member's tops (`residuals.required`), and one `no-top` row for a member with none (S4-D5:
occurrences, never CSV rows or survey stations). `prepare` refuses a selection that needs more before anything is
downloaded or computed, with Connectors' row-count sentence.

6-9: `writers.well_residual` writes a result of exactly 8 MiB (1 MiB before D-36 (a), adhoc-d36a) and refuses one byte more with Connectors' too-large
sentence (the Gateway half of the parity is `project_gateway/tests/test_residual_boundaries.py`)."""
import json

import pytest

from ophiolite import residuals, writers
from ophiolite.errors import Refused, ValidationFailed
from test_reference_residual import FakeProject, bore, member
from test_residuals import SURFACE, accepted, refused
from test_writers import read_back

LIMITS = 'A residual result has 1 to 10 000 rows and is at most 8 MiB'  # D-36 (a): Connectors well_residual.LIMITS
ROW_COUNT = LIMITS + '; this one has 10 001 rows.'  # at binding: the rows the run needs, nothing written
MIB = 1024 * 1024


def needing(dcc, others=0, without=1):
    """Member 1 with DCC tops (plus OTHERS tops of another formation), then WITHOUT members linked to no tops: the run
    needs DCC + WITHOUT rows."""
    client = FakeProject()
    client.add_grid()
    tops = [{'name': 'DCC', 'md': 1000.0 + i / 100} for i in range(dcc)] + [{'name': 'NSB', 'md': 900.0} for _ in range(others)]
    members = [member(1, client.add_survey(1))]
    client.link(bore(1), client.add_tops(1, tops))
    members += [member(i, client.add_survey(i)) for i in range(2, 2 + without)]
    return client, members


def test_a_run_needing_10000_rows_binds():
    """Mutation: the limit 9 999 -> refused -> red."""
    client, members = needing(9_999)
    assert len(accepted(client, members).inputs['tops']) == 1


def test_a_run_needing_10001_rows_is_refused_before_anything_is_downloaded():
    """Mutation: the limit 10 001 (or no limit, as on main before adhoc-d17) -> bound and downloaded -> red."""
    client, members = needing(10_000)
    assert refused(client, members) == ROW_COUNT
    selection = client.add_set(members)
    with pytest.raises(Refused) as caught:
        residuals.prepare(client, selection, SURFACE, 'DCC')
    assert caught.value.details == {'reason': 'residuals:row-count'}


@pytest.mark.parametrize('json_wanted', [False, True])
def test_the_command_prints_the_row_count_sentence_and_exits_1(tmp_path, monkeypatch, capsys, json_wanted):
    """`ophiolite residuals run` on a selection needing 10 001 rows: Connectors' sentence on stderr (or the --json error
    on stdout), exit 1, nothing run. The handler runs against FakeProject in place of the configured client."""
    from ophiolite import cli
    client, members = needing(10_000)
    selection = client.add_set(members)
    argv = ['residuals', 'run', 'residual-at-wells', '--selection', '@%s:%s' % (selection['asset_id'], selection['revision']), '--surface',
            '@%s:%s' % (SURFACE['asset_id'], SURFACE['revision']), '--formation', 'DCC', '--output', str(tmp_path / 'out'), '--yes'] + (['--json'] if json_wanted else [])
    monkeypatch.setattr(cli, 'main', lambda given: cli._residuals(cli.parser().parse_args(given), client))
    with pytest.raises(SystemExit) as stopped:
        cli.entrypoint(argv)
    out, err = capsys.readouterr()
    assert stopped.value.code == 1 and not (tmp_path / 'out').exists()
    if json_wanted: assert json.loads(out)['error']['message'] == ROW_COUNT and err == ''
    else: assert (out, err) == ('', ROW_COUNT + '\n')


def test_the_rows_are_the_occurrences_of_the_formation_and_one_per_member_without_one():
    """S4-D5: tops of another formation need no row; a member with no top of the formation needs one. 9 998 DCC and
    500 NSB tops, two members without: 10 000 rows, bound; a third member without: 10 001, refused."""
    client, members = needing(9_998, others=500, without=2)
    accepted(client, members)
    client, members = needing(9_998, others=500, without=3)
    assert refused(client, members) == ROW_COUNT


def test_the_rows_needed_are_the_rows_compute_makes():
    """The count `prepare` refuses on (`needed`) is the length of the document `compute` makes from the same tops: three
    DCC tops (two at one depth), an NSB top, a member whose tops name no DCC and a member with no tops. Members without a
    trajectory, so every row is a reason and no geometry runs."""
    ref = {'asset_id': 'tops-1', 'revision': 'r1'}
    given = {bore(1): (ref, [{'name': 'DCC', 'md': 1200.0}, {'name': 'NSB', 'md': 1100.0}, {'name': 'DCC', 'md': 1190.0}, {'name': 'DCC', 'md': 1200.0}]),
             bore(2): (ref, [{'name': 'NSB', 'md': 1100.0}])}
    members = [{'well': 'well-1', 'wellbore': bore(i), 'trajectory': None, 'frame': None} for i in (1, 2, 3)]
    document = residuals.compute(members, given, {}, None, SURFACE, 'DCC')
    assert residuals.needed(members, {b: tops for b, (_, tops) in given.items()}, 'DCC') == len(document['rows']) == 5


def residual(size, count):
    """A result of COUNT `no-top` rows, each its own wellbore, whose UTF-8 JSON as `writers.well_residual` writes it is
    SIZE bytes: crossings fill it (at most 64 a row, md from 1001 m), the last bytes the digits of their low ends (inside
    the 0.01 m bracket). Every row is one Connectors' reader accepts (Codex round 1: padding a wellbore is not)."""
    rows = [{'wellbore': 'wellbore-%032x' % i, 'occurrence': 0, 'top': None, 'trajectory': None, 'crossings': [], 'used': None,
             'residual': None, 'unit': 'm', 'reason': 'no-top', 'between': None} for i in range(count)]
    document = {'schema': 'ophiolite.well-residual/1', 'correspondence': {'formation': 'DCC'}, 'display_unit': 'm', 'surface': dict(SURFACE), 'rows': rows}
    written = lambda: len((json.dumps(document, indent=2, allow_nan=False, ensure_ascii=False) + '\n').encode('utf-8'))  # noqa: E731
    crossing = lambda j: {'md': 1001.0 + j, 'low': 1001.0 + j, 'high': 1001.0 + j}  # noqa: E731
    for row in rows: row['crossings'] = [crossing(0)]
    base = written()
    rows[0]['crossings'].append(crossing(1))
    each = written() - base
    extra, rest = divmod(size - base, each)
    rows[0]['crossings'].pop()
    for row in rows:
        more = min(63, extra); extra -= more
        row['crossings'] += [crossing(j) for j in range(1, more + 1)]
    for c in (c for row in rows for c in row['crossings']):
        if not rest: break
        digits = min(9, rest); rest -= digits  # 1001.0 -> 1000.99 (+1 byte) ... 1000.9999999999 (+9)
        c['low'] = float('%d.%s' % (c['md'] - 1, '9' * (digits + 1)))
    assert written() == size
    return document


def test_a_result_of_exactly_8_mib_is_written():
    """adhoc-d36a (D-36 (a)): 3 000 rows, within the row limit, and Connectors' reader accepts the written bytes.
    Mutation: the bound 8 MiB - 1 -> refused -> red."""
    out = writers.well_residual(residual(8 * MIB, count=3_000))
    assert len(out.bytes) == 8 * MIB
    assert read_back(out)[0]['count'] == 3_000


def test_a_result_of_8_mib_and_one_byte_is_refused():
    """D-36: the sentence names both limits and this result's rows and exact bytes. Mutations: the bound 8 MiB + 1 ->
    written -> red; the 1 MiB sentence -> red."""
    document = residual(8 * MIB + 1, count=3_000)
    with pytest.raises(ValidationFailed) as caught:
        writers.well_residual(document)
    assert caught.value.violations == (LIMITS + '; this one has 3 000 rows and 8 388 609 bytes.',)


def test_10000_typical_rows_are_written_under_the_cap():
    """D-36's case for (a), a size only: the SDK's own contract fixture's three rows (computed, grazing, no-top) cycled
    to 10 000 (each wellbore its own) are about 5.3 MB, as written (the E119b fixture's seven rows, outside the SDK's
    tree, gave 6.1 MB in adhoc-d36). A valid result of 10 000 rows, published and read back, is the Gateway's
    `test_a_valid_result_of_10000_rows_is_published_valid_and_read_back`."""
    from pathlib import Path
    fixture = json.loads((Path(writers.__file__).parent / 'contracts/assets/v1/fixtures/well-residual.original').read_text())
    rows = [dict(fixture['rows'][i % 3], wellbore='wellbore-%032x' % i) for i in range(10_000)]
    out = writers.well_residual(dict(fixture, rows=rows))
    assert 5_000_000 < len(out.bytes) < 8 * MIB


@pytest.mark.parametrize('rows, size, words', [
    (None, None, ''), (10_001, None, '; this one has 10 001 rows'), (None, 1_048_577, '; this one has 1 048 577 bytes'),
    (0, 312, '; this one has 0 rows and 312 bytes'), (1, 1, '; this one has 1 row and 1 byte')])
def test_the_limits_sentence_states_what_is_known(rows, size, words):
    assert residuals.limits(rows, size) == LIMITS + words + '.'
