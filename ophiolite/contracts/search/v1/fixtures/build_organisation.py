"""E145 s0 C2 (D7): the non-id facts of the frozen organisation `org-e145` (organisation.json).

The builder writes what the seeder (`services/project_gateway/tests/e145_seed.py`) lands through the real routes: the
people, projects and wells, the bytes of every LAS file and table file (as their builder inputs: curves, samples, rows),
each version's name, well, kind, command and landing time. The asset ids and revisions in organisation.json are the ones the
real landing returned; this builder never computes them for the committed file. It searches command ids offline (`_tied`)
only so that the five caliper logs of Q2 land with the adversarial id order of the strategy (§4).

    python build_organisation.py   # prints the facts as JSON (organisation.json without `asset` and `revision`)
"""
import calendar
import hashlib
import json
import time

ORGANIZATION = {'id': 'org-e145', 'name': 'E145 organisation', 'owner': 'alice'}
PEOPLE = {'alice': 'Alice', 'bob': 'Bob'}
START = '2026-11-01T08:00:00Z'  # project A's first landing; B one day later, C two days later; one minute per landing
STEP = 60
PROJECTS = [
    {'id': 'proj-a', 'name': 'Project A', 'owner': 'alice', 'archived': False, 'crs': 'EPSG:23031', 'day': 0},
    {'id': 'proj-b', 'name': 'Project B', 'owner': 'bob', 'archived': False, 'crs': 'EPSG:4326', 'day': 1},
    {'id': 'proj-c', 'name': 'Project C', 'owner': 'alice', 'archived': True, 'crs': 'EPSG:32631', 'day': 2},
]
# (name, x, y): literals in the project's system; W01/W02 and W15/W16 close together, every other pair at least 5 km apart;
# B's as (longitude, latitude): W12 on the corner of Q7's box, W13 inside it, W14 the swap of a point inside it.
WELLS = {
    'proj-a': [('34/10-A-1', 470000.0, 6790000.0), ('34/10-A-2', 471200.0, 6790800.0), ('34/10-A-3', 500000.0, 6820000.0),
               ('34/10-A-4', 485000.0, 6775000.0), ('34/10-A-5', 495000.0, 6760000.0), ('34/10-A-6', 507000.0, 6790000.0),
               ('34/10-A-7', 515000.0, 6805000.0), ('34/10-A-8', 522000.0, 6835000.0)],
    'proj-b': [('35/11-B-1', 5.5, 53.5), ('35/11-B-2', 6.5, 54.0), ('35/11-B-3', 1.0, 49.0), ('35/11-B-4', 4.0, 52.0),
               ('35/11-B-5', 3.0, 51.0), ('35/11-B-6', 51.0, 3.0)],
    'proj-c': [('31/2-C-1', 450000.0, 6740000.0), ('31/2-C-2', 451000.0, 6740600.0), ('31/2-C-3', 465000.0, 6750000.0),
               ('31/2-C-4', 475000.0, 6733000.0), ('31/2-C-5', 440000.0, 6760000.0), ('31/2-C-6', 482000.0, 6766000.0)],
}
ALIAS = {'well': '34/10-A-3', 'as_written': 'NO 34/10-A-3'}  # ADR 0025: a typed alias of W03's wellbore, through well-names/accept
CURVES = {'gamma ray': [['GR', 'gAPI']], 'caliper': [['CALI', 'in'], ['BS', 'in']], 'caliper one': [['CALI', 'in']],
          'density': [['RHOB', 'g/cm3']], 'sonic': [['DT', 'us/ft']], 'resistivity': [['RDEP', 'ohmm']], 'neutron': [['NPHI', 'v/v']]}
OBSOLETE = [['GR', 'gAPI'], ['OBSOLETE', 'gAPI']]  # the superseded revisions' curves: "obsolete" is in no head's text
# Per well, the logs other than gamma ray (each a `las2/1` version); the gamma-ray count per well; tops for every well;
# deviation for every well but W08. A caliper log of B has one curve fewer: viewed by alice, B's text says "Uploaded by a
# project member" (two words more than "Uploaded by you"), so the five calipers have equal word counts and tie on score.
OTHERS = {
    'proj-a': {'34/10-A-1': ['caliper log a', 'caliper log a'], '34/10-A-2': ['caliper log b'], '34/10-A-3': ['density log'],
               '34/10-A-4': ['density log'], '34/10-A-5': ['density log'], '34/10-A-6': ['density log'], '34/10-A-7': ['density log'],
               '34/10-A-8': ['density log']},
    'proj-b': {'35/11-B-1': ['caliper log a', 'density log'], '35/11-B-2': ['sonic log', 'resistivity log'],
               '35/11-B-3': ['sonic log', 'resistivity log'], '35/11-B-4': ['sonic log', 'resistivity log'],
               '35/11-B-5': ['sonic log', 'resistivity log', 'neutron log', 'density log'],
               '35/11-B-6': ['sonic log', 'resistivity log', 'neutron log'], None: ['density log']},
    'proj-c': {'31/2-C-1': ['caliper log a'], '31/2-C-2': ['density log'], '31/2-C-3': ['density log'], '31/2-C-4': ['density log'],
               '31/2-C-5': ['sonic log', 'density log'], '31/2-C-6': ['sonic log', 'density log']},
}
GAMMA = {'proj-a': {w: 7 for w, *_ in WELLS['proj-a']},
         'proj-b': {'35/11-B-1': 4, '35/11-B-2': 4, '35/11-B-3': 4, '35/11-B-4': 4, '35/11-B-5': 2, '35/11-B-6': 2},
         'proj-c': {w: 2 for w, *_ in WELLS['proj-c']}}
NO_DEVIATION = {'34/10-A-8'}
SUPERSEDED = [('proj-a', '34/10-A-%d' % n, 'gamma ray run 1') for n in (1, 2, 3, 4)]  # each landed twice: old revision, then head
LETTER = {'proj-a': 'A', 'proj-b': 'B', 'proj-c': 'C'}


def instant(epoch):
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(epoch))


def epoch(text):
    return calendar.timegm(time.strptime(text, '%Y-%m-%dT%H:%M:%SZ'))


def las(curves, well, n):
    """The bytes of one LAS 2.0 file: three depth samples and one value per curve, all from the version's number n."""
    lines = ['~Version', ' VERS. 2.0:', ' WRAP. NO:', '~Well', ' STRT.M 1000:', ' STOP.M 1002:', ' STEP.M 1:', ' NULL. -999.25:',
             ' WELL. %s:' % (well or ''), '~Curve', ' DEPT.M:'] + [' %s.%s:' % (m, u) for m, u in curves] + ['~A']
    for d in range(3):
        lines.append(' '.join(['%d' % (1000 + d)] + ['%d.%d' % (n + 10 * c, d) for c in range(len(curves))]))
    return ('\n'.join(lines) + '\n').encode()


def tops(project, wells):
    rows = ['Well,Formation,Top MD (m)']
    for i, well in enumerate(wells):
        rows += ['%s,Top Brent,%d' % (well, 2000 + 10 * i), '%s,Base Brent,%d' % (well, 2100 + 10 * i)]
    return '\n'.join(rows) + '\n'


def deviation(i):
    return 'AH depth (m),Deviation (deg),Azimuth (deg),TVD (m)\n0,0,0,0\n500,%d.5,%d,499.8\n1000,%d.5,%d,998.9\n' % (i, 10 * i, i + 1, 10 * i + 5)


def upload_id(project, owner, command):
    """The upload id formula (las_uploads.py, D7), used ONLY to choose the calipers' command ids offline."""
    from asset_connectors.sources import canonical
    return hashlib.sha256(canonical(['upload', project, owner, command]).encode()).hexdigest()


def _tied():
    """Command numbers of the five calipers: B's id lowest of all five, C's between B's and A's low "a", A's "b" lowest of
    A's three, and A's two "a" logs high and low. The first numbers from 901 that satisfy it, searched in that order."""
    ids = {}
    def first(project, owner, start, ok):
        n = start
        while not ok(upload_id(project, owner, 'e145-%s-%03d' % (project, n))): n += 1
        return n, upload_id(project, owner, 'e145-%s-%03d' % (project, n))
    ids['a1'] = first('proj-a', 'alice', 901, lambda i: True)
    ids['a2'] = first('proj-a', 'alice', ids['a1'][0] + 1, lambda i: True)
    low = min(ids['a1'][1], ids['a2'][1])
    ids['b'] = first('proj-a', 'alice', ids['a2'][0] + 1, lambda i: i < low)
    ids['B'] = first('proj-b', 'bob', 901, lambda i: i < ids['b'][1])
    ids['C'] = first('proj-c', 'alice', 901, lambda i: ids['B'][1] < i < low)
    return {k: v[0] for k, v in ids.items()}


def facts():
    """organisation.json without the landed ids (`asset`, `revision`)."""
    tied = _tied()
    caliper = {('proj-a', '34/10-A-1', 0): tied['a1'], ('proj-a', '34/10-A-1', 1): tied['a2'], ('proj-a', '34/10-A-2', 0): tied['b'],
               ('proj-b', '35/11-B-1', 0): tied['B'], ('proj-c', '31/2-C-1', 0): tied['C']}
    projects, wells, files, versions, superseded = [], [], {}, [], []
    for p in PROJECTS:
        pid, owner = p['id'], p['owner']
        base = epoch(START) + 86400 * p['day']
        projects.append({k: p[k] for k in ('id', 'name', 'owner', 'archived', 'crs')})
        names = [w for w, *_ in WELLS[pid]]
        wells += [{'project': pid, 'name': w, 'wellbore': w, 'x': x, 'y': y, 'crs': p['crs']} for w, x, y in WELLS[pid]]
        minute, number = 0, 0

        def at():
            nonlocal minute
            minute += 1
            return instant(base + STEP * minute)
        for well in names + ([None] if None in OTHERS[pid] else []):
            logs = [('gamma ray run %d' % k, 'gamma ray') for k in range(1, GAMMA[pid].get(well, 0) + 1)]
            logs += [(name, ('caliper one' if pid == 'proj-b' else 'caliper') if name.startswith('caliper') else name.split()[0]) for name in OTHERS[pid][well]]
            seen = 0
            for name, kind in logs:
                if name.startswith('caliper'):
                    n = caliper[(pid, well, seen)]; seen += 1
                else:
                    number += 1; n = number
                header = ALIAS['as_written'] if (pid, well, name) == ('proj-a', ALIAS['well'], 'density log') else well
                versions.append({'project': pid, 'well': well, 'kind': 'las2/1', 'name': name, 'landing': 'las-uploads/upload',
                                 'command': 'e145-%s-%03d' % (pid, n), 'header': header, 'curves': CURVES[kind], 'n': n,
                                 'published_at': at(), 'published_by': owner})
        stem = 'tops-%s' % LETTER[pid].lower()
        files[stem + '.csv'] = tops(pid, names)
        when = at()
        for well in names:
            versions.append({'project': pid, 'well': well, 'kind': 'well-tops-csv/1', 'name': '%s - %s' % (stem, well), 'landing': 'table-imports/well-tops',
                             'command': 'e145-%s-tops' % pid, 'file': stem + '.csv', 'published_at': when, 'published_by': owner})
        for i, well in enumerate(names, 1):
            if well in NO_DEVIATION: continue
            stem = 'deviation %s-%d' % (LETTER[pid], i)
            files[stem + '.csv'] = deviation(i)
            versions.append({'project': pid, 'well': well, 'kind': 'deviation-csv/1', 'name': '%s - %s' % (stem, well), 'landing': 'table-imports/deviation-survey',
                             'command': 'e145-%s-deviation-%d' % (pid, i), 'file': stem + '.csv', 'published_at': at(), 'published_by': owner})
        for project, well, name in SUPERSEDED:
            if project != pid: continue
            head = next(v for v in versions if (v['project'], v['well'], v['name']) == (project, well, name))
            superseded.append({'project': pid, 'well': well, 'name': name, 'command': head['command'], 'curves': OBSOLETE, 'n': head['n'],
                               'published_at': head['published_at'], 'published_by': owner})
            head['command'] = head['command'] + '-v2'  # the head is the second upload, appended to the first's asset
            head['published_at'] = at()
    return {'schema': 'ophiolite.fixture/search/organisation/1', 'organization': ORGANIZATION, 'people': PEOPLE, 'start': START,
            'projects': projects, 'wells': wells, 'alias': ALIAS, 'files': files, 'versions': versions, 'superseded': superseded}


if __name__ == '__main__':
    print(json.dumps(facts(), indent=1))
