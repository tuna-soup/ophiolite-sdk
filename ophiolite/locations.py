"""E29: where wells are. Client.wells() lists the wells you may read with the location the server chose from the
newest source you may read; Client.extent() is their extent in one CRS. Coordinates are never converted here: a
location is in the CRS you asked the server for, or as stored when you asked for none, and to_geojson() needs a
fetch in OGC:CRS84 (GeoJSON's CRS) rather than converting locally.
"""
from .errors import Refused, VerificationFailed

CRSS = ('OGC:CRS84', 'EPSG:4326', 'EPSG:3857', 'EPSG:28992', 'EPSG:32631')


class Well:
    """One well and, when a source you may read locates it, its location (x, y, crs, source, provenance)."""
    def __init__(self, document):
        self.document = document
        self.entity_id, self.name, self.location = document['entity_id'], document['name'], document.get('location')

    def __repr__(self):
        where = 'unlocated' if not self.location else 'unconverted' if self.location['x'] is None else '%s, %s %s' % (self.location['x'], self.location['y'], self.location['crs'])
        return 'Well(%r, %s)' % (self.name, where)


class Wells(list):
    """The wells of one fetch, with the CRS they were fetched in (None: as stored) and how many could not be converted."""
    def __init__(self, wells, crs, untransformed):
        super().__init__(wells)
        self.crs, self.untransformed = crs, untransformed

    def to_frame(self):
        """One row per well: its name and location (x, y and crs as fetched; missing when it has none)."""
        try: import pandas as pd
        except ImportError: raise Refused('Install ophiolite[pandas] for DataFrames.') from None
        rows = []
        for w in self:
            loc = w.location or {}
            source = loc.get('source') or {}
            rows.append({'name': w.name, 'entity_id': w.entity_id, 'x': loc.get('x'), 'y': loc.get('y'), 'crs': loc.get('crs'),
                         'source_asset_id': source.get('asset_id'), 'source_revision': source.get('revision'), 'source_row': source.get('row'),
                         'ambiguous': loc.get('ambiguous', False) if loc else None})
        frame = pd.DataFrame(rows, columns=['name', 'entity_id', 'x', 'y', 'crs', 'source_asset_id', 'source_revision', 'source_row', 'ambiguous'])
        frame[['x', 'y']] = frame[['x', 'y']].astype('Float64')
        return frame

    def to_geojson(self):
        """A GeoJSON FeatureCollection (well names in properties). GeoJSON is longitude, latitude in CRS84, so this
        needs the wells fetched with crs='OGC:CRS84'; nothing is converted locally."""
        if self.crs != 'OGC:CRS84':
            raise Refused('These wells were fetched %s; fetch them again with wells(..., crs=\'OGC:CRS84\') for GeoJSON.'
                          % ('as stored' if self.crs is None else 'in ' + self.crs))
        features = []
        for w in self:
            loc = w.location
            geometry = {'type': 'Point', 'coordinates': [loc['x'], loc['y']]} if loc and loc['x'] is not None else None
            features.append({'type': 'Feature', 'id': w.entity_id, 'geometry': geometry, 'properties': {'name': w.name, 'entity_id': w.entity_id}})
        return {'type': 'FeatureCollection', 'features': features}


class LocationClient:
    def wells(self, bbox=None, bbox_crs=None, crs=None, limit=None):
        """The wells you may read, each with its location when a source you may read locates it. With `bbox`
        ([minx, miny, maxx, maxy], which needs `bbox_crs`), only the wells located inside it. `crs` converts each
        location on the server (omitted: as stored). `limit` stops after that many wells."""
        if bbox is not None and bbox_crs is None: raise Refused('Give bbox_crs with bbox: the box is read in no CRS by default.')
        for name, value in (('bbox_crs', bbox_crs), ('crs', crs)):
            if value is not None and value not in CRSS: raise Refused('Choose %s from: %s' % (name, ', '.join(CRSS)))
        body = {'kind': 'well', **({'bbox': list(bbox), 'bbox_crs': bbox_crs} if bbox is not None else {}), **({'crs': crs} if crs else {})}
        found, untransformed, cursor, seen = [], 0, None, set()
        while True:
            page = self._post('entities', 'list', {**body, 'limit': 100, **({'cursor': cursor} if cursor else {})})
            for document in page['entities']:
                location = document.get('location')
                if location is not None and crs is not None and location['crs'] != crs:
                    raise VerificationFailed('A location came back in %s, not the %s asked for.' % (location['crs'], crs))
                found.append(Well(document))
                if limit is not None and len(found) >= limit: return Wells(found, crs, untransformed + page.get('untransformed', 0))
            untransformed += page.get('untransformed', 0)
            cursor = page.get('next_cursor')
            if not cursor: return Wells(found, crs, untransformed)
            if cursor in seen: raise VerificationFailed('Repeated well cursor.')
            seen.add(cursor)

    def extent(self, crs='OGC:CRS84'):
        """The extent of the wells you may see located: {'crs', 'bbox' ([minx, miny, maxx, maxy] or None), 'count',
        'untransformed'}; wells whose stored CRS cannot be converted to `crs` are left out and counted."""
        if crs not in CRSS: raise Refused('Choose crs from: ' + ', '.join(CRSS))
        answer = self._post('entities', 'extent', {'crs': crs})
        if answer.get('crs') != crs: raise VerificationFailed('The extent came back in another CRS.')
        return answer
