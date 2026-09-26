"""Scientific array views. Values and their source metadata travel separately."""
from urllib.parse import quote
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

    def attach(self,frame):
        frame.attrs['ophiolite']=self.model_dump()
        return frame

    def _repr_html_(self):
        from .repr import descriptor_html
        return descriptor_html(self)


def workspace_url(data):
    from ._core import origin
    if not data.url:return None
    asset=data.descriptors[0]
    return (origin(data.url)+'/project/'+quote(asset.project_id,safe='')+'/asset/'+
            quote(asset.asset_id,safe='')+'?revision='+quote(asset.revision,safe='')+
            '&kind=scientific&curve='+quote(asset.scientific.curve,safe=''))


def aligned(data):
    if not data.curves or len(data.curves)!=len(data.descriptors):
        raise Refused('A view needs one scientific description for each selected curve.')
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
        display=asset.display.model_dump(exclude_unset=True) if asset.display else {})


def to_numpy(data):
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
