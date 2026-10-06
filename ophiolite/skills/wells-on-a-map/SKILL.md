---
name: wells-on-a-map
description: Show the wells a person may read on a map, zoom to their extent, and list the wells inside a box, without converting coordinates yourself.
---
<!-- sdk-contract: {"routes":["/api/v1/projects/{project}/entities/list","/api/v1/projects/{project}/entities/extent","/api/v1/projects/{project}/features/collections/{collection}/items"],"symbols":["ophiolite.Client.wells","ophiolite.Client.extent","ophiolite.locations.Wells.to_geojson","ophiolite.locations.Wells.to_frame"],"errors":["INVALID_ARGUMENT","PERMISSION_DENIED","verification-failed"]} -->

Use this when an application draws wells on a map or asks which wells lie inside an area.

```python
extent = client.extent()                         # {'crs': 'OGC:CRS84', 'bbox': [minx, miny, maxx, maxy] or None, 'count', 'untransformed'}
wells = client.wells(crs="OGC:CRS84")            # every well you may read; located ones carry x, y in that CRS
geojson = wells.to_geojson()                     # a FeatureCollection for MapLibre or Leaflet (CRS84 only)
inside = client.wells(bbox=[150000, 460000, 170000, 480000], bbox_crs="EPSG:28992", crs="OGC:CRS84")
```

A well's location comes from the newest source the person may read (a row of a table of wells, or a
well-location file associated with the well). The server converts coordinates; never convert them in the client
and never label unconverted numbers with another CRS. A well whose stored CRS cannot be converted has no
coordinates (`x` is `None`) and is counted in `untransformed`; a well with no location you may read is listed
without one. A box always needs its CRS (`bbox_crs`): nothing is guessed from the data.

Show each well's name; keep identifiers, the source revision and row under "Technical details". The supported
CRSs are OGC:CRS84, EPSG:4326 (latitude first in OGC API answers), EPSG:3857, EPSG:28992, EPSG:32631 and EPSG:23031; another is
refused (`Refused`, before anything is sent). GIS tools can open the same wells as an OGC API – Features collection at
/api/v1/projects/{project}/features/collections/{collection}/items (the collection is `wells`). `ophiolite init map-application` starts a map page
whose backend holds the credential.
