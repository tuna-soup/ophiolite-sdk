"""E127 s1a C5 (A12, H10, H11): the report lists the files a catalogue manifest row lists, each after its manifest, in
the CSV and, when not added, in the text; every file keeps its own line and instruction. Other outputs (a conversion's,
a package's) are not rows: a converted run's and a package run's CSV, text and `ok` equal what the SDK on main gave
(frozen before the change). Mutations (recorded in the Validation Record): the zip kept in `text()`; `rows` without
catalogue outputs; outputs added for every `output`, not only `listed-`."""
import copy

from ophiolite.upload_runs import Report

R2 = "This file's bytes do not match the checksum the manifest states. Nothing was added."
COUNTS = {'waiting': 0, 'reading': 0, 'added': 0, 'already_here': 0, 'needs_decision': 0, 'not_read': 0, 'not_supported': 0, 'cancelled': 0,
          'needs_procedure': 0, 'converting': 0, 'converted': 0}


def view(items, label='Finished with files not added', folder='catalogue', **counts):
    return {'run_id': 'f' * 64, 'state': 'closed', 'label': label, 'folder_name': folder, 'files': len(items), 'settings': {},
            'counts': {**COUNTS, **counts}, 'items': items}


def item(path, state, sentence=None, asset=None, kind='', role='primary', outputs=None, read=None):
    return {'path': path, 'state': state, 'sentence': sentence, 'asset_id': asset, 'kind': kind, 'role': role, 'read': read,
            **({'outputs': outputs} if outputs is not None else {})}


def output(n, outcome, sentence=None, asset=None, kind='Well log (LAS)'):
    return {'output': 'listed-%d' % n, 'role': 'listed-%d' % n, 'label': 'Listed file %d' % n, 'kind': kind if outcome in ('added', 'already-here') else '',
            'outcome': outcome, 'asset_id': asset, 'revision': 'r' if asset else None, 'line': 'SYNTH A-1: 3 curves' if asset else None, 'sentence': sentence}


MANIFEST = item('catalogue/manifest-two-wells.json', 'not-read', '1 of the 2 files this manifest lists were not added.',
                outputs=[output(1, 'added', asset='a' * 64), output(2, 'not-landed', R2)])
FAILED = item('catalogue/bad.las', 'not-read', 'This file could not be read as Well log (LAS).')
PROCEDURE = item('catalogue/survey.dat', 'needs-procedure', 'Can be read by Ada on your computer.')


def test_a_manifests_files_follow_it_and_each_file_keeps_its_own_line_and_instruction():
    report = Report(view([MANIFEST, FAILED, PROCEDURE], not_read=2, needs_procedure=1))
    assert report.rows() == [
        {'path': 'catalogue/manifest-two-wells.json', 'result': 'Not read', 'kind': '', 'read': '', 'reason': '1 of the 2 files this manifest lists were not added.', 'asset': ''},
        {'path': 'catalogue/manifest-two-wells.json: Listed file 1', 'result': 'Added', 'kind': 'Well log (LAS)', 'read': 'SYNTH A-1: 3 curves', 'reason': '', 'asset': 'a' * 64},
        {'path': 'catalogue/manifest-two-wells.json: Listed file 2', 'result': 'Not added', 'kind': '', 'read': '', 'reason': R2, 'asset': ''},
        {'path': 'catalogue/bad.las', 'result': 'Not read', 'kind': '', 'read': '', 'reason': 'This file could not be read as Well log (LAS).', 'asset': ''},
        {'path': 'catalogue/survey.dat', 'result': 'Can be read on your computer', 'kind': '', 'read': '', 'reason': 'Can be read by Ada on your computer.', 'asset': ''}]
    assert report.text().split('\n')[1:] == [
        '  catalogue/manifest-two-wells.json: Not read - 1 of the 2 files this manifest lists were not added.',
        '  catalogue/manifest-two-wells.json: Listed file 2: Not added - ' + R2,
        '  catalogue/bad.las: Not read - This file could not be read as Well log (LAS).',
        '  catalogue/survey.dat: Can be read on your computer - Can be read by Ada on your computer.',
        '    To read it on this computer: ophiolite intake read %s survey.dat' % ('f' * 64)]
    assert not report.ok


def test_a_manifest_whose_files_were_all_added_is_ok_and_lists_no_line():
    added = item('catalogue/manifest-two-wells.json', 'added', outputs=[output(1, 'added', asset='a' * 64), output(2, 'already-here', asset='b' * 64)])
    report = Report(view([added], label='Finished', added=1))
    assert report.ok and report.text().split('\n')[1:] == []
    assert [(r['path'], r['result'], r['asset']) for r in report.rows()] == [('catalogue/manifest-two-wells.json', 'Added', ''),
        ('catalogue/manifest-two-wells.json: Listed file 1', 'Added', 'a' * 64), ('catalogue/manifest-two-wells.json: Listed file 2', 'Already here', 'b' * 64)]


# --- frozen on main (before E127 s1a): a converted run and a package run --------------------------------------------

CONVERTED = view([item('logs/survey.dat', 'converted', None, kind='Raw survey', outputs=[
    {'output': None, 'role': 'gr', 'label': 'Gamma ray', 'kind': 'Well log (LAS)', 'outcome': 'added', 'asset_id': 'c' * 64, 'revision': 'r', 'line': 'GR', 'sentence': None},
    {'output': None, 'role': 'rhob', 'label': 'Density', 'kind': 'Well log (LAS)', 'outcome': 'cancelled', 'asset_id': None, 'revision': None, 'line': None, 'sentence': 'Stopped.'}])],
    label='Finished', folder='logs', converted=1)
PACKAGE = view([item('model/field.epc', 'added', None, kind='RESQML package', outputs=[
    {'output': 'u1/obj_Grid2dRepresentation', 'role': 'u1/obj_Grid2dRepresentation', 'label': 'Top surface', 'kind': 'Surface', 'outcome': 'added',
     'asset_id': 'd' * 64, 'revision': 'r', 'line': None, 'sentence': 'Top surface — added'},
    {'output': 'u2/obj_WellboreTrajectoryRepresentation', 'role': 'u2/obj_WellboreTrajectoryRepresentation', 'label': 'Well path', 'kind': 'Trajectory',
     'outcome': 'cancelled', 'asset_id': None, 'revision': None, 'line': None, 'sentence': None},
    {'output': 'u3/obj_PolylineSetRepresentation', 'role': 'u3/obj_PolylineSetRepresentation', 'label': 'Faults', 'kind': 'Fault sticks',
     'outcome': 'expired', 'asset_id': None, 'revision': None, 'line': None, 'sentence': None}]),
    item('model/field.h5', 'added', None, role='hdf5')], label='Finished', folder='model', added=2)
FROZEN = {  # printed by origin/main's `ophiolite/upload_runs.py` (264e60551) for these views, before this change
    'converted': ('path,result,kind,read,reason,asset\nlogs/survey.dat,Read on your computer,Raw survey,,,\n',
                  'logs - 1 files - Finished. 0 Added, 0 Already here, 0 Needs your decision, 0 Not read, 0 Not supported, 1 Read on your computer\n'
                  '  logs/survey.dat: Read on your computer', True),
    'package': ('path,result,kind,read,reason,asset\nmodel/field.epc,Added,RESQML package,,,\nmodel/field.h5,Added,,,,\n',
                'model - 2 files - Finished. 2 Added, 0 Already here, 0 Needs your decision, 0 Not read, 0 Not supported', True)}


def test_a_converted_and_a_package_run_report_as_on_main():
    import csv
    import io
    for name, given in (('converted', CONVERTED), ('package', PACKAGE)):
        report = Report(copy.deepcopy(given))
        out = io.StringIO()
        writer = csv.DictWriter(out, ('path', 'result', 'kind', 'read', 'reason', 'asset'), lineterminator='\n')
        writer.writeheader(); writer.writerows(report.rows())
        assert (out.getvalue(), report.text(), report.ok) == FROZEN[name], name
