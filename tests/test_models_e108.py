"""E108 slice 0: the SDK reads the upload receipt's sha256 and a descriptor's acquisition.sourced_by. Each test names the
mutation it catches."""
import json
from pathlib import Path

import jsonschema

from ophiolite.models import generated
from ophiolite.models.api import UploadResult

CONTRACTS = Path(__file__).resolve().parents[1] / 'ophiolite/contracts'
RECEIPT = {'asset_id': 'a1', 'revision': 'd' * 64, 'name': 'Survey', 'can_share': True, 'acquisition': {}, 'permitted_audience': ['alice'],
           'recipients': [], 'reuse_recipients': []}


def test_a_receipt_keeps_its_sha256_beside_a_different_revision():
    """Mutation: UploadResult without `sha256` (extra fields are ignored): the field reads None (red); or the model
    replaces it with the revision: red. S2's receipt check refuses the contradictory pair; parsing keeps both."""
    parsed = UploadResult.model_validate({**RECEIPT, 'sha256': 'e' * 64})
    assert (parsed.revision, parsed.sha256) == ('d' * 64, 'e' * 64)
    assert parsed.model_dump()['sha256'] == 'e' * 64


def test_a_receipt_from_a_server_before_e108_has_no_sha256():
    """Mutation: `sha256` required: an older server's receipt no longer parses (red)."""
    assert UploadResult.model_validate(RECEIPT).sha256 is None


def test_the_shared_descriptor_with_sourced_by_validates_in_the_sdk():
    """Mutation: the snapshot's schema or the generated model without SourcedBy: the fixture is refused (red)."""
    descriptor = json.loads((CONTRACTS / 'assets/v1/fixtures/sourced-by.json').read_text())
    parsed = generated.ScientificAsset.model_validate(descriptor)
    assert parsed.acquisition.sourced_by.model_dump() == {'digest': '7ac382330ee3f77a80d1f6db3f95155f61561703eb4667fc7dd77f7d8feecf6f', 'label': 'Survey share',
                                                          'version_label': '2', 'version': 2, 'rules_version': '1.0.0', 'runner': 'alice',
                                                          'system': 'Team survey share', 'role': 'well_headers'}
    schema = json.loads((CONTRACTS / 'assets/v1/schema.json').read_text())
    assert schema['x-ophiolite']['version'] == '1.32.0'  # E123 S1f-a 1.32.0; S0 1.25.0; S1 1.26.0 (ImportOrigin.sourced_by); E125 s3a 1.27.0; E119a 1.28.0; E119b 1.29.0; E119b s1 1.30.0 (Asset.residual_validity); E127 s0 1.31.0 (Acquisition.listed_in)
    jsonschema.Draft202012Validator(schema).validate(descriptor)
