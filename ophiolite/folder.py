"""The project folder, checked byte by byte (E117 s0, D4). Offline; standard library only — it never reads a table or
an image, so pandas and pyarrow are never imported.

    from ophiolite.folder import check
    report = check('field/')    # {ok, verified, schema, files, items, first_problem}

A folder whose block is `ophiolite.project-folder/2` is checked here: the block by the contract's own validator
(contracts/folders/v1/folder.py), then every file as `open_bundle` checks a bundle file (no link on the way, the file
and total limits, size, SHA-256) and nothing in the folder that the manifest does not list. A bundle without a /2
block — a server bundle, or a /1 folder ophiolite-mapper writes today — is checked by `open_bundle` unchanged, and a
/1 folder's items are read from its verified recipe (`derived: "recipe"`), never guessed. `verified` is always
"bytes": the rows, the coordinate systems and the payloads themselves are not read.

A manifest with a citation (bundle 2.15, E147 s0) lists the standard descriptors beside it (RO-Crate, Croissant,
DataCite) and a bundle's prov.json; both kinds of folder check them as open_bundle does (bundle.citation_verdicts):
prov.json by its digest, each descriptor compared with the manifest. Their rows carry the roles `citation-prov` and
`citation-descriptor`; a refusal names its code and its place, `croissant.json:$.license` for a descriptor's value.

Each problem is a code and the place it was found: a file's path, or a JSON path into the manifest for the block's
rules (the validator's codes, listed on contracts/folders/v1/README.md).
"""
from pathlib import Path

from . import bundle
from .errors import OphioliteError

FOLDER_2 = bundle.FOLDER_2
_folder_contract = bundle._folders_contract  # the packaged project folder validator, loaded once (E117 s1: one copy)


def _report(schema, files, items, problem):
    return {'ok': problem is None, 'verified': 'bytes', 'schema': schema, 'files': files, 'items': items, 'first_problem': problem}


def _problem(code, path, sentence=None):
    return {'code': code, 'path': path, **({'sentence': sentence} if sentence else {})}


def _refused(error):
    """E147 s0: a citation or descriptor refusal as a problem: its code, its place (a manifest JSON path, a file, or
    `file:json path`) and, for the contract's codes, its words (a file's own fault keeps the folder's words for it)."""
    return _problem(error.code, error.path, error.sentence if error.code in bundle._descriptors_contract().CODES else None)


def _manifest(root):
    path = root / 'manifest.json'
    if root.is_symlink() or not root.is_dir(): return None, _problem('not-a-folder', None, 'A project folder is a directory.')
    if path.is_symlink() or not path.is_file(): return None, _problem('file-missing', 'manifest.json')
    if path.stat().st_size > bundle.MAX_MANIFEST_BYTES: return None, _problem('file-too-large', 'manifest.json')
    try: return bundle._finite_json(path.read_bytes(), 'The bundle manifest'), None
    except OphioliteError as error: return None, _problem('manifest-unreadable', 'manifest.json', str(error))


def _unlisted(root, listed):
    """Files (and links to files) the manifest does not list; a linked directory is a listed file's fault, not one."""
    return sorted(p.relative_to(root).as_posix() for p in root.rglob('*')
                  if p.is_file() and p.relative_to(root).as_posix() not in listed
                  and not any((root / parent).is_symlink() for parent in p.relative_to(root).parents if parent != Path('.')))


def _check_2(root, manifest):
    contract, block = _folder_contract(), manifest['folder']
    try: contract.validate(block, manifest)
    except contract.FolderError as error: return _report(FOLDER_2, [], [], _problem(error.code, error.path))
    if manifest.get('assets'):
        return _report(FOLDER_2, [], [], _problem('assets-unsupported', '$.assets', bundle.FOLDER_2_BESIDE_ASSETS))
    files, problem = [], None
    verdicts, total = bundle.folder_verdicts(root, block['files'], 0)  # E117 s1: the traversal open_bundle uses
    for row, verdict in zip(block['files'], verdicts):
        files.append({'path': row['path'], 'role': row['role'], 'verdict': verdict})
        if verdict != 'ok' and problem is None: problem = _problem(verdict, row['path'])
    cited, refused, _ = bundle.citation_verdicts(root, manifest, total)  # E147 s0 (D3): the check open_bundle makes
    files += cited
    if refused is not None and problem is None: problem = _refused(refused)
    listed = {row['path'] for row in block['files']} | {'manifest.json'} | set(bundle.citation_names(manifest))
    unlisted = _unlisted(root, listed)
    files += [{'path': path, 'role': None, 'verdict': 'file-unlisted'} for path in unlisted]
    if unlisted and problem is None: problem = _problem('file-unlisted', unlisted[0])
    by_path = {f['path']: f['verdict'] for f in files}
    items = [{'path': i['path'], 'kind': i['kind'], 'osdu': dict(i['osdu']), 'derived': 'manifest', 'verdict': by_path[i['path']]}
             for i in block['items']]
    return _report(FOLDER_2, files, items, problem)


def _check_opened(root, manifest):
    """open_bundle unchanged; then the files it verified, the unlisted ones, and a /1 folder's items from its recipe."""
    block = manifest.get('folder') if isinstance(manifest, dict) else None
    schema = block.get('schema') if isinstance(block, dict) else None
    try: opened = bundle.open_bundle(root)
    except bundle.DescriptorRefused as error: return _report(schema, [], [], _refused(error))  # E147 s0: its code and place
    except OphioliteError as error: return _report(schema, [], [], _problem('bundle-refused', None, str(error)))
    files = [{'path': f['path'], 'role': f.get('role'), 'verdict': 'ok'} for a in manifest['assets'] for f in a['files']]
    files += [{'path': row['path'], 'role': row['role'], 'verdict': 'ok'} for row in opened.folder]
    files += [{'path': row['path'], 'role': row['role'], 'verdict': 'ok'} for row in opened.citation]
    files += [{'path': path, 'role': None, 'verdict': 'file-unlisted'} for path in opened.unlisted]
    problem = _problem('file-unlisted', opened.unlisted[0]) if opened.unlisted else None
    items = [{'path': i['path'], 'kind': i['kind'], 'osdu': i['osdu'], 'derived': 'recipe', 'verdict': 'ok'} for i in opened.items]
    return _report(schema, files, items, problem)


def check(path):
    """Check a bundle or project folder directory completely, byte by byte, and report each file and item. Never
    raises for a damaged folder: the report says `ok: false` and names the first problem."""
    root = Path(path)
    manifest, problem = _manifest(root)
    if problem: return _report(None, [], [], problem)
    block = manifest.get('folder') if isinstance(manifest, dict) else None
    if isinstance(block, dict) and block.get('schema') == FOLDER_2: return _check_2(root, manifest)
    return _check_opened(root, manifest)


def write_folder(out, items, *, writer=None, namespace='synthetic', created_at=None, citation=None):
    """E117 s1: write a data frame of wells as a project folder /2 and return its check() report. Needs the `folder`
    extra (pandas, pyarrow, pyproj); see ophiolite.folder_write, imported only here. E147 s1: with CITATION (the
    block's own fields) the folder is cited at 2.15 and carries its RO-Crate, Croissant and DataCite descriptors."""
    from .folder_write import write_folder as write
    return write(out, items, writer=writer, namespace=namespace, created_at=created_at, citation=citation)
