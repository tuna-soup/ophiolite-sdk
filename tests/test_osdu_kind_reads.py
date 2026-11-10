"""E168 s1 C2: a curve frame and a typed read say the OSDU kind the gateway served, verbatim, and never fill one in
(charter acceptance 1, the SDK half; the in-process gateway cases are in tests/gateway/test_osdu_kind_reads.py)."""
import json

import pytest

from ophiolite import osdu

WELL_LOG = 'osdu:wks:work-product-component--WellLog:1.5.0'
HORIZON = 'osdu:wks:work-product-component--SeismicHorizon:2.1.0'  # a valid kind the matrix does not give las2/1
FILE_ROWS = json.loads(osdu.MATRIX.read_text(encoding='utf-8'))['rows']
REASON = next(r['none'] for r in FILE_ROWS if r['profile'] == 'points-csv/1')
SERVED = {'kind': {'osdu_kind': WELL_LOG, 'osdu_kind_reason': None},
          'no kind': {'osdu_kind': None, 'osdu_kind_reason': REASON},
          'disagrees with the packaged matrix': {'osdu_kind': HORIZON, 'osdu_kind_reason': None},  # served wins, verbatim
          'before s0': {}}


def expected(case):
    return {'osdu_kind': None, 'osdu_kind_reason': None, **SERVED[case]}


def served_view(case):
    """The SDK's increasing las2/1 view (test_scientific's fixture), each served descriptor carrying SERVED[case]."""
    from ophiolite.client import CurveSet
    from ophiolite.validate import pair
    from test_scientific import FIXTURES
    data = json.loads((FIXTURES / 'increasing.json').read_text())
    models = [pair({**d, **SERVED[case]}, raw.encode()) for d, raw in zip(data['descriptors'], data['normalized_utf8'])]
    return CurveSet([a for a, _ in models], [c for _, c in models], data['artifact_utf8'].encode(), url='https://workspace.example',
                    project='synthetic-project')


@pytest.mark.parametrize('case', SERVED)
def test_a_curve_frame_says_the_kind_the_gateway_served_and_never_fills_one_in(case):
    pytest.importorskip('pandas')
    frame, meta = served_view(case).to_frame()
    assert {'osdu_kind': meta.osdu_kind, 'osdu_kind_reason': meta.osdu_kind_reason} == expected(case)
    assert frame.attrs == {}
    attached = meta.attach(frame).attrs['ophiolite']
    assert {k: attached[k] for k in ('osdu_kind', 'osdu_kind_reason')} == expected(case)


@pytest.mark.parametrize('case', SERVED)
def test_a_typed_read_and_its_attached_frame_say_the_kind_the_gateway_served(case):
    pd = pytest.importorskip('pandas')
    from ophiolite.typed import WellTops
    asset = served_view(case).descriptors[0]
    for descriptor in (asset, asset.model_dump(by_alias=True)):  # the verified model, or a descriptor read from a folder
        tops = WellTops(descriptor, {'context': {'type': 'well-tops'}, 'tops': []}, None)
        assert {'osdu_kind': tops.osdu_kind, 'osdu_kind_reason': tops.osdu_kind_reason} == expected(case)
        frame = tops.to_frame()
        assert frame.attrs == {}  # unchanged unless attached
        frame.attrs['source_names'] = {'a': 'A'}
        assert tops.attach(frame) is frame and frame.attrs == {'source_names': {'a': 'A'}, 'ophiolite': {
            'asset_id': 'sdk-view-fixture', 'revision': asset.revision, 'profile': 'las2/1', **expected(case)}}
        assert isinstance(frame, pd.DataFrame) and list(frame.columns) == ['name', 'md', 'tvd', 'source']
