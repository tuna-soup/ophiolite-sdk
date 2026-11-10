"""E164 s1 C3: the wheel the lane built from this tree (OPHIOLITE_TEST_DIST) carries the README as its Markdown long
description and the four Project-URL entries of pyproject.toml. Each test names the mutation it catches."""
import email.parser
import os
from pathlib import Path
import tomllib
import zipfile
import pytest

SDK = Path(__file__).resolve().parents[1]
NAMES = ('Homepage', 'Documentation', 'Source', 'Changelog')


@pytest.fixture(scope='module')
def metadata():
    dist = os.environ.get('OPHIOLITE_TEST_DIST')
    if not dist:
        if os.environ.get('OPHIOLITE_REQUIRE_WHEEL') == '1': pytest.fail('Set OPHIOLITE_TEST_DIST to the folder holding the built wheel')
        pytest.skip('Set OPHIOLITE_TEST_DIST to the folder holding the built wheel')
    [wheel] = Path(dist).glob('ophiolite-*.whl')
    with zipfile.ZipFile(wheel) as z:
        [name] = [n for n in z.namelist() if n.endswith('.dist-info/METADATA')]
        return email.parser.Parser().parsestr(z.read(name).decode('utf-8'))


def test_the_long_description_is_the_readme_in_markdown(metadata):
    """Mutation: `readme` removed from pyproject.toml → no content type and no body."""
    assert metadata['Description-Content-Type'] == 'text/markdown'
    assert metadata.get_payload() == (SDK / 'README.md').read_text(encoding='utf-8')


def test_the_project_urls_are_the_four_of_pyproject(metadata):
    """Mutations: a URL removed from [project.urls], or its value changed after the wheel was built → the lines differ."""
    urls = tomllib.loads((SDK / 'pyproject.toml').read_text(encoding='utf-8'))['project']['urls']
    assert tuple(urls) == NAMES
    assert metadata.get_all('Project-URL') == ['%s, %s' % item for item in urls.items()]
