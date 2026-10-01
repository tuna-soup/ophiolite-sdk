import json
from pathlib import Path
import pytest
from ophiolite.models import generated
ROOT=Path(__file__).resolve().parents[1]/'ophiolite/contracts'
INDEX=json.loads((ROOT/'registry.json').read_text())
SCHEMAS={r['id']:json.loads((ROOT/r['path']).read_text()) for r in INDEX['schemas']}
RENAMES={'Asset':'ScientificAsset','Curve':'ApplicationCurve'}
FIXTURES=[r for r in INDEX['documents'] if r['kind']=='fixture' and r.get('schema')]

@pytest.mark.parametrize('row',FIXTURES,ids=lambda row:row['path'])
def test_every_declared_registry_fixture(row):
    title=SCHEMAS[row['schema']]['title'];model=getattr(generated,RENAMES.get(title,title))
    model.model_validate(json.loads((ROOT/row['path']).read_text()))


def test_registry_and_profiles():
    generated.ContractsRegistry.model_validate(INDEX)
    for row in INDEX['profiles']:generated.ContractProfile.model_validate(json.loads((ROOT/row['path']).read_text()))


def test_a_version_reads_with_and_without_the_access_key_that_made_it():
    """B1(a): a version made through a project access key names it; an older record, or one made otherwise, has none."""
    via = {'kind': 'access-key', 'key_id': 'k1', 'label': '<b>Surface publisher app</b>'}
    made = generated.Version.model_validate({'at': '2026-10-01T08:00:00Z', 'by': {'id': 'alice'}, 'via': via})
    assert made.via.label == '<b>Surface publisher app</b>' and made.via.key_id == 'k1'  # text, as written
    assert generated.Version.model_validate({'at': '2026-09-01T08:00:00Z', 'by': {'id': 'alice'}}).via is None
    with pytest.raises(Exception): generated.Via.model_validate({**via, 'label': 'x' * 81})


def test_a_result_s_versions_name_the_key_each_was_published_through():
    from ophiolite.models.api import History
    h = History.model_validate({'asset_id': 'd1', 'head_revision': 'r2', 'count': 2, 'revisions': [
        {'number': 1, 'revision': 'r1', 'by': 'alice', 'stage': 'draft', 'via': {'kind': 'access-key', 'key_id': 'k1', 'label': 'Surface publisher app'}},
        {'number': 2, 'revision': 'r2', 'by': 'alice', 'stage': 'draft', 'via': None}]})
    assert h.revisions[0].via.label == 'Surface publisher app' and h.revisions[1].via is None
