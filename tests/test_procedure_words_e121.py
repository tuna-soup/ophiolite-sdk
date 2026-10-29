"""E121 O5 (rehearsal seed log): a system's configuration holds its settings as text; a number there (a port written
5432, not "5432") was refused with the sentence for a missing or unreadable file. The refusal now names the keys whose
values are not text and the way through, never a value."""
import json

from ophiolite import procedures
from test_procedures_run import FIXTURES, SOURCE, refused

BASE = 'Not run: Field database needs its configuration file, holding exactly its settings as text'


def source(tmp_path, config):
    folder = tmp_path / 'source'; folder.mkdir()
    (folder / 'procedure.json').write_text((FIXTURES / 'valid/source.json').read_text()); (folder / 'procedure.py').write_text(SOURCE)
    path = tmp_path / 'db.json'
    path.write_text(config if isinstance(config, str) else json.dumps(config))
    return lambda: procedures.run(folder, tmp_path / 'out', systems={'database': str(path)})


def test_a_value_that_is_not_text_is_named_by_its_key_never_its_value(tmp_path):
    """Mutation: the old check (any non-text value -> the plain sentence) -> red."""
    error = refused('system-config', source(tmp_path, {'host': 'Field', 'user': 'anna', 'password': 908172}))
    assert str(error) == BASE + '; password is not text: put its value in quotes.'
    assert error.details == {'expected_keys': ['host', 'user', 'password'], 'not_text': ['password']} and '908172' not in str(error) + json.dumps(error.details)


def test_two_values_that_are_not_text_are_both_named(tmp_path):
    error = refused('system-config', source(tmp_path, {'host': 5432, 'user': 'anna', 'password': None}))
    assert str(error) == BASE + '; host and password are not text: put their values in quotes.'


def test_a_file_with_other_keys_or_no_json_keeps_the_plain_sentence(tmp_path):
    (tmp_path / 'a').mkdir(); (tmp_path / 'b').mkdir()
    assert str(refused('system-config', source(tmp_path / 'a', {'host': 'Field', 'user': 'anna'}))) == BASE + '.'
    assert str(refused('system-config', source(tmp_path / 'b', '{not json'))) == BASE + '.'
