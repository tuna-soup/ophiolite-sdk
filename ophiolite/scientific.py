"""Scientific array views. Values and their source metadata travel separately."""
from .models.generated import Contract
from .models.invariants import INTERPRETATION, REFERENCE, known, registry
from .errors import AxisMismatch, MissingExtra, Refused

class Axis(Contract):
    values: list[float]
    unit: str
    unit_status: str
    depth_index: str
    depth_reference: str
    order: str
    duplicates: bool

class CurveMetadata(Contract):
    unit: str
    unit_status: str
    missing_count: int
    sample_count: int
    marker: str

class Descriptor(Contract):
    asset_id: str
    revision: str
    project: str
    authority: str
    origin: str
    profile: str
    display_name: str
    axis: Axis
    curves: dict[str,CurveMetadata]
    interpretation: dict
    recorded_interpretation: dict | None
    evidence: str
    artifact_sha256: str
    curve_sha256: dict[str,str]
    workspace_url: str | None
    contracts: dict
    display: dict
    osdu_kind: str | None  # E168 s1 (D1): as the gateway served it; None for both from a gateway before E168 s0
    osdu_kind_reason: str | None

    def attach(self,frame):
        frame.attrs['ophiolite']=self.model_dump()
        return frame

    def _repr_html_(self):
        from .repr import descriptor_html
        return descriptor_html(self)


def workspace_url(data):
    """The stored data page (E45 `m~`) at this exact version (E104 C2; the page takes no curve key, Left 2)."""
    from .links import item_url
    if not data.url:return None
    asset=data.descriptors[0]
    return item_url(data.url,asset.project_id,'m',asset.asset_id,asset.revision)


MIXED='Well logs and application curves are not combined in one view; read them with one form.'  # E183 s2c


def aligned(data):
    if not data.curves or len(data.curves)!=len(data.descriptors):
        raise Refused('A view needs one scientific description for each selected curve.')
    if any(isinstance(v,WellLog) for v in data.curves):raise Refused(MIXED)  # E183 s2c: old and new forms never mix
    names=[v.curve for v in data.curves]
    if len(set(names))!=len(names):raise Refused('Choose distinct value curves for a combined view.')
    first=data.curves[0].model_dump(by_alias=True);first_asset=data.descriptors[0]
    for curve,asset in zip(data.curves[1:],data.descriptors[1:]):
        value=curve.model_dump(by_alias=True);left=first['axis'];right=value['axis']
        if left!=right:
            at=next((i for i,(a,b) in enumerate(zip(left,right)) if a!=b),min(len(left),len(right)))
            raise AxisMismatch(names,'values',at)
        a,b=first['context'],value['context']
        if a['depth_unit']!=b['depth_unit'] or first_asset.scientific.axis_unit_status!=asset.scientific.axis_unit_status:
            raise AxisMismatch(names,'unit')
        if a['depth_index']!=b['depth_index'] or a['depth_reference']!=b['depth_reference']:
            raise AxisMismatch(names,'reference')
        if known(first['interpretation'],INTERPRETATION)!=known(value['interpretation'],INTERPRETATION):
            raise AxisMismatch(names,'interpretation')
        if (known(first['source'],REFERENCE)!=known(value['source'],REFERENCE) or
            (first_asset.project_id,first_asset.asset_id,first_asset.revision)!=(asset.project_id,asset.asset_id,asset.revision)):
            raise AxisMismatch(names,'source')


def descriptor(data):
    aligned(data)
    asset=data.descriptors[0];view=data.curves[0];index,profiles=registry()
    normalized={a.scientific.curve:next(r.sha256 for r in a.representations if r.kind=='normalized') for a in data.descriptors}
    return Descriptor(
        asset_id=asset.asset_id,revision=asset.revision,project=asset.project_id,
        authority=asset.authority,origin=asset.origin,profile=asset.profile,
        display_name=profiles[asset.profile]['display_name'],
        axis=Axis(values=list(view.axis),unit=view.context.depth_unit,unit_status=asset.scientific.axis_unit_status,
                  depth_index=view.context.depth_index,depth_reference=view.context.depth_reference,
                  order=asset.scientific.axis_order,duplicates=asset.scientific.axis_duplicates),
        curves={v.curve:CurveMetadata(unit=v.unit,unit_status=a.scientific.unit_status,
                  missing_count=a.scientific.missing_count,sample_count=a.scientific.sample_count,
                  marker=v.context.missing_value_marker) for a,v in zip(data.descriptors,data.curves)},
        interpretation=asset.interpretation.model_dump(),
        recorded_interpretation=asset.recorded_interpretation.model_dump() if asset.recorded_interpretation else None,
        evidence=data.evidence[view.curve],
        artifact_sha256=next(r.sha256 for r in asset.representations if r.kind!='normalized'),
        curve_sha256=normalized,workspace_url=workspace_url(data),
        contracts={'registry_version':index['version'],'schema_ids':['ophiolite.scientific-asset/1','ophiolite.application-curve/1']},
        display=asset.display.model_dump(exclude_unset=True) if asset.display else {},
        osdu_kind=asset.osdu_kind,osdu_kind_reason=asset.osdu_kind_reason)


def to_numpy(data):
    from .windows import refuse_window;refuse_window(data)  # E100a
    try:import numpy as np
    except ImportError:raise MissingExtra("Install the NumPy extra: pip install 'ophiolite[numpy]'.") from None
    meta=descriptor(data)
    array=np.column_stack([np.array([np.nan if value is None else value for value in view.values],dtype='float64') for view in data.curves])
    return array,meta


def to_frame(data):
    try:import pandas as pd
    except ImportError:raise MissingExtra("Install the pandas extra: pip install 'ophiolite[pandas]'.") from None
    array,meta=to_numpy(data)
    frame=pd.DataFrame(array,index=meta.axis.values,columns=list(meta.curves))
    return frame,meta


class WellLogHeader:
    """E183 s2c: the file's header as received (`as_received`): its entries as text in file order, how many the file
    has and how many stayed in the original, and the source with its digest. Nothing here is read to decide anything."""
    __slots__=('entries','entries_total','entries_withheld','source','source_sha256')

    def __init__(self,received):
        self.entries=[dict(e) for e in received['entries']];self.entries_total=received['entries_total']
        self.entries_withheld=received['entries_withheld'];self.source=dict(received['source']);self.source_sha256=received['source_sha256']

    def __repr__(self):return 'WellLogHeader(%d entries, %d withheld)'%(len(self.entries),self.entries_withheld)


class WellLog:
    """E183 s2c: one curve read in the well log form (`ophiolite.well-log-curve/1`), verified. The well, depth kind, depth
    unit and datum are the sender's declarations as stored; `depth` and `values` are as served (a missing sample is None);
    `header` is the file's header as received. Nothing is converted, resampled or inferred."""
    def __init__(self,model):
        self._model=model;value=model.model_dump(by_alias=True);strict=value['strict']
        self.curve=strict['mnemonic'];self.well=strict['well'];self.unit=strict['unit']
        self.depth_kind,self.depth_unit,self.depth_datum=strict['depth_kind'],strict['depth_unit'],strict['depth_datum']
        self.depth,self.values=list(strict['depth']),list(strict['values'])
        self.missing_value_marker=strict['missing_value_marker'];self.reading=dict(strict['reading'])
        self.header=WellLogHeader(value['as_received'])

    def model_dump(self,**options):return self._model.model_dump(**options)

    def __repr__(self):return 'WellLog(%r, well=%r, %s %s, %d samples)'%(self.curve,self.well,self.depth_kind,self.depth_unit,len(self.depth))


class WellLogDescriptor(Contract):
    """E183 s2c: what a combined view of well logs states beside its numbers: the exact version, the declared well, depth
    kind, unit and datum, and per curve its unit, counts and marker."""
    asset_id: str
    revision: str
    project: str
    profile: str
    well: str
    depth_kind: str
    depth_unit: str
    depth_datum: str
    depth: list[float]
    curves: dict[str,CurveMetadata]
    interpretation: dict
    evidence: dict
    artifact_sha256: str
    curve_sha256: dict[str,str]
    workspace_url: str | None
    contracts: dict


def well_logs_aligned(data):
    """E183 s2c (C6): well logs combine only when depth, depth unit, depth kind, datum, well and source are all equal;
    otherwise AxisMismatch names the reason before any frame or file is built. Old and new forms never mix."""
    if not data.curves or len(data.curves)!=len(data.descriptors):
        raise Refused('A view needs one scientific description for each selected curve.')
    if not all(isinstance(v,WellLog) for v in data.curves):raise Refused(MIXED)
    names=[v.curve for v in data.curves]
    if len(set(names))!=len(names):raise Refused('Choose distinct value curves for a combined view.')
    first=data.curves[0];first_asset=data.descriptors[0]
    for log,asset in zip(data.curves[1:],data.descriptors[1:]):
        if first.depth!=log.depth:
            at=next((i for i,(a,b) in enumerate(zip(first.depth,log.depth)) if a!=b),min(len(first.depth),len(log.depth)))
            raise AxisMismatch(names,'values',at)
        if first.depth_unit!=log.depth_unit:raise AxisMismatch(names,'unit')
        if first.depth_kind!=log.depth_kind:raise AxisMismatch(names,'kind')
        if first.depth_datum!=log.depth_datum:raise AxisMismatch(names,'datum')
        if first.well!=log.well:raise AxisMismatch(names,'well')
        if (known(first.header.source,REFERENCE)!=known(log.header.source,REFERENCE) or first.header.source_sha256!=log.header.source_sha256 or
            (first_asset.project_id,first_asset.asset_id,first_asset.revision)!=(asset.project_id,asset.asset_id,asset.revision)):
            raise AxisMismatch(names,'source')


def well_log_descriptor(data):
    well_logs_aligned(data)
    asset=data.descriptors[0];log=data.curves[0]
    return WellLogDescriptor(
        asset_id=asset.asset_id,revision=asset.revision,project=asset.project_id,profile=asset.profile,
        well=log.well,depth_kind=log.depth_kind,depth_unit=log.depth_unit,depth_datum=log.depth_datum,depth=list(log.depth),
        curves={v.curve:CurveMetadata(unit=v.unit,unit_status='declared',missing_count=v.values.count(None),sample_count=len(v.values),
                                      marker=v.missing_value_marker) for v in data.curves},
        interpretation=asset.interpretation.model_dump(),evidence=data.evidence,
        artifact_sha256=next(r.sha256 for r in asset.representations if r.kind!='normalized'),
        curve_sha256={a.scientific.curve:next(r.sha256 for r in a.representations if r.kind=='normalized') for a in data.descriptors},
        workspace_url=workspace_url(data),
        contracts={'registry_version':registry()[0]['version'],'schema_ids':['ophiolite.scientific-asset/1','ophiolite.well-log-curve/1']})


def well_logs_numpy(data):
    try:import numpy as np
    except ImportError:raise MissingExtra("Install the NumPy extra: pip install 'ophiolite[numpy]'.") from None
    meta=well_log_descriptor(data)
    array=np.column_stack([np.array([np.nan if value is None else value for value in log.values],dtype='float64') for log in data.curves])
    return array,meta


def well_logs_frame(data):
    """The depth index is named by the declared depth kind; its unit, the datum and the well are in `attrs['ophiolite']`."""
    try:import pandas as pd
    except ImportError:raise MissingExtra("Install the pandas extra: pip install 'ophiolite[pandas]'.") from None
    array,meta=well_logs_numpy(data)
    frame=pd.DataFrame(array,index=pd.Index(meta.depth,name=meta.depth_kind,dtype='float64'),columns=list(meta.curves))
    frame.attrs['ophiolite']=meta.model_dump()
    return frame,meta
