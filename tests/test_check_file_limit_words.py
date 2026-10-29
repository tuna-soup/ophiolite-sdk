"""adhoc-d38 (D-38): the SDK's size sentences say the gateway's check-file limit, 8 MiB, and the SDK sends check requests
up to the gateway's check body bound. The numbers are stated here, so the test runs where the SDK runs alone (the export
tree, `pytest tests --ignore=tests/gateway`); their parity with the Platform source is
`tests/gateway/test_check_file_limit_parity.py` (adhoc-night-green-6)."""
import re

import pytest

from ophiolite import checks

MIB = 8  # the gateway's checks.FILE_LIMIT in MiB, read from the Platform source by the parity test
CHECK_BODY = 33_658_436  # the gateway's checks.BODY_LIMIT for an 8 MiB file: 3 * base64(8 MiB) + 104_000


def test_the_size_sentences_say_8_mib_as_the_gateway_limits():
    """Mutations: a sentence left at 2 MiB / 2 MB -> red."""
    assert checks.PUBLISH_REFUSED['size'] == 'Not published: a file of the check is larger than 8 MiB.'
    assert checks.COMPARE_REFUSED['size'] == 'Not compared: the file is larger than 8 MiB.'
    for sentence in (checks.PUBLISH_REFUSED['size'], checks.COMPARE_REFUSED['size']):
        assert re.findall(r'larger than (\d+) MiB', sentence) == [str(MIB)]


def test_the_sdk_sends_check_requests_up_to_the_gateways_check_body_bound(monkeypatch):
    """The SDK's own request cap is the gateway's check body bound for checks publish and compare only, and names the
    limit it used. Mutations: `CHECK_REQUEST_BYTES` drifts from the formula -> red; `_post` keeps one cap for every
    route -> red; a lower cap (a request of exactly the bound refused) -> red; the refusal names the old number -> red."""
    from ophiolite import publish
    from ophiolite.client import Client
    from ophiolite.errors import ValidationFailed
    assert publish.CHECK_REQUEST_BYTES == 3 * 4 * -(-MIB * 1024 * 1024 // 3) + 104_000 == CHECK_BODY
    assert publish.MAX_REQUEST_BYTES == 2_100_000
    with pytest.raises(ValidationFailed) as caught: publish.json_bytes('x' * 40, limit=41)
    assert caught.value.violations == ('Request exceeds 41 bytes.',)
    with pytest.raises(ValidationFailed) as caught: publish.json_bytes('x' * 2_100_000)
    assert caught.value.violations == ('Request exceeds 2,100,000 bytes.',)
    sent = []
    client = Client.__new__(Client)
    client.project = 'p'
    monkeypatch.setattr(Client, '_post_bytes', lambda self, area, operation, raw, **options: sent.append((area, operation, len(raw))), raising=False)
    big = {'file': 'x' * 3_000_000}
    for operation in ('publish', 'compare'): client._post('checks', operation, big)
    assert [s[:2] for s in sent] == [('checks', 'publish'), ('checks', 'compare')]
    for area, operation in (('checks', 'list'), ('checks', 'publishers'), ('derived', 'publish')):
        with pytest.raises(ValidationFailed) as caught: client._post(area, operation, big)
        assert caught.value.violations == ('Request exceeds 2,100,000 bytes.',)
    at_bound = 'x' * (CHECK_BODY - len('{"project_id":"p","file":""}'))  # the serialized request is exactly the bound
    client._post('checks', 'compare', {'file': at_bound})
    assert sent[-1] == ('checks', 'compare', 33_658_436)
    with pytest.raises(ValidationFailed) as caught: client._post('checks', 'compare', {'file': at_bound + 'x'})
    assert caught.value.violations == ('Request exceeds 33,658,436 bytes.',)
