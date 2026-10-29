"""E119a slice 1 (C3 test 5): a separate Python process that uses only the public SDK (the installed wheel when
OPHIOLITE_TEST_WHEEL_PYTHON names its interpreter) registers a well and its wellbore, uploads two deviation surveys of
that wellbore, is refused a set until it names one version by its label, saves the set, adds a version with the other
survey, and reads both versions back typed (`WellSet`) through `validate.typed_pair`, against the in-process gateway
served over local HTTP. Mutation (run at slice 1): the profile removed from the `validate.py` map refuses the read."""
import json
import os
import subprocess
import sys

from test_in_process_publish import web, shared, app, service  # noqa: F401 (fixtures)
from test_well_imports import TOKEN  # the in-process gateway's fixture credential, passed in the environment
from test_well_path import serve

FRAME = {'crs': 'EPSG:28992', 'wellhead': {'x': 236512.4, 'y': 583104.75}, 'depth_reference': {'name': 'KB', 'elevation': 7.92, 'datum': 'NAP'},
         'north': {'survey_basis': 'grid:EPSG:28992', 'rotation_deg': 0}, 'tie_in': None, 'source': 'NLOG wellbore header'}
CHILD = '''
import json, os, sys
from ophiolite import Client, Credential
from ophiolite.errors import Refused
from ophiolite.well_sets import encode
client = Client(sys.argv[1], 'p', Credential.bearer(os.environ['OPHIOLITE_ACCESS_KEY']))
frame = json.loads(sys.argv[2])
well = client.create_entity('well', 'ZRP-01', authority='nlog', key='ZRP-01-e119as1', command_id='e119as1-well')
bore = client.create_entity('wellbore', 'ZRP-01 main', authority='nlog', key='ZRP-01-main-e119as1', part_of=well,
                            statement='Operator completion report', command_id='e119as1-bore')
surveys = {}
for name, raw in (('Gyro survey', b'md,inclination,azimuth\\n100,0,0\\n200,10,0\\n'), ('MWD survey', b'md,inclination,azimuth\\n100,0,0\\n200,12,0\\n')):
    t = client.upload_data(raw, profile='deviation-csv/1', name=name, filename='survey.csv', declared={'azimuth_reference': 'grid-north'},
                           attribution='Synthetic', audience=[], rights_confirmed=True, command_id='e119as1-' + name.split()[0])
    client.of_entity(t.asset_id, t.revision, bore, command_id='e119as1-tie-' + name.split()[0])
    surveys[name] = t
try:
    client.well_sets.from_list('Zuidwolde wells', [bore.entity_id], frames={bore.entity_id: frame})
    refusal = None
except Refused as refused:
    refusal = str(refused)
sets = client.well_sets
v1 = sets.from_list('Zuidwolde wells', [bore.entity_id], frames={bore.entity_id: frame}, choose={bore.entity_id: 'Gyro survey'})
first = sets.save(v1['label'], v1['members'], attribution='Anna', rights_confirmed=True, command_id='e119as1-set')
v2 = sets.from_list('Zuidwolde wells', [bore.entity_id], frames={bore.entity_id: frame}, choose={bore.entity_id: 'MWD survey'})
second = sets.new_version(first, v2['label'], v2['members'], attribution='Anna', rights_confirmed=True, command_id='e119as1-set-2')
reads = [client.read_data(r.asset_id, r.revision) for r in (first, second)]
print(json.dumps({'refusal': refusal, 'same_set': first.asset_id == second.asset_id, 'distinct': first.revision != second.revision,
                  'classes': [type(r).__name__ for r in reads], 'originals': [r.original == encode(v) for r, v in zip(reads, (v1, v2))],
                  'members': [r.members for r in reads], 'labels': [r.label for r in reads],
                  'chosen': [v1['members'][0]['trajectory'], v2['members'][0]['trajectory']],
                  'surveys': {k: {'asset_id': t.asset_id, 'revision': t.revision} for k, t in surveys.items()},
                  'listed': [i['asset_id'] for i in sets.list()], 'ids': [well.entity_id, bore.entity_id]}))
'''


def test_a_well_set_saved_versioned_and_read_typed_in_a_separate_process(web, tmp_path):
    server = serve(web)
    wheel = os.environ.get('OPHIOLITE_TEST_WHEEL_PYTHON')
    try:
        env = {**os.environ, 'HOME': str(tmp_path), 'OPHIOLITE_ACCESS_KEY': TOKEN}
        if not wheel: env['PYTHONPATH'] = os.pathsep.join(p for p in sys.path if p)
        done = subprocess.run([wheel or sys.executable, '-c', CHILD, 'http://127.0.0.1:%d' % server.server_port, json.dumps(FRAME)],
                              env=env, capture_output=True, text=True, timeout=180, cwd=str(tmp_path))
    finally:
        server.shutdown()
    assert done.returncode == 0, done.stderr
    answer = json.loads(done.stdout)
    assert answer['refusal'] == 'ZRP-01 main has 2 trajectory versions: "Gyro survey", "MWD survey". Name one version by its label in choose.'
    assert [s for s in (*answer['ids'], *(v for t in answer['surveys'].values() for v in t.values())) if s in answer['refusal']] == []
    assert (answer['same_set'], answer['distinct'], answer['classes'], answer['originals']) == (True, True, ['WellSet', 'WellSet'], [True, True])
    assert answer['chosen'] == [answer['surveys']['Gyro survey'], answer['surveys']['MWD survey']]
    well, bore = answer['ids']
    assert answer['members'] == [[{'well': well, 'wellbore': bore, 'trajectory': t, 'frame': FRAME}] for t in answer['chosen']]
    assert answer['labels'] == ['Zuidwolde wells', 'Zuidwolde wells']
    assert len(answer['listed']) == 1


SAME = '''
import json, os, sys
from ophiolite import Client, Credential
from ophiolite.errors import Refused
from ophiolite.well_sets import TRAJECTORY
client = Client(sys.argv[1], 'p', Credential.bearer(os.environ['OPHIOLITE_ACCESS_KEY']))
frame = json.loads(sys.argv[2])
well = client.create_entity('well', 'ZRP-02', authority='nlog', key='ZRP-02-d10', command_id='d10-well')
bores = [client.create_entity('wellbore', name, authority='nlog', key=name + '-d10', part_of=well, statement='Operator completion report',
                              command_id='d10-bore-%d' % n) for n, name in enumerate(('ZRP-02 main', 'ZRP-02 side'))]
uploads = []
for n, (bore, angle) in enumerate(((bores[0], 10), (bores[0], 12), (bores[1], 14))):
    t = client.upload_data(b'md,inclination,azimuth\\n100,0,0\\n200,%d,0\\n' % angle, profile='deviation-csv/1', name='Final survey', filename='survey.csv',
                           declared={'azimuth_reference': 'grid-north'}, attribution='Synthetic', audience=[], rights_confirmed=True, command_id='d10-up-%d' % n)
    client.of_entity(t.asset_id, t.revision, bore, command_id='d10-tie-%d' % n)
    uploads.append({'asset_id': t.asset_id, 'revision': t.revision})
main = bores[0].entity_id

def refused(choose):
    try:
        client.well_sets.from_list('Zuidwolde wells', [main], frames={main: frame}, choose={main: choose})
    except Refused as error:
        return str(error)

item = [i for i in client.data(bores[0], profile=TRAJECTORY) if (i['asset_id'], i['revision']) == tuple(uploads[1].values())][0]
exact = {'asset_id': item['asset_id'], 'revision': item['revision']}  # the version itself, as `client.data` lists it
doc = client.well_sets.from_list('Zuidwolde wells', [main], frames={main: frame}, choose={main: exact})
saved = client.well_sets.save(doc['label'], doc['members'], attribution='Anna', rights_confirmed=True, command_id='d10-set')
print(json.dumps({'label': refused('Final survey'), 'other_bore': refused(uploads[2]), 'extra_key': refused({**exact, 'name': 'Final survey'}),
                  'saved': client.read_data(saved.asset_id, saved.revision).members[0]['trajectory'], 'uploads': uploads}))
'''


def test_two_versions_under_one_label_are_chosen_by_the_version_itself_in_a_separate_process(web, tmp_path):
    """D-10, through the public SDK (the installed wheel when OPHIOLITE_TEST_WHEEL_PYTHON names it) against the in-process
    gateway: ZRP-02 main has two versions labelled "Final survey". The label is refused; the version itself, a mapping of
    exactly asset_id and revision, is chosen and saved; another wellbore's version and a mapping with another key are
    refused, naming no identifier. Mutation (run at the lane): compare the mapping by label only -> the choice is refused
    as "more than one ... named" -> red."""
    server = serve(web)
    wheel = os.environ.get('OPHIOLITE_TEST_WHEEL_PYTHON')
    try:
        env = {**os.environ, 'HOME': str(tmp_path), 'OPHIOLITE_ACCESS_KEY': TOKEN}
        if not wheel: env['PYTHONPATH'] = os.pathsep.join(p for p in sys.path if p)
        done = subprocess.run([wheel or sys.executable, '-c', SAME, 'http://127.0.0.1:%d' % server.server_port, json.dumps(FRAME)],
                              env=env, capture_output=True, text=True, timeout=180, cwd=str(tmp_path))
    finally:
        server.shutdown()
    assert done.returncode == 0, done.stderr
    answer = json.loads(done.stdout)
    assert answer['label'] == ('ZRP-02 main has more than one trajectory version named "Final survey" ("Final survey", "Final survey"). '
                               'Name one by passing the version itself in choose.')
    assert answer['saved'] == answer['uploads'][1]
    assert answer['other_bore'] == 'ZRP-02 main has no trajectory version you can read matching the one named.'
    assert answer['extra_key'] == 'ZRP-02 main: choose names a trajectory version by its label, or by a mapping of exactly asset_id and revision.'
    ids = [v for t in answer['uploads'] for v in t.values()]
    assert [i for i in ids if any(i in answer[k] for k in ('label', 'other_bore', 'extra_key'))] == []
