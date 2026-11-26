"""E192 s2b C3: `client.imports.from_table(target='table', made_for=...)` names the exact versions a kept table was made
for, on preview and start alike; a malformed list is refused before the file is read; a release that does not record
made_for is said in one sentence through Imports as through the client."""
import pytest

from ophiolite.errors import Refused, ValidationFailed
from ophiolite.imports import NOT_CHECKED, Imports
from ophiolite.publish import MADE_FOR_SHAPE, MADE_FOR_UNRECORDED

from test_imports_table import A, Fake

DESIGN = ('synthetic-design', 'd' * 64)
PLAN = ('synthetic-plan', 'e' * 64)
WIRE = [{'asset_id': 'synthetic-design', 'revision': 'd' * 64}, {'asset_id': 'synthetic-plan', 'revision': 'e' * 64}]
STUB = ('This deployment cannot record what this file was made for yet.', {'reason': 'made-for-not-recorded', 'field': 'made_for'})
BEFORE = ('Invalid request fields: made_for', None)
OTHER = ('Invalid request fields: made_for.0.revision', None)


class Refusing(Fake):
    """The tops answers, with the preview refused as the transport raises it (the server's details kept)."""

    def __init__(self, refusal):
        super().__init__('tops'); self.refusal = refusal

    def _answer(self, operation, body):
        if operation != 'preview': return super()._answer(operation, body)
        self.sent.append((operation, body))
        text, details = self.refusal
        raise Refused('generic transport words', status=400, code='INVALID_ARGUMENT', details=details, server_message=text)


@pytest.fixture
def table(tmp_path):
    path = tmp_path / 'costs.csv'; path.write_bytes(b'not read here'); return path


def test_preview_and_start_carry_made_for_only_when_given(table):
    """Mutation: `made_for` left out of `options` (or of `_body`) → the bodies lack it; always written → the plain
    bodies carry `made_for: None` or an empty list."""
    fake = Fake('tops')
    Imports(fake).from_table(table, 'table', made_for=[DESIGN, {'asset_id': 'synthetic-plan', 'revision': 'e' * 64}])
    assert [s[0] for s in fake.sent] == ['read', 'preview', 'start', 'step']
    assert fake.sent[1][1]['made_for'] == WIRE and fake.sent[2][1]['made_for'] == WIRE
    plain = Fake('tops')
    Imports(plain).from_table(table, 'table')
    assert all('made_for' not in body for operation, body in plain.sent if operation in ('preview', 'start'))
    assert plain.sent[1][1] == {'target': 'table', 'input_id': A['tops']['read']['input_id'],
                                'mapping': {'fields': {}, 'declarations': {}, 'schema_digest': A['tops']['read']['schema_digest']}}


@pytest.mark.parametrize('made_for', [[], [DESIGN, DESIGN], [('synthetic-design', 'D' * 64)], [('synthetic-design',)],
                                      [{'asset_id': 'synthetic-design', 'revision': 'd' * 64, 'note': 'x'}], 'synthetic-design',
                                      [DESIGN] * 33])
def test_a_malformed_list_is_refused_before_the_file_is_read(table, made_for):
    """Mutation: the check moved after `self.read` (or only in `_body`) → the read is sent first."""
    fake = Fake('tops')
    with pytest.raises(ValidationFailed) as refused:
        Imports(fake).from_table(table, 'table', made_for=made_for)
    assert fake.sent == [] and MADE_FOR_SHAPE in str(refused.value)


@pytest.mark.parametrize('refusal', [STUB, BEFORE], ids=['stub', 'before-s0'])
def test_a_release_that_does_not_record_made_for_is_said_in_one_sentence(table, refusal):
    """Mutation: `_post` without `made_for_refused` (or `said` without its line) → the generic sentence."""
    with pytest.raises(Refused) as refused:
        Imports(Refusing(refusal)).from_table(table, 'table', made_for=[DESIGN])
    assert (str(refused.value), refused.value.status, refused.value.server_message) == (MADE_FOR_UNRECORDED, 400, refusal[0])


def cli_run(argv, fake):
    from types import SimpleNamespace
    from ophiolite import cli
    return cli._table_import(cli.parser().parse_args(argv), SimpleNamespace(imports=Imports(fake)))


def test_the_command_line_names_made_for_on_preview_and_start(table):
    """Mutation: `made_for=args.made_for` dropped from `_table_import` → the bodies lack it; `table` out of the
    --target choices → a usage error (exit 2)."""
    fake = Fake('tops')
    cli_run(['import', 'table', str(table), '--target', 'table', '--made-for', 'synthetic-design@' + 'd' * 64,
             '--made-for', 'synthetic-plan@' + 'e' * 64], fake)
    assert [s[0] for s in fake.sent] == ['read', 'preview', 'start', 'step']
    assert fake.sent[1][1]['target'] == 'table' and fake.sent[1][1]['made_for'] == WIRE and fake.sent[2][1]['made_for'] == WIRE


def test_the_command_line_refuses_made_for_elsewhere_and_malformed(table, capsys):
    """Mutation: `args.made_for` out of `table_only` → status sends a request; `type=_exact_version` dropped → a bare
    item reaches the SDK instead of a usage error."""
    from ophiolite import cli
    fake = Fake('tops')
    with pytest.raises(Refused, match='Only import table takes .*--made-for'):
        cli_run(['import', 'status', 'i1', '--made-for', 'synthetic-design@' + 'd' * 64], fake)
    assert fake.sent == []
    with pytest.raises(SystemExit) as stopped:
        cli.parser().parse_args(['import', 'table', str(table), '--target', 'table', '--made-for', 'synthetic-design'])
    assert stopped.value.code == 2 and 'give an exact version as ITEM@VERSION' in capsys.readouterr().err


@pytest.mark.parametrize('refusal, made_for', [(OTHER, [DESIGN]), (('Synthetic refusal.', None), [DESIGN]), (STUB, None), (BEFORE, None)],
                         ids=['other-field', 'other-words', 'stub-without', 'before-without'])
def test_every_other_refusal_keeps_its_words(table, refusal, made_for):
    """Mutation: a broad match in `said` (any 400 that names made_for) → these read as the release sentence."""
    with pytest.raises(Refused) as refused:
        Imports(Refusing(refusal)).from_table(table, 'table', made_for=made_for)
    assert str(refused.value) == NOT_CHECKED and refused.value.server_message == refusal[0]
