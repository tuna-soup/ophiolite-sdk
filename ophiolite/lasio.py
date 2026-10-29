"""E126a: a project's log as a `lasio.LASFile`, and a lasio-built file back into the project (`pip install 'ophiolite[lasio]'`).

`to_lasio` **reconstructs** a LAS file from one exact read: `DEPT` and each curve with its declared unit, `NaN` for
missing, `NULL` -999.25, and an `~Other` section naming the project, asset and revision. It does not reproduce the
original header (`Client.download_original` returns the original file): COMP, FLD, LOC, PROV, CNTY, STAT, CTRY, SRVC,
DATE, UWI, API, the curve descriptions and `~Params` are left empty. `WELL` is the name of the one well linked to this
exact revision that you may read; else the `well=` you give; else empty. It is never taken from the original header or
a display name.

`lasio_bytes` writes a `LASFile` for `Client.upload_las` with every sample spelled exactly, and re-reads its header
with the SDK's own reader before returning. `curves_from_lasio` turns a `LASFile` into the `WrittenOriginal` that
`Client.publish_derived` takes, with the file's `NULL` as missing. lasio is imported only when one of these is called;
the SDK's core (`import ophiolite`, `ophiolite.exchange`) never imports it.
"""
import io
import math
from .errors import Busy, MissingExtra, OphioliteError, PermissionRefused, Unavailable, ValidationFailed, VerificationFailed

NULL = -999.25


def _lasio():
    try:
        import lasio
        return lasio
    except ImportError: raise MissingExtra("Install the lasio extra: pip install 'ophiolite[lasio]'.") from None


def _nan(value):
    return isinstance(value, float) and math.isnan(value)


def _exact(curve):
    """A LASFile curve's samples as 64-bit floats, refusing any a 64-bit float cannot hold exactly (E126a: nothing is rounded)."""
    import numpy as np
    data = np.asarray(curve.data)
    if data.dtype.kind not in 'fiu': raise ValidationFailed([f'Curve {curve.mnemonic} is not numeric; write numbers only.'])
    if data.dtype.kind == 'f' and data.dtype.itemsize > 8:
        raise ValidationFailed([f'Curve {curve.mnemonic} is wider than a 64-bit float and cannot be written exactly; nothing is rounded.'])
    if data.dtype.kind in 'iu':
        for v in data.tolist():
            if int(float(v)) != v: raise ValidationFailed([f'{v} in {curve.mnemonic} cannot be written exactly; nothing is rounded.'])
    return [float(v) for v in data.tolist()]


def _no_marker(name, values, marker):
    if any(v is not None and not _nan(float(v)) and float(v) == marker for v in values):
        raise ValidationFailed([f'Curve {name} has a real value equal to the null marker {marker:g}; it would read back as missing.'])


def _linked_well(data):
    """The name of the one well linked to this exact revision that the caller may read, or None."""
    client = getattr(data, '_client', None)
    if client is None: return None
    asset, revision = data.descriptors[0].asset_id, data.descriptors[0].revision
    names = {}
    for item in client.associations(assets=[asset]):
        entity = item.get('entity') or {}
        if (item.get('asset_id'), item.get('revision')) != (asset, revision): continue
        if entity.get('kind') == 'well': names[entity['entity_id']] = entity['name']
        elif entity.get('kind') == 'wellbore':
            try: well = client.entity(entity['entity_id']).well()  # None when its well is hidden from you
            except Busy: raise  # a busy service says nothing about the well: never a different WELL
            except (PermissionRefused, Unavailable): continue
            if well is not None: names[well.entity_id] = well.name
    return next(iter(names.values())) if len(names) == 1 else None


def to_lasio(data, *, well=None):
    """One exact read (`Client.read(...)`) as a reconstructed `lasio.LASFile`; see the module text for what it carries."""
    lasio = _lasio()
    import numpy as np
    from .scientific import descriptor
    from .windows import refuse_window
    refuse_window(data)  # E100a: blocks are not samples
    meta = descriptor(data)  # one axis and one exact source (AxisMismatch otherwise)
    for view in data.curves: _no_marker(view.curve, view.values, NULL)
    linked = _linked_well(data)
    las = lasio.LASFile()
    las.append_curve('DEPT', np.array(meta.axis.values, dtype='float64'), unit=meta.axis.unit)
    for view in data.curves:
        las.append_curve(view.curve, np.array([np.nan if v is None else v for v in view.values], dtype='float64'), unit=view.unit)
    las.well['NULL'].value = NULL
    las.well['WELL'].value = linked if linked is not None else (well or '')
    las.other = '\n'.join([f'Project {meta.project}', f'Asset {meta.asset_id}', f'Revision {meta.revision}'])
    return las


def _null(las):
    try: marker = float(las.well['NULL'].value)
    except (KeyError, TypeError, ValueError): marker = math.nan
    if not math.isfinite(marker): raise ValidationFailed(["Declare the file's NULL value as a finite number; nothing is inferred."])
    return marker


def lasio_bytes(las):
    """A `LASFile` as LAS 2.0 bytes for `Client.upload_las`: written by lasio with every sample spelled exactly
    (`%.17g`), then its curve header re-read by the SDK's reader; a disagreement returns nothing. A real sample equal
    to the file's NULL would read back as missing, so it is refused (`curves_from_lasio`, by contrast, reads such a
    value as missing: there the file's NULL is how the file says "missing"). A sample a 64-bit float cannot hold exactly
    (a large integer, a wider float), an infinite sample and a missing depth are refused."""
    _lasio()
    from . import las_header
    marker = _null(las)
    for i, curve in enumerate(las.curves):
        values = _exact(curve)
        if i == 0 and any(_nan(v) for v in values): raise ValidationFailed(['Depth cannot be missing.'])
        if any(math.isinf(v) for v in values): raise ValidationFailed([f'Curve {curve.mnemonic} must be finite; write a missing sample as NaN.'])
        _no_marker(curve.mnemonic, values, marker)
    out = io.StringIO()
    las.write(out, version=2.0, fmt='%.17g')
    raw = out.getvalue().encode()
    try: read = [(c.mnemonic, c.unit) for c in las_header.curves(raw)]
    except OphioliteError: read = None
    if read != [(c.mnemonic, c.unit) for c in las.curves]:
        raise VerificationFailed('lasio wrote a header the SDK reads differently; nothing was returned.')
    return raw


def curves_from_lasio(las, *, depth_unit=None, well=None, filename='derived.las', notes=()):
    """A `LASFile` as the `WrittenOriginal` `Client.publish_derived` takes, through `write_curves`. The first curve is
    the depth; `NaN` and any value equal to the file's numeric `NULL` are missing (a file built in a notebook may hold
    the marker itself; `lasio_bytes` refuses such a value instead, because it writes the file); units are the file's;
    a sample a 64-bit float cannot hold exactly is refused. The depth unit is the file's or `depth_unit=`; neither, or two different
    ones, is refused (nothing is converted). `well` defaults to the file's `WELL`, else 'DERIVED'."""
    _lasio()
    from .writers import write_curves
    if not las.curves: raise ValidationFailed(['The file has no curves.'])
    index, rest = las.curves[0], las.curves[1:]
    stated = (index.unit or '').strip()
    if not stated and not depth_unit: raise ValidationFailed([f"Declare the depth unit: the file's {index.mnemonic} curve has none; nothing is inferred."])
    if stated and depth_unit and stated != depth_unit:
        raise ValidationFailed([f"The file's depth unit {stated!r} differs from depth_unit={depth_unit!r}; nothing is converted."])
    try: marker = float(las.well['NULL'].value)
    except (KeyError, TypeError, ValueError): marker = None
    if well is None:
        try: well = str(las.well['WELL'].value or '').strip() or 'DERIVED'
        except KeyError: well = 'DERIVED'
    value = lambda v: None if _nan(float(v)) or float(v) == marker else float(v)
    depth = [value(d) for d in _exact(index)]
    curves = {c.mnemonic: (c.unit, [value(v) for v in _exact(c)]) for c in rest}
    return write_curves(depth, curves, depth_unit=stated or depth_unit, well=well, filename=filename, notes=notes)
