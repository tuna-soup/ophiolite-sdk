"""E137 s8 C1 (strategy D-2'..D-6, R1-1..R1-13): every kind an OpendTect survey archive holds has a row, and the
listing audit names each file's kind from its path alone or says it cannot. Synthetic member names only (D-4); the
live variant reads OSD's listings from OSD_LISTINGS_DIR and records counts in the Validation Record only."""
import os
import re
from pathlib import Path

import pytest

from ophiolite import starter_kinds as sk

PICKSETS = "OpendTect's Python lists a survey's picksets but cannot read their points, so a starter pack cannot carry them."
LISTINGS = 5  # OSD's five archive listings (E137 charter)

# (member, kind, status): one synthetic member per rule, literal expectations (R1-8)
CASES = [
    ('Syn/.survey', 'survey-definition', 'not data'),
    ('Syn/.omf', 'survey-definition', 'not data'),
    ('Syn/.hiddenthing', 'hidden', 'not data'),
    ('Syn/Seismics/SynCube.cbvs', 'seismic-3d', 'written'),
    ('Syn/Seismics/SynLines/SynLine_1.cbvs', 'seismic-2d', 'written'),
    ('Syn/Seismics/SynCube.par', 'object-parameters', 'not data'),
    ('Syn/Seismics/SynWavelet.wvlt', 'wavelets', 'refused'),
    ('Syn/Seismics/.omf', 'survey-definition', 'not data'),
    ('Syn/Geometry/SynLine.geom', 'line-geometry', 'written'),
    ('Syn/Surfaces/SynH.hor', 'horizons-3d', 'written'),
    ('Syn/Surfaces/SynH2.2dh', 'horizons-2d', 'written'),
    ('Syn/Surfaces/SynF.fss', 'faults', 'written'),
    ('Syn/Surfaces/SynF.flt', 'faults', 'written'),
    ('Syn/Surfaces/SynHC/SynHC.3dhc', 'horizon-cubes', 'refused'),
    ('Syn/Surfaces/SynB.body', 'bodies', 'refused'),
    ('Syn/WellInfo/SynW.well', 'wells', 'written'),
    ('Syn/WellInfo/SynW^1.wll', 'logs', 'written'),
    ('Syn/WellInfo/SynW.wlm', 'markers', 'written'),
    ('Syn/WellInfo/SynW.wlt', 'survey-time-depth', 'refused'),
    ('Syn/WellInfo/SynW.pwell', 'well-other', 'refused'),
    ('Syn/Locations/SynP.pck', 'picksets', 'refused'),
    ('Syn/Locations/SynR.rdl', 'random-lines', 'refused'),
    ('Syn/Attribs/SynA.attr', 'attribute-sets', 'refused'),
    ('Syn/Models/SynM.sgd', 'models', 'refused'),
    ('Syn/Proc/SynJob.par', 'processing', 'refused'),
    ('Syn/Misc/SynSel.objsel', 'sessions', 'not data'),
    ('Syn/RawFolder/SynReport.pdf', 'documents', 'not data'),
    ('Syn/RawFolder/SynOutline.shp', 'map-overlays', 'not data'),
    ('Syn/RawFolder/SynWell/SynW.las', 'raw-sources', 'not data'),
    ('Syn/RawFolder/SynWell/SynCS.txt', 'raw-sources', 'not data'),
]


@pytest.mark.parametrize('member,kind,status', CASES)
def test_each_member_maps_to_its_kind_and_status(member, kind, status):
    assert sk.archive_kind(member) == kind
    assert sk.ARCHIVE_BY_KEY[kind].status == status


def test_a_raw_text_table_is_a_checkshot_table_only_when_declared():
    member = 'Syn/RawFolder/SynWell/SynCS.txt'
    assert sk.archive_kind(member, declared={member}) == 'checkshot-tables'
    assert sk.ARCHIVE_BY_KEY['checkshot-tables'].route == 'time-depth'
    assert sk.archive_kind('Syn/RawFolder/SynWell/Other.txt', declared={member}) == 'raw-sources'


@pytest.mark.parametrize('member', ['Syn/Surfaces/SynX.unknownext', 'Syn/Seismics/SynLines/Deeper/SynLine.cbvs',
                                    'Syn/RawFolder/SynThing.unknownext', 'Syn/Locations/SynP.pck/'])
def test_content_the_path_does_not_establish_is_unresolved(member):
    assert sk.archive_kind(member) == sk.UNRESOLVED


def test_written_rows_name_pack_kinds_and_refused_rows_a_sentence():
    for row in sk.ARCHIVE:
        assert row.status in ('written', 'refused', 'waits', 'not data'), row
        if row.status == 'written': assert sk.known(row.route), row
        else: assert row.route.endswith('.') or row.route.startswith('not part of a starter pack: '), row
    assert sk.ARCHIVE_BY_KEY['picksets'].route == PICKSETS


def test_the_refusals_are_plain_sentences_of_their_own():
    assert sk.refused('picksets') == PICKSETS
    assert sk.refused('polygons') == "OpendTect's Python lists a survey's polygons but cannot read their points, so a starter pack cannot carry them."
    assert sk.refused('random-lines') == "OpendTect's Python cannot read a survey's random lines, so a starter pack cannot carry them."
    assert sk.refused('horizons-2d') is None and sk.refused('horizons') is None and sk.refused(3) is None
    assert not any(sk.known(k) for k in sk.REFUSED)


LINE = re.compile(r'\s*(\d+)\s+\d{4}-\d\d-\d\d\s+\d\d:\d\d\s+(.+?)\s*$')
HEADS = re.compile(r'\s*(Archive:|Length\s+Date|-+\s+-+|-+\s+-+\s*$|\d+\s+\d+ files?\s*$)')


def listing_members(path):
    """The file members of an `unzip -l` listing; a line that is neither a member, a directory nor a header fails."""
    files = []
    for line in Path(path).read_text(encoding='utf-8', errors='replace').splitlines():
        if not line.strip() or HEADS.match(line): continue
        m = LINE.match(line)
        assert m, 'unparsed listing line in %s' % Path(path).name
        if m.group(2).endswith('/'): continue
        files.append(m.group(2))
    return files


SYNTHETIC = """Archive:  Syn.zip
  Length      Date    Time    Name
---------  ---------- -----   ----
        0  2026-01-01 00:00   Syn/
      120  2026-01-01 00:00   Syn/.survey
        0  2026-01-01 00:00   Syn/Seismics/
     4096  2026-01-01 00:00   Syn/Seismics/Syn Cube.cbvs
     2048  2026-01-01 00:00   Syn/Seismics/Syn Lines/Syn Line 1.cbvs
      512  2026-01-01 00:00   Syn/Locations/Syn P.pck
---------                     -------
     6776                     5 files
"""


def listings(tmp_path):
    """OSD_LISTINGS_DIR's listings when set (live, VR only), else five synthetic ones of the same form."""
    if os.environ.get('OSD_LISTINGS_DIR'): return Path(os.environ['OSD_LISTINGS_DIR'])
    for n in range(LISTINGS): (tmp_path / ('syn-%d-listing.txt' % n)).write_text(SYNTHETIC, encoding='utf-8')
    return tmp_path


def test_a_listing_is_read_whole_names_with_spaces_and_directories_skipped(tmp_path):
    (tmp_path / 'a-listing.txt').write_text(SYNTHETIC, encoding='utf-8')
    assert listing_members(tmp_path / 'a-listing.txt') == ['Syn/.survey', 'Syn/Seismics/Syn Cube.cbvs',
                                                          'Syn/Seismics/Syn Lines/Syn Line 1.cbvs', 'Syn/Locations/Syn P.pck']
    (tmp_path / 'b-listing.txt').write_text(SYNTHETIC + 'garbled line\n', encoding='utf-8')
    with pytest.raises(AssertionError, match='unparsed listing line'): listing_members(tmp_path / 'b-listing.txt')


def test_every_member_of_the_osd_listings_has_a_kind(tmp_path):
    paths = sorted(listings(tmp_path).glob('*-listing.txt'))
    assert len(paths) == LISTINGS
    for p in paths:
        members = listing_members(p)
        assert members, p.name
        unresolved = [m for m in members if sk.archive_kind(m) == sk.UNRESOLVED]
        assert unresolved == [], '%s: %d unresolved' % (p.name, len(unresolved))
