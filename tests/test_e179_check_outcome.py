"""E179 s0 C1: the SDK reads the outcome form of a `check` (procedure rules 1.5.0) with its packaged contract copy and
never runs it on this computer: only Ophiolite runs an outcome's check, when the outcome is evaluated (slice 1)."""
import pytest

from ophiolite import procedures
from test_procedures import EXPECTED, FIXTURES, folder_with


def outcome_folder(tmp_path):
    raw = (FIXTURES / 'valid/check-outcome.json').read_bytes()
    return folder_with(tmp_path, 'check-outcome', raw, EXPECTED['members']['check-outcome'])


def test_the_outcome_form_validates_through_the_sdk_with_its_words(tmp_path):
    verdict = procedures.validate(outcome_folder(tmp_path))
    assert (verdict['valid'], verdict['rules_version'], verdict['sentence']) == (
        True, '1.6.0', "Valid: Residuals within the team's limit, version 1. It reads Residual result (JSON) and Well tops (CSV) "
                       'and Horizon grid (ESRI ASCII) and makes an answer.')


def test_running_the_outcome_form_locally_is_refused_before_a_destination(tmp_path):
    """Mutation: drop the `check-outcome` refusal in `procedures.run` (the run goes on to bind inputs and is refused
    `missing-input` instead; seen 19 Nov)."""
    with pytest.raises(procedures.NotRun) as error: procedures.run(outcome_folder(tmp_path), tmp_path / 'out')
    assert (error.value.code, str(error.value)) == (
        'check-outcome', 'Not run: this check answers an outcome; Ophiolite runs it when the outcome is evaluated.')
    assert not (tmp_path / 'out').exists()


def test_the_comparison_form_still_runs_past_the_refusal(tmp_path):
    """The comparison form is not refused for its step: without inputs it stops on its first missing slot instead."""
    raw = (FIXTURES / 'valid/check.json').read_bytes()
    folder = folder_with(tmp_path, 'check', raw, EXPECTED['members']['check'])
    with pytest.raises(procedures.NotRun) as error: procedures.run(folder, tmp_path / 'out')
    assert error.value.code != 'check-outcome'
