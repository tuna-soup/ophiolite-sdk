"""E131 s1 C2 (D5): every start `make` and `procedures.new` write says it is a tool in its first comment, and nothing
else in it changed: with that one line removed each procedure.py is byte-identical to the start written at f1d813538
(the literals below), and its code still imports only names every release has. Expected values are literals."""
import ast
import hashlib
import json

from ophiolite import _version, procedure_templates as templates, procedures

COMMENT = ('# A tool. Ophiolite reads it as procedure.json and procedure.py, and its code imports procedure, the name every '
           'release runs.')
# The ophiolite names a start's code may use: those the pre-lane release (2026.10.128) has. Never `tool` or `ophiolite.tools`.
RELEASED = {'ophiolite', 'ophiolite.procedure', 'ophiolite.compared', 'ophiolite.delivered', 'ophiolite.refused',
            'ophiolite.not_delivered', 'ophiolite.unknown', 'ophiolite.readers', 'ophiolite.writers',
            'ophiolite.residuals.read_survey', 'ophiolite.residuals.read_tops'}
# sha256 of procedure.py written by `make(<dir>/demo, step, kind)` at f1d813538 (before E131).
BEFORE = {
    ('check', 'deviation-csv/1'): '0f80a3977b0921f44ac556a622b160564708ad7aba2ebbd4911a89d437f62508',
    ('check', 'well-tops-csv/1'): '080af5b5391b67a14b9fd858f30a5e73bd2fc04d3af43728c7eaf0e3a97d4212',
    ('process', 'deviation-csv/1'): '3e57e0b3700439581c01f0dd0098749fc1a2c87594bfc8bd2e07ea3edcde06bd',
    ('process', 'esri-ascii-grid/1'): '35b8681312548d65df7936b0321ec85d2c17cfe9df4623113968392672afa6a6',
    ('process', 'las2/1'): '31b38d4dafd71e18e8e1c52f8aa9e46bfeebdcdd15b81d6ced44e509634d31cc',
    ('process', 'mesh-text/1'): 'f8f27e230706145d8cec2c3418786029de61c580fc22ccfac4dc16bb1d4bd5ad',
    ('process', 'model-section-text/1'): '009aed88b240f1948a8329033d10f1197b5fee843ce0b56acb4cf277afd21aef',
    ('process', 'opendtect-faultsticks/1'): 'fe7cc3af288c5acc741ba61e1e2e6c981dc2f065d73acfd3c4ba5a186a01895b',
    ('process', 'points-csv/1'): '200b0a36bbe2072a868fd4324beeacc156a33285037044ec980916f43427d752',
    ('process', 'seismic-section-text/1'): 'd4c0dd0f1d0d5ffc667707433222daa2795e7a96fb262804750e282db5be672f',
    ('process', 'time-depth-csv/1'): 'ac9abdc40772d8a2a91afa278321fee06c769f754f332aec4cbaa2c3daed8e76',
    ('process', 'wavelet-text/1'): '6707ef6a210ed7cd19122e4690e57516071e9438f9ada6527da30ce23c144d50',
    ('process', 'well-location/1'): '585cce3cb20b4c580a287d74b2708fa7e9f4f572f3c782e3cb2ce54c9f22943b',
    ('process', 'well-tops-csv/1'): 'c64677e87ad221bc59cd5ef2fc55c197bf0066158ef0bcdba3a5eaae204e0b5e',
    ('read', 'deviation-csv/1'): '0230eb478eaf97aa52619a16187c23a72078e1b0cef1ae780da3493ade9743f0',
    ('read', 'esri-ascii-grid/1'): '49d24273d796c65de5ccafb22e5493734afae99b0dd1ad50df9bcac051ac06a0',
    ('read', 'las2/1'): 'eb64b223393e70b0ed782091585d23c1848ff969a2dfb6bc20160adc06f3746e',
    ('read', 'mesh-text/1'): 'fa75410b41c7df8bea26d7e8dcb36261d61d1738c47d995352b845724285594b',
    ('read', 'model-section-text/1'): '5fbeccf460a8040c767a10d6b25afe2ca6d5e09735afc1cb1ddfbdb2ec4e2249',
    ('read', 'opendtect-faultsticks/1'): '48b7b0c9031b9553acb7631ff53ddfd65d103619194bf92e652d6ef8e6ebb2a2',
    ('read', 'points-csv/1'): '612b2e7cbab61d1134471c7d547ff00108b2103fadbaad570c95d7d1c13b2ba6',
    ('read', 'time-depth-csv/1'): '46e495f67692b4b94fff28b9070be1df4d8b071d10ad8a2c655827577b15666d',
    ('read', 'wavelet-text/1'): 'a10f96b351258664394d64f30e67c8cb2d8b40495af7a69eadc785b5648082f4',
    ('read', 'well-location/1'): '78f8ffe0d7a864d87c69bedbeedaf2ec4a0583c6d95633970655e3a7136d26e6',
    ('read', 'well-tops-csv/1'): '721cf87017ecc86a7cfac2e5492e56769fb7e5eb3a6274e113d2fb6d1cceb52a',
    ('send', 'deviation-csv/1'): 'dae898f1b73e0f516073c0a67cd157d00d48fd164e59bd3596f75f96b23a6f0a',
    ('send', 'esri-ascii-grid/1'): '4bc2414ccb18787fd16c29979ea5a94323e797775ec3aee10bdb8a3852aece2a',
    ('send', 'las2/1'): '9281f0edd741cefa6d93717ae29072918cdc82d3878ab3ac43f6f49ec851d23b',
    ('send', 'mesh-text/1'): '9c5871bd8c58ce0c002b31b0d6d5b85a02e3e1b9ec76d415a642dca3b0648cc8',
    ('send', 'model-section-text/1'): 'd0f06e5a477a02c74197d3225f532d868a78fe1bd49453684b68dcc735d6112a',
    ('send', 'opendtect-faultsticks/1'): 'e284cb1851472f3a2e10ba61f7475b5c2fbf4e19c7d6078aa51d1aeb7abada24',
    ('send', 'points-csv/1'): '6a5d1b492db869641a963d039289bd751774bee8830f3b691b1e7abbf2c04e66',
    ('send', 'seismic-section-text/1'): 'ca7f5e0b16986df6d6196d1aef644790cfa961a3af7e1f19eebbbc81928587ae',
    ('send', 'time-depth-csv/1'): '834e744b360ea745480245f895f61fdbb0cf922982d6f58f959d5daad61e932b',
    ('send', 'wavelet-text/1'): '9a94d580f5f32618764c066e09fd55a5ef979067add3a0e2298776a076e78c36',
    ('send', 'well-location/1'): '26d48ce61c316a4fa2da20fa01cb480803fb8d0f7fac02c5fc68399fdaec7190',
    ('send', 'well-residual/1'): 'e7637716016ce9c071f137df78b25ae1f7d7f366aa79e27a5a3bf0a27961502f',
    ('send', 'well-tops-csv/1'): 'b3df5b309a4b12c4f6b571b77e1547d0671163965b5e660787b5eeb326e0e00a',
    ('source', 'deviation-csv/1'): '7776e08a1692071b3522fff3ffacc2bde60985ed6429155d18c782e47bc9b1e4',
    ('source', 'esri-ascii-grid/1'): 'ec43ca7838cc7d26590cee08437607ea5e4bd0f01fa853c48de3a9abf1df4c87',
    ('source', 'las2/1'): '1203de59688d754e014740d0635071f62ad599e15ebe206c75d4284bc4b7f887',
    ('source', 'mesh-text/1'): '96c01879d8c4a0531c8e8f97ae1186039b85185a04f96df98fdcaf791affabc0',
    ('source', 'model-section-text/1'): 'a3396e37a73566953e9e7c3baa192447e7827d9efbc694cd5e7f56e7d9dff9cc',
    ('source', 'opendtect-faultsticks/1'): '2dc75c6ddb5183f9a5cf062214aeb20c111000cf3be3a066eac0db6d004cdedf',
    ('source', 'points-csv/1'): 'b5f86868c333d9537bf20f09228b74bc22e1eece1434e295c453b34f8b5db06f',
    ('source', 'time-depth-csv/1'): '673f84891a2a73a8cffe5d9ba7cc24e8a375dbf519fa0ff4b54ff80cb9b8ee3e',
    ('source', 'wavelet-text/1'): '312adb12136b19c6c03607a152d140853f01ab142c53383840593b1da6cba3f7',
    ('source', 'well-location/1'): 'cc15810feee4f03805aec14dbe3256a4cf103a8212c7207c322862e9821b4152',
    ('source', 'well-tops-csv/1'): '4063a30cb71c53c460f99239b0f13e3bc57e9fe81e8f2ac5a9a8b13413664692',
}
# E105a's no-kind process start, `procedures.new(<dir>/demo, 'process')`, at f1d813538 and at this head.
NO_KIND_BEFORE = {'procedure.py': '07dcb95d9891d32a2c459e0bf59e6c8b7649212bfb95475a05a37983cd9dd101',
                  'procedure.json': '3f12d0c33c0ce7a81a40aaa4598e6abc276e46bfb76f9ad467d1a03b37b0c16e',
                  'digest': 'd4909f22d08a31b1f0e77edbb58d51cfb4894da788293277502bbc92044912e9'}
NO_KIND_DIGEST = '04fced678f56505ab5362a75c22c41fd2fe80b7119982df65c9008d918073722'
# Every other member of three typed starts at f1d813538 (template.json compared by its fields, R2-2).
MEMBERS = {
    ('process', 'well-tops-csv/1'): {
        'data/declared.json': '104b0a25360c3e35b9f91019fa8f3de1baedcc10735b1d2a4ff74ec9f08cc571',
        'data/tops.csv': 'c84b0db79664a2abf8f83f1282ad32b26d9bc92de9fb57ba5400933fe06bf243',
        'procedure.json': 'cd6722c660f2c169e95bbd9e9fd3f10eec2693ff3e2202f78341d20fe6a8c920',
        'tests/test_procedure.py': 'd21da5a47532911717f772b35d9fba6bb99e2e0aa14fbb18e61c4195c51c1803'},
    ('read', 'las2/1'): {
        'data/sample.json': '518324a4d47fb1ea78f38c3822c669b2e25074376b7d92176697a5b3a6719241',
        'procedure.json': '3bb396efec8e7cf8426eea616c2be3c0069310ff2d007dcfbcb245c5392f00f2',
        'tests/test_procedure.py': '6f020f6ba295fc312a7552c0ab5f0f20abfea8e1954c660eceb4eb074ae3f3ef'},
    ('send', 'well-tops-csv/1'): {
        'data/tops.csv': 'c84b0db79664a2abf8f83f1282ad32b26d9bc92de9fb57ba5400933fe06bf243',
        'procedure.json': '62316c05ef33df92d47cc618dbc932ecccdc6c3d8249d7977043bee3557adde1',
        'tests/test_procedure.py': '3d18a0a75b18e77b80eb2c22395aaf2b5bc457520ee0e19722a66780bc011977'},
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def names(code):
    """The ophiolite names a start's code imports or reads as attributes."""
    found = set()
    for node in ast.walk(ast.parse(code)):
        if isinstance(node, ast.ImportFrom) and (node.module or '').split('.')[0] == 'ophiolite':
            found |= {f'{node.module}.{alias.name}' for alias in node.names}
        elif isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names if alias.name.split('.')[0] == 'ophiolite'}
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == 'ophiolite':
            found.add('ophiolite.' + node.attr)
    return found


def starts(tmp_path):
    """(pair or 'no-kind', folder) for every start this SDK writes."""
    made = []
    for index, (step, kind) in enumerate(sorted(templates.made())):
        folder = tmp_path / str(index) / 'demo'
        templates.make(folder, step, kind)
        made.append(((step, kind), folder))
    procedures.new(tmp_path / 'no-kind/demo', 'process')
    return made + [('no-kind', tmp_path / 'no-kind/demo')]


def test_every_start_names_tools_in_its_first_comment_and_imports_only_released_names(tmp_path):
    made = starts(tmp_path)
    assert len(made) == 50
    for pair, folder in made:
        lines = (folder / 'procedure.py').read_text().split('\n')
        assert lines[0].startswith('"""') and lines[0].endswith('"""'), pair
        assert lines[1] == COMMENT, pair
        assert [line for line in lines if line.startswith('#')][0] == COMMENT, pair
        used = names('\n'.join(lines))
        assert used <= RELEASED, (pair, used - RELEASED)
        assert 'ophiolite.tool' not in used and 'ophiolite.tools' not in used, pair


def test_only_the_comment_changed(tmp_path):
    made = dict(starts(tmp_path))
    assert set(made) - {'no-kind'} == set(BEFORE)
    for pair, folder in made.items():
        raw = (folder / 'procedure.py').read_bytes()
        assert raw.count((COMMENT + '\n').encode()) == 1, pair
        before = NO_KIND_BEFORE['procedure.py'] if pair == 'no-kind' else BEFORE[pair]
        assert sha(raw.replace((COMMENT + '\n').encode(), b'', 1)) == before, pair
    for pair, members in MEMBERS.items():
        folder = made[pair]
        written = {str(path.relative_to(folder)) for path in folder.rglob('*') if path.is_file()}
        assert written == {*members, 'procedure.py', 'template.json'}, pair
        for member, expected in members.items():
            assert sha((folder / member).read_bytes()) == expected, (pair, member)
        template = json.loads((folder / 'template.json').read_text())
        assert template.pop('sdk_version') == _version.__version__
        assert template == {'step': pair[0], 'kind': pair[1], 'pairs_rules_version': '1.4.0'}, pair
    no_kind = made['no-kind']
    assert sorted(path.name for path in no_kind.iterdir()) == ['procedure.json', 'procedure.py']
    assert sha((no_kind / 'procedure.json').read_bytes()) == NO_KIND_BEFORE['procedure.json']
    assert procedures.validate(no_kind)['digest'] == NO_KIND_DIGEST != NO_KIND_BEFORE['digest']
