"""adhoc-d38 (D-38): through the installed SDK and the in-process gateway, a check file one byte over 8 MiB is refused
with the SDK's sentence for publish and for compare, and nothing is stored."""
import os

import pytest

try:
    from project_gateway.tests.test_checks_compare import las  # noqa: F401
    from project_gateway.tests.test_checks_publish import world, rows  # noqa: F401 (fixture)
    from project_gateway.tests.real_credentials import project  # noqa: F401 (fixture)
    from project_gateway.tests.test_access_foundations import access  # noqa: F401 (fixture)
    from project_gateway.tests.test_organizations import service  # noqa: F401 (fixture)
except ImportError:
    if os.environ.get('OPHIOLITE_REQUIRE_GATEWAY') == '1': raise
    pytest.skip('Platform test runtime is needed for the gateway lane', allow_module_level=True)
from ophiolite.errors import OphioliteError
from test_checks_client import sdk, shale

OVER = b'0' * (8 * 1024 * 1024 + 1)


def test_a_file_over_8_mib_is_refused_with_the_sdk_sentence_and_nothing_is_stored(world, tmp_path):
    """Mutations: the gateway's FILE_LIMIT one byte more -> accepted -> red; the SDK sentences at 2 MiB -> red."""
    alice = sdk(world, 'alice')
    folder = shale(tmp_path)
    (folder / 'reference.las').write_bytes(OVER)
    with pytest.raises(OphioliteError) as caught: alice.check_publish(folder)
    assert str(caught.value) == 'Not published: a file of the check is larger than 8 MiB.'
    result = world.upload()
    with pytest.raises(OphioliteError) as caught: alice.check_compare(result['asset_id'], result['revision'], OVER, file_name='mine.las')
    assert str(caught.value) == 'Not compared: the file is larger than 8 MiB.'
    assert rows(world, 'SELECT count(*) FROM check_runs')[0][0] == 0
    assert alice.check_list(asset=result['asset_id'], revision=result['revision'])['records'] == []
