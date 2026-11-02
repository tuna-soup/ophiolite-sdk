"""Read a ZGY cube on your computer (E123 SZ, the reference ZGY reader): the cube is converted here to SEG-Y rev 1 with
IEEE samples and lands as a seismic volume. The conversion is `ophiolite.zgy.read`; until the coordinate system and the
vertical domain are confirmed it stops with its one question, before any sample is decoded."""
from ophiolite import procedure, zgy


@procedure
def read_zgy(inputs, settings):
    original = inputs['file'][0]
    return {'volume': zgy.read(original.path, crs=settings['crs'], z_domain=settings['z_domain'], horizontal_unit=settings['horizontal_unit'])}
