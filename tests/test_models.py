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
