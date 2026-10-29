"""adhoc-night-green-6: the numbers `tests/test_check_file_limit_words.py` states (8 MiB, the check body bound) are the
Platform's `checks.FILE_LIMIT`, `ENCODED_LIMIT` and `BODY_LIMIT` in this checkout, compared as values (the gateway
module is imported, as the other gateway tests import project_gateway). A monorepo-only test: the export tree runs the
SDK half alone."""
from test_check_file_limit_words import CHECK_BODY, MIB

from ophiolite import publish
from project_gateway import checks


def test_the_sdk_numbers_are_the_gateways_check_limits():
    """Mutations: the gateway's FILE_LIMIT, ENCODED_LIMIT or BODY_LIMIT changed alone (a number or a trailing `+ 1`)
    -> red; the SDK test's stated MIB or CHECK_BODY changed alone -> red."""
    assert checks.FILE_LIMIT == MIB * 1024 * 1024 == 8_388_608
    assert checks.ENCODED_LIMIT == 11_184_812  # base64 of 8 MiB
    assert checks.BODY_LIMIT == CHECK_BODY == publish.CHECK_REQUEST_BYTES
