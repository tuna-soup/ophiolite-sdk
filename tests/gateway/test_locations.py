"""E29 S1: Client.wells and Client.extent against the in-process gateway (real chain, no patched authorization):
bbox with its CRS, stored coordinates by default, pagination past 100 wells, to_geojson only after a CRS84 fetch,
unlocated wells listed without a location, and an extent checked against extrema computed here."""
import json
import os
import pytest
try:
    from project_gateway.tests.test_one_api_matrix import web,shared,app,service
except ImportError:
    if os.environ.get('OPHIOLITE_REQUIRE_GATEWAY')=='1':raise
    pytest.skip('Platform test runtime is needed for the gateway lane',allow_module_level=True)
from ophiolite import Client,Credential
from ophiolite.errors import Refused

POINTS=[(155000.0,463000.0),(165000.0,463000.0),(150000.0,470000.0)]  # RD New (EPSG:28992)


def client(web,persona):
    return Client('https://workspace.example','p',Credential.bearer('oph_api_'+persona+':read,write'),web.c)


@pytest.fixture
def located(web):
    alice=client(web,'alice')
    wells=[]
    for n,(x,y) in enumerate(POINTS):
        well=alice.create_entity('well','L%d'%n,provisional=True,audience=['bob'],command_id='w%d'%n)
        up=alice.upload_data(json.dumps({'x':x,'y':y,'crs':'EPSG:28992','elevation_reference':'KB'}).encode(),profile='well-location/1',name='Location %d'%n,
                             attribution='Survey',audience=['bob'],rights_confirmed=True,command_id='l%d'%n)
        alice.share({'asset_id':up.asset_id,'revision':up.revision,'authority':'ophiolite:uploaded'},read=['bob'],expected_generation=alice.grants({'asset_id':up.asset_id,'revision':up.revision,'authority':'ophiolite:uploaded'}).generation)
        alice.of_entity(up.asset_id,up.revision,well,command_id='a%d'%n)
        wells.append(well)
    alice.create_entity('well','Unlocated',provisional=True,audience=['bob'],command_id='w-none')
    return alice,client(web,'bob')


def test_wells_as_stored_and_inside_a_box(located):
    alice,bob=located
    every=bob.wells()
    assert {w.name for w in every}=={'L0','L1','L2','Unlocated'} and every.crs is None
    stored={w.name:(w.location['x'],w.location['y'],w.location['crs']) for w in every if w.location}
    assert stored=={'L%d'%n:(x,y,'EPSG:28992') for n,(x,y) in enumerate(POINTS)} and all('transformation' not in w.location for w in every if w.location)
    assert next(w for w in every if w.name=='Unlocated').location is None
    inside=bob.wells(bbox=[149000,460000,160000,471000],bbox_crs='EPSG:28992')
    assert sorted(w.name for w in inside)==['L0','L2']
    with pytest.raises(Refused):bob.wells(bbox=[0,0,1,1])  # no bbox_crs


def test_to_geojson_needs_a_crs84_fetch(located):
    alice,bob=located
    with pytest.raises(Refused,match="crs='OGC:CRS84'"):bob.wells().to_geojson()
    with pytest.raises(Refused,match="crs='OGC:CRS84'"):bob.wells(crs='EPSG:28992').to_geojson()
    geo=bob.wells(crs='OGC:CRS84').to_geojson()
    located_features=[f for f in geo['features'] if f['geometry']]
    assert len(located_features)==3 and all(4<f['geometry']['coordinates'][0]<6 and 51<f['geometry']['coordinates'][1]<53 for f in located_features)
    assert next(f for f in geo['features'] if f['properties']['name']=='Unlocated')['geometry'] is None


def test_the_extent_matches_extrema_computed_here(located):
    alice,bob=located
    xs,ys=[p[0] for p in POINTS],[p[1] for p in POINTS]
    assert bob.extent('EPSG:28992')=={'crs':'EPSG:28992','bbox':[min(xs),min(ys),max(xs),max(ys)],'count':3,'untransformed':0}
    import pyproj
    t=pyproj.Transformer.from_crs('EPSG:28992','OGC:CRS84',always_xy=True)
    lons,lats=zip(*(t.transform(x,y) for x,y in POINTS))
    e=bob.extent()
    assert e['crs']=='OGC:CRS84' and all(abs(a-b)<1e-9 for a,b in zip(e['bbox'],[min(lons),min(lats),max(lons),max(lats)]))


def test_pages_past_a_hundred_wells_and_an_empty_box(web):
    alice=client(web,'alice')
    for n in range(105):alice.create_entity('well','P%03d'%n,provisional=True,command_id='p%d'%n)
    assert len(alice.wells())==105 and len(alice.wells(limit=7))==7
    assert list(alice.wells(bbox=[0,0,1,1],bbox_crs='EPSG:28992'))==[]



# E44: ED50 / UTM zone 31N. Synthetic positions in the Dutch offshore (whole kilometres); the oracle is literals: the
# stored extrema, the box they fall in, and a longitude/latitude box drawn from the zone's geometry (central meridian
# 3 E; 500 km east is the meridian, each 100 km east about 1.5 degrees at 53 N; northing 5,900 km is about 53.2 N).
ED50=[('ED50-A',600000,5940000),('ED50-B',580000,5920000),('ED50-C',560000,5900000)]


def test_ed50_utm31_is_a_crs_you_can_ask_for(web):
    alice=client(web,'alice')
    for n,(name,x,y) in enumerate(ED50):
        well=alice.create_entity('well',name,provisional=True,command_id='e%d'%n)
        up=alice.upload_data(json.dumps({'x':x,'y':y,'crs':'EPSG:23031','elevation_reference':'KB'}).encode(),profile='well-location/1',name='ED50 %d'%n,
                             attribution='Synthetic',audience=[],rights_confirmed=True,command_id='u%d'%n)
        alice.of_entity(up.asset_id,up.revision,well,command_id='o%d'%n)
    assert alice.extent('EPSG:23031')=={'crs':'EPSG:23031','bbox':[560000,5900000,600000,5940000],'count':3,'untransformed':0}
    assert sorted(w.name for w in alice.wells(bbox=[570000,5910000,620000,5950000],bbox_crs='EPSG:23031'))==['ED50-A','ED50-B']
    placed={w.name:(w.location['x'],w.location['y']) for w in alice.wells(crs='OGC:CRS84')}
    assert all(3.8<lon<4.6 and 53.2<lat<53.7 for lon,lat in placed.values()) and placed['ED50-A'][0]>placed['ED50-C'][0], placed
    with pytest.raises(Refused,match='EPSG:32631, EPSG:23031'):alice.extent('EPSG:2154')
