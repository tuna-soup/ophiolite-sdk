"""adhoc-e121-claims (E121 O6), offline: a send procedure that raises says the first line of its error, with every
value of the system's configuration replaced by "…", and names the `--system` slot to check. The line is kept in the
attempt on this computer for the sentence; the report carries only the state, as before.

Mutations (recorded in docs/program-2026-09-25/adhoc-e121-claims-VALIDATION.md): `_raised` without its replacement ->
the folder is told -> red; `_raised` keeping the whole message -> the second line is told -> red; the `raised` branch of
`delivery_words` removed -> the old "did not say" sentence -> red."""
import json
from pathlib import Path

from ophiolite import procedures
from test_deliver import CODE, DESTINATION, attempt_of, count, deliver, folder_of, manifest, world  # noqa: F401 (fixture)

RAISES = CODE.replace("raise RuntimeError('The connection was lost.')",
                      "raise RuntimeError('cannot open %s: permission denied.\\n  at line 2' % delivery.system.config['folder'])")


def raised(message, config, slot='db'):
    return procedures._raised({'state': 'unknown', 'said': 'raised', 'type': 'OperationalError', 'message': message}, {'slot': slot}, config)


def test_the_first_line_is_told_with_every_configuration_value_replaced():
    config = {'host': 'db.internal.example', 'port': 5432, 'database': 'team', 'login': {'user': 'team_writer', 'roles': ['ro', 'team_ops']},
              'ssl': True, 'note': None}
    line = raised('\n  connection to db.internal.example:5432 as team_writer (team, team_ops, ro) failed.\nDETAIL: db.internal.example', config)
    assert line == {'line': 'connection to …:… as … (…, …, ro) failed', 'slot': 'db'}  # longest first; "ro" is too short to replace


def test_a_line_is_cut_at_200_characters_and_an_empty_message_says_its_type():
    assert raised('x' * 300, {})['line'] == 'x' * 200
    assert raised('\n \n', {}, slot=None) == {'line': 'OperationalError', 'slot': None}


def test_any_other_answer_has_no_raised_line():
    assert procedures._raised({'state': 'unknown', 'said': 'stopped', 'exit_status': 9}, {'slot': 'db'}, {}) is None
    assert procedures._raised(None, None, None) is None


def test_the_sentence_names_the_line_and_the_system_to_check():
    attempt = {'destination': 'Team database', 'procedure': {'label': 'Residuals to the team database'}, 'reported': True,
               'result': {'state': 'unknown', 'items': 0, 'raised': {'line': 'fe_sendauth: no password supplied', 'slot': 'db'}}}
    said = 'Outcome unknown for Team database by Residuals to the team database on this computer. The procedure stopped with an error: fe_sendauth: no password supplied.'
    assert procedures.delivery_words(attempt) == said + ' Check the system configuration given with --system db, then run the same command to record what happened. Recorded in the project.'
    attempt['result']['raised']['slot'] = None
    assert procedures.delivery_words(attempt) == said + ' Run the same command to record what happened. Recorded in the project.'
    assert procedures.delivery_words(attempt, again=True).endswith('It was not sent again. Recorded in the project.')  # a later run says what it did


def test_a_raising_procedure_keeps_its_line_here_and_reports_only_the_state(world, tmp_path):
    w = world
    w.register(folder_of(tmp_path / 'raising', manifest(name='team/raising'), code=RAISES))
    answer = deliver(w, settings=['mode=raise'], name='team/raising')
    assert answer['state'] == 'unknown' and answer['reported'] and count(w) == 1
    assert answer['sentence'] == (f'Outcome unknown for {DESTINATION} by Tops to team folder on this computer. The procedure stopped with an error: '
                                  'cannot open …: permission denied. Check the system configuration given with --system dest, then run the same '
                                  'command to record what happened. Recorded in the project.')
    assert attempt_of(answer)['result']['raised'] == {'line': 'cannot open …: permission denied', 'slot': 'dest'}
    assert w.posts[0]['delivery'] == {'delivery_id': answer['delivery_id'], 'state': 'unknown', 'items': 0}
    sent = json.dumps(w.posts) + json.dumps(w.deliveries.events, default=str)
    assert str(w.dest) not in sent and 'permission denied' not in sent and 'raised' not in sent
    assert str(w.dest) in (Path(answer['folder']) / 'log.txt').read_text()  # what the procedure said stays in the log here (D3)
