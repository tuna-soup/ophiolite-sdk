"""E137 s6b C5: the live driver's packs P3 and P4 carry every 2D horizon of the survey, and the OpendTect import's 2D
horizon sentences are classes (`conformance/roundtrip/live_packs.py`)."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('roundtrip_live_packs_h2d_test', ROOT / 'conformance/roundtrip/live_packs.py')
lp = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = lp
spec.loader.exec_module(lp)


def test_p3_and_p4_name_every_2d_horizon_under_horizons_and_its_sentences_have_classes():
    """E137 s6b C5. Catches: a 2D horizon dropped from the contents or named alone; the import step, the missing lines
    or a differing read-back printed as `unclassified`."""
    assert all('horizons-2d' in lp.PACKS[p]['kinds'] and 'Geometry' in lp.PACKS[p]['folders'] for p in ('P3', 'P4'))
    assert lp.contents_of((), {'faults': 'SynF', 'horizons-2d': ['SynA', 'SynB']}) == [
        {'kind': 'horizons', 'ids': ['SynA', 'SynB']}, {'kind': 'faults', 'ids': ['SynF']}]
    assert lp.contents_of((), {'horizons': 'Top', 'horizons-2d': ['SynA']}) == [{'kind': 'horizons', 'ids': ['Top', 'SynA']}]
    assert lp.classify('Import opendtect-import/SynA.txt in OpendTect (Survey > Import > Horizons > ASCII 2D > Single 2D Horizon ...: '
                       'Horizon is in Time). Then run this import again.') == '2D horizon imported by hand'
    assert lp.classify('The survey has no 2D line geometry for 2 of the lines of the 2D horizon “SynA” (the first: “L1”); import those '
                       'lines first.') == '2D horizon without its lines'
    assert lp.classify('The 2D horizon “SynA” in the survey is not files/horizons2d/SynA/L1.csv: trace 7 z differs.') == 'opendtect differs'
