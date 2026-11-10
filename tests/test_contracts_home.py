"""E164 s1 C1: the SDK's guarantee, limit, qualification and compatibility statements live in CONTRACTS.md, and the
reference that was the README lives in docs/sdk-guide.md. Each test names the mutation it catches."""
import json
from pathlib import Path
import re

SDK = Path(__file__).resolve().parents[1]
CONTRACTS = SDK / 'CONTRACTS.md'
GUIDE = SDK / 'docs' / 'sdk-guide.md'
CITED = SDK / 'tests' / 'fixtures' / 'contracts-cited-sentences.json'
LINK = re.compile(r'\]\(([^)\s]+)\)')


def flat(text):
    """TEXT with every run of white space as one space: a sentence is verbatim whatever its line breaks."""
    return re.sub(r'\s+', ' ', text)


def homeless(text, sentences):
    """The cited SENTENCES that TEXT does not carry verbatim."""
    body = flat(text)
    return [s for s in sentences if flat(s) not in body]


def broken(path, text):
    """The relative link targets of TEXT (a Markdown file at PATH) that name no file or folder inside the SDK."""
    found = []
    for target in LINK.findall(text):
        if re.match(r'[a-z][a-z0-9+.-]*:', target) or target.startswith('#'): continue  # absolute address or same-page anchor
        place = (path.parent / target.split('#', 1)[0]).resolve()
        if not place.exists() or not place.is_relative_to(SDK): found.append(target)
    return found


def sentences():
    return json.loads(CITED.read_text(encoding='utf-8'))['sentences']


def test_every_cited_sentence_is_verbatim_in_contracts():
    """Mutation: delete a cited sentence from CONTRACTS.md → it is listed as homeless."""
    cited = sentences()
    assert cited and len(set(cited)) == len(cited)
    assert homeless(CONTRACTS.read_text(encoding='utf-8'), cited) == []


def test_a_deleted_cited_sentence_is_found():
    text = flat(CONTRACTS.read_text(encoding='utf-8'))
    assert any(s not in CONTRACTS.read_text(encoding='utf-8') for s in sentences())  # one spans a line break: flat() matters
    for sentence in sentences():
        assert homeless(text.replace(flat(sentence), ''), [sentence]) == [sentence]


def test_contracts_opens_with_its_title_and_points_at_the_schema_page():
    """Mutation: another first line, or no link to docs/contracts.md → this fails."""
    lines = CONTRACTS.read_text(encoding='utf-8').splitlines()
    assert lines[0] == '# Stability, compatibility and qualification statements of the Ophiolite SDK'
    assert '](docs/contracts.md)' in '\n'.join(lines[:4])


def test_every_relative_link_of_the_two_files_resolves_inside_the_sdk():
    """Mutation: leave a moved link unrewritten (`examples/x` in docs/sdk-guide.md) → it names no file."""
    for path in (CONTRACTS, GUIDE):
        text = path.read_text(encoding='utf-8')
        assert LINK.findall(text), path
        assert broken(path, text) == [], path


def test_an_unrewritten_link_is_found():
    text = GUIDE.read_text(encoding='utf-8')
    assert '](../examples/public_curve_handoff.py)' in text
    assert broken(GUIDE, text.replace('](../examples/', '](examples/')) == ['examples/public_curve_handoff.py']
    assert broken(CONTRACTS, '[outside](../../README.md)') == ['../../README.md']  # inside the SDK only
