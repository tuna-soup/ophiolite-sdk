"""E123 S3a C2, S3b C5, through the installed SDK against the in-process gateway (synthetic files only). Four Petrel
scattered-data maps that state no basis, uploaded from one folder, print the gateway's proposal sentence after the files
sentence (served by default since S3b, K6); the SDK confirms or declines it; the command line answers the shared basis
once with --share-basis and --basis and each file's own `positive` with --declare, and every file is added; two GeoTIFF
grids complete with the basis options alone."""
import json

import numpy as np
import pytest
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from test_in_process_publish import web, shared, app, service  # noqa: F401 (fixtures)
from test_upload_source import folder, upload
from project_gateway.tests.test_petrel_scattered_journey import GRID

import ophiolite

ORIGIN = 'https://workspace.example'
MAPS = [('a.txt', GRID)] + [('%s.txt' % n, GRID.replace(b'-1201.250000', v)) for n, v in (('b', b'-1201.500000'), ('c', b'-1201.750000'), ('d', b'-1202.000000'))]
PROPOSAL = 'These 4 files state no basis. Do they share one?'
ITEMS = ['crs', 'vertical_domain', 'vertical_datum', 'units.xy', 'units.z']


def tiff(unit, first):
    with MemoryFile() as m:
        with m.open(driver='GTiff', width=2, height=2, count=1, dtype='float64', crs='EPSG:23031', transform=from_origin(500000, 6700000, 25, 25), nodata=-9999.0) as ds:
            ds.write(np.array([[first, 1.0], [2.0, 3.0]]), 1)
            ds.units = (unit,)
        return m.read()


def runs(web):
    return ophiolite.Client(ORIGIN, 'p', ophiolite.Credential.bearer('oph_api_alice:read,write'), web.c).upload_runs


def sent(web, tmp_path, name):
    return runs(web).upload(str(folder(tmp_path, MAPS, name)), attribution='NLOG.NL', rights_confirmed=True, audience=())


def values(web):
    """{path: {item: value}} the latest upload's files were given by a basis answer (`declared` by you), as served."""
    view = runs(web).status(runs(web).list()[0]['run_id']).view
    served = view['basis']['grouping']['resolved']['per_member']
    return {p: {i: v['value'] for i, v in items.items() if (v['class'], v['source']) == ('declared', 'you')} for p, items in served.items()}


def questions(report):
    return [(q['target'], q['item'], len(q['members'])) for q in report.view['basis']['grouping']['resolved']['questions']]


def test_the_proposal_sentence_prints_as_served(web, tmp_path):
    report = sent(web, tmp_path, 'Maps')
    assert [i['state'] for i in report.items] == ['needs-decision'] * 4
    assert [s['sentence'] for s in report.view['basis']['sentences']] == [PROPOSAL]
    lines = report.text().splitlines()
    assert lines[1:3] == [PROPOSAL, '    Maps/a.txt, Maps/b.txt, Maps/c.txt and Maps/d.txt'] and len(lines) == 7  # E123 S6: the files it means
    (group,) = report.basis
    assert (group.kind, group.state, group.members, group.open, group.sentence) == ('proposal', 'proposed', tuple('Maps/%s' % p for p, _ in MAPS), (), PROPOSAL)


def test_the_sdk_confirms_or_declines_a_proposal(web, tmp_path):
    report = sent(web, tmp_path, 'Maps')
    proposal = report.view['basis']['grouping']['plan']['proposals'][0]['id']
    confirmed = runs(web).basis(report.run_id, decision=(proposal, 'confirm'))
    assert questions(confirmed) == [(proposal, i, 4) for i in ITEMS]
    (group,) = confirmed.basis  # E123 S6: a confirmed proposal has no served sentence, and the text names no files for it
    assert (group.state, group.open, group.sentence) == ('confirmed', ('coordinate system', 'vertical values', 'vertical datum', 'map unit', 'vertical unit'), '')
    assert PROPOSAL not in confirmed.text() and '    Maps/a.txt' not in confirmed.text()
    report = sent(web, tmp_path, 'Maps2')
    declined = runs(web).basis(report.run_id, decision={'proposal': report.view['basis']['grouping']['plan']['proposals'][0]['id'], 'choice': 'decline'})
    assert len(questions(declined)) == 20 and {n for _, _, n in questions(declined)} == {1}
    answered = runs(web).basis(report.run_id, answers=[('Maps2/a.txt', 'crs', 'EPSG:23031')])
    assert answered.view['basis']['grouping']['resolved']['per_member']['Maps2/a.txt']['crs'] == {'value': 'EPSG:23031', 'class': 'declared', 'source': 'you'}


def test_the_command_line_answers_the_shared_basis_once_and_every_map_is_added(web, tmp_path, monkeypatch, capsys):
    """K2: the grouped items through --share-basis and --basis (in words), the own key through --declare."""
    lines = upload(web, tmp_path, monkeypatch, capsys, folder(tmp_path, MAPS, 'Maps'), '--share-basis', '--basis', 'coordinate system=EPSG:23031',
                   '--basis', 'vertical values=depth', '--basis', 'vertical-datum=MSL', '--basis', 'map unit=m', '--basis', 'units.z=m',
                   '--declare', 'petrel-scattered-data/1:positive=down')
    assert lines == ['Maps - 4 files - Finished. 4 Added, 0 Already here, 0 Needs your decision, 0 Not read, 0 Not supported']
    landed = values(web)
    assert sorted(landed) == ['Maps/%s' % p for p, _ in MAPS]
    assert {p: (v['crs'], v['vertical_domain'], v['units.xy']) for p, v in landed.items()} == {p: ('EPSG:23031', 'depth', 'm') for p in landed}


def test_grids_complete_with_the_basis_options_alone(web, tmp_path, monkeypatch, capsys):
    grids = [('ft.tif', tiff('ft', 1234.5)), ('m.tif', tiff('m', 98.25))]
    lines = upload(web, tmp_path, monkeypatch, capsys, folder(tmp_path, grids, 'Grids'), '--share-basis', '--basis', 'vertical datum=MSL')
    assert lines == ['Grids - 2 files - Finished. 2 Added, 0 Already here, 0 Needs your decision, 0 Not read, 0 Not supported']
    assert values(web) == {'Grids/ft.tif': {'vertical_datum': 'MSL'}, 'Grids/m.tif': {'vertical_datum': 'MSL'}}


def test_an_item_not_asked_once_is_refused_before_anything_is_sent(web, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('OPHIOLITE_ACCESS_KEY', 'oph_api_alice:read,write')
    (tmp_path / 'configuration.json').write_text(json.dumps({'schema': 'ophiolite.read-configuration/1', 'url': ORIGIN, 'project': 'p'}))
    from ophiolite import cli
    monkeypatch.setattr(cli, 'Client', lambda url, project, credential: ophiolite.Client(url, project, credential, web.c))
    with pytest.raises(SystemExit) as stopped:
        cli.entrypoint(['upload', str(folder(tmp_path, MAPS, 'Maps')), '--configuration', str(tmp_path / 'configuration.json'), '--credentials', str(tmp_path / 'none.json'),
                        '--attribution', 'NLOG.NL', '--audience', 'me', '--rights-confirmed', '--basis', 'positive=down'])
    assert stopped.value.code == 1
    assert 'positive is not asked once for a folder; say one of: coordinate system, vertical values' in capsys.readouterr().err
    assert runs(web).list() == []
