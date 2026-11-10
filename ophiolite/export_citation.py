"""E147 s2 (strategy E147-s2-export-descriptors D1-D4): the citation of an export. The person gives words (title,
description, version); the records give the facts: who made each selected version (its story's root node), the
project's organisation (discovery) and the files' licences (each read's `acquisition.listed_in.licence`)."""
from datetime import datetime, timezone

from .errors import Refused

EXPORT_FIELDS = ('title', 'description', 'version')
MAX_CREATORS = 64
GIVEN = ('The citation of an export takes title, description and version; the writer adds creators, publisher, licence '
         'and date from the records.')
TOO_MANY = ('A citation names at most 64 creators; these versions were made by %d people. Export fewer versions, or '
            'export without a title.')
NO_PUBLISHER = 'A citation names its publisher: this project is not in an organisation you belong to. Export without a title.'
ORGANISATION_ONLY = 'No selected version names a person who made it, so the organisation is the creator.'  # R-3
DESCRIPTORS = ['ro-crate-metadata.json', 'croissant.json', 'datacite.json']
_clock = datetime  # tests freeze it


def given(citation):
    """The person's words, checked before anything is read (D1)."""
    if not isinstance(citation, dict) or not set(citation) <= set(EXPORT_FIELDS): raise Refused(GIVEN, code='citation-given')
    return dict(citation)


def publisher(client):
    """The name of the organisation holding CLIENT's project, read through the client's own transport and credential
    (D3). Every discovery page is followed; a discovery failure raises Unavailable."""
    from .account import Account
    account = Account(client.url, client.credential, http=client.http)
    row = next((p for p in account.projects() if p.get('id') == client.project), None)
    organisation = row and row.get('organization_id')
    name = next((o['name'] for o in account.organizations() if o['id'] == organisation), None) if organisation else None
    if not name: raise Refused(NO_PUBLISHER, code='citation-publisher')
    return name


def _person(made):
    """The person the story states made a version (D2.1): `by` for a person, `on_behalf_of` for an agent, else None."""
    if not isinstance(made, dict): return None
    if made.get('by_kind') == 'person': return made.get('by')
    if made.get('by_kind') == 'agent': return made.get('on_behalf_of')
    return None


def _instant(at):
    if not isinstance(at, str): return None
    try: return datetime.fromisoformat(at.replace('Z', '+00:00'))
    except ValueError: return None


def creators(pages, organisation):
    """The creators from each selected version's story page at limit=1, in selection order [((asset, revision), page)]
    (D2): named persons ordered by their earliest dated version, then the undated, ties in selection order; none left
    gives the organisation (R-3); more than 64 is refused."""
    found = {}  # person id -> [date or None, first selection index, name]
    for index, ((asset, revision), page) in enumerate(pages):
        root = next((n for n in page.get('nodes') or [] if n.get('asset_id') == asset and n.get('revision') == revision), None)
        made = (root or {}).get('made')
        person = _person(made)
        name = ((page.get('display') or {}).get('member_names') or {}).get(person) if person else None
        if not isinstance(name, str) or not name: continue
        at = _instant(made.get('at'))
        entry = found.setdefault(person, [None, index, name])
        if at is not None and (entry[0] is None or at < entry[0]): entry[0] = at
    if len(found) > MAX_CREATORS: raise Refused(TOO_MANY % len(found), code='citation-creators')
    ordered = sorted(found.values(), key=lambda e: (e[0] is None, e[0] or datetime.min.replace(tzinfo=timezone.utc), e[1]))
    return [{'name': name, 'kind': 'person'} for _, _, name in ordered] or [{'name': organisation, 'kind': 'organisation'}]


def stories(client, selections):
    """[((asset, revision), page)] of the story at limit=1 for each selected version."""
    return [((asset, revision), client.story(asset, revision, limit=1)) for asset, revision, _ in selections]


def licences(items):
    """Each read's catalogue licence (`acquisition.listed_in.licence`), or None, in item order (D4)."""
    out = []
    for _, read in items:
        descriptor = read._wire_descriptors[0] if hasattr(read, '_wire_descriptors') else getattr(read, '_wire_descriptor', None)
        listed = ((descriptor or {}).get('acquisition') or {}).get('listed_in')
        out.append(listed.get('licence') if isinstance(listed, dict) else None)
    return out


def complete(words, *, creators, publisher, licence, notice):
    """The citation block write_bundle takes: the person's words and the records' facts; `published` is the UTC date."""
    from .bundle import _descriptors_contract
    contract = _descriptors_contract()
    block = {'schema': contract.CITATION, **{k: words[k] for k in ('title', 'description') if k in words},
             'published': _clock.now(timezone.utc).date().isoformat(), **({'version': words['version']} if 'version' in words else {}),
             'creators': creators, 'publisher': {'name': publisher}, 'licence': licence, **({'notice': notice} if notice else {}),
             'doi': None, 'descriptors': list(DESCRIPTORS)}
    return block


def check(block):
    """Raise the reader's DescriptorRefused for a block the contract refuses (a missing description: citation-schema)."""
    from .bundle import _descriptors_contract, _refused
    contract = _descriptors_contract()
    try: contract.validate_block(block)
    except contract.DescriptorError as error: raise _refused(error) from None
    return block


def licence_of(items):
    from .bundle import _descriptors_contract
    return _descriptors_contract().export_licence(licences(items))

