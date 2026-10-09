"""E104 C2: the Workspace page addresses. Literal expectations; the plug-in (C5) and the Workspace (C7) copy this table
into their own tests, so each repository keeps its own literals."""
from urllib.parse import parse_qs, urlsplit
import pytest
from ophiolite.errors import Refused
from ophiolite.links import FAMILY_OF_KIND, family_of, item_url

V1, V2 = 'r/1?', 'a' * 64

ADDRESSES = [
    (('https://ws.example', 'a project', 'a', 'x/y?#', V1), 'https://ws.example/project/a%20project/data/a~x%2Fy%3F%23?revision=r%2F1%3F'),
    (('https://ws.example', 'a project', 'a', 'x/y?#', V2), 'https://ws.example/project/a%20project/data/a~x%2Fy%3F%23?revision=' + 'a' * 64),
    (('https://ws.example', 'a project', 'm', 'x/y?#', V1), 'https://ws.example/project/a%20project/data/m~x%2Fy%3F%23?revision=r%2F1%3F'),
    (('https://ws.example', 'a project', 'm', 'x/y?#', V2), 'https://ws.example/project/a%20project/data/m~x%2Fy%3F%23?revision=' + 'a' * 64),
    (('https://ws.example', 'a project', 's', 'x/y?#', None), 'https://ws.example/project/a%20project/data/s~x%2Fy%3F%23'),
    (('http://127.0.0.1:8080/', 'p', 'm', 'id', V1), 'http://127.0.0.1:8080/project/p/data/m~id?revision=r%2F1%3F'),
]


@pytest.mark.parametrize('args,expected', ADDRESSES)
def test_literal_addresses(args, expected):
    assert item_url(*args) == expected


def test_no_tab_until_e98():
    for args, _ in ADDRESSES:
        assert 'tab' not in parse_qs(urlsplit(item_url(*args)).query)
    with pytest.raises(TypeError):
        item_url('https://ws.example', 'p', 'm', 'id', V1, 'summary')


def test_family_of_kind_literal():
    assert FAMILY_OF_KIND == {'external-scalar-map': 'a', 'external-curve': 'a', 'derived': 'm', 'uploaded': 'm'}
    assert [family_of(k) for k in ('external-scalar-map', 'external-curve', 'derived', 'uploaded')] == ['a', 'a', 'm', 'm']
    with pytest.raises(Refused, match='^This item has no Workspace page.$'):
        family_of('recipe')


@pytest.mark.parametrize('args,sentence', [
    (('https://ws.example', 'p', 's', 'id', V1), 'A connected selection always shows its current version.'),
    (('https://ws.example', 'p', 'x', 'id', V1), 'This item has no Workspace page.'),
    (('https://ws.example', 'p', 'm', 'id', ''), 'Name the version.'),
    (('https://ws.example', '', 'm', 'id', V1), 'Name the project and the item.'),
    (('https://ws.example', 'p', 'm', None, V1), 'Name the project and the item.'),
    (('https://ws.example/app', 'p', 'm', 'id', V1), 'Use HTTPS or a loopback origin without credentials or a path.'),
    (('http://ws.example', 'p', 'm', 'id', V1), 'Use HTTPS or a loopback origin without credentials or a path.'),
])
def test_refused(args, sentence):
    with pytest.raises(Refused) as raised:
        item_url(*args)
    assert str(raised.value) == sentence
