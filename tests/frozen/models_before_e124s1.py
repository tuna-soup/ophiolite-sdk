"""E124 s1 (A1, R6): the released SDK models (main d66fe65be, `ophiolite/models/generated.py`) of the three contracts A1
widens and what they use, copied verbatim class by class, so the old reader is tested as it was released."""
from __future__ import annotations
from typing import Annotated, Any, ClassVar, Literal
from pydantic import BaseModel, ConfigDict, Field

class Contract(BaseModel):
    model_config = ConfigDict(extra='allow', strict=True, allow_inf_nan=False)
    __strict_extras__: ClassVar[bool] = False


class Reference(Contract):
    authority: Annotated[str, Field(min_length=1, max_length=512)] = Field(...)
    key: Annotated[str, Field(min_length=1, max_length=512)] = Field(...)
    revision: Annotated[str, Field(min_length=1, max_length=512)] = Field(...)
    profile: Annotated[str, Field(pattern='^[a-z0-9][a-z0-9.-]*(/[a-z0-9.-]+)*/[0-9]+$', max_length=128)] = Field(...)

class TypedInterpretation(Contract):
    reader: Literal['asset_connectors.typed_reader/1', 'asset_connectors.feature_files/1'] = Field(...)
    mapping: Literal['well-tops/1', 'trajectory/1', 'regular-grid-surface/1', 'triangulated-surface/1', 'point-set/1', 'polyline-set/1', 'seismic-volume/1', 'well-location/1', 'wavelet/1', 'model-section/1', 'seismic-section/1', 'time-depth/1', 'feature-set/1', 'well-path/1', 'well-set/1', 'well-residual/1'] = Field(...)
    parsing_policy: Literal['typed-strict/1'] = Field(...)
    null_policy: Annotated[str, Field(min_length=1, max_length=512)] = Field(...)

class Fidelity(Contract):
    status: Literal['assessed'] = Field(...)
    preserved: Annotated[list[Annotated[str, Field(min_length=1, max_length=512)]], Field(max_length=16)] = Field(...)
    losses: Annotated[list[Annotated[str, Field(min_length=1, max_length=512)]], Field(max_length=16)] = Field(...)
    unknown_context: Annotated[list[Annotated[str, Field(min_length=1, max_length=128)]], Field(max_length=16)] = Field(...)
    decisions: Annotated[list[Annotated[str, Field(min_length=1, max_length=512)]], Field(max_length=64)] | None = Field(None)

class TrajectoryContext(Contract):
    type: Literal['trajectory'] = Field(...)
    depth_unit: Annotated[str, Field(pattern='^([A-Za-z0-9 ./^()\\-]{1,32}|unknown)$')] = Field(...)
    angle_unit: Literal['deg'] = Field(...)
    azimuth_reference: Literal['true-north', 'grid-north', 'magnetic-north', 'unknown'] = Field(...)
    depth_datum: Annotated[str, Field(min_length=1, max_length=128)] = Field(...)
    count: Annotated[int, Field(ge=1, le=10000)] = Field(...)
    missing_angle_count: Annotated[int, Field(ge=0, le=10000)] = Field(...)
    tvd_provided: bool = Field(...)
    md_range: Annotated[list[float], Field(min_length=2, max_length=2)] = Field(...)
    fidelity: Fidelity = Field(...)

class Station(Contract):
    md: float = Field(...)
    inclination: Annotated[float, Field(ge=0, le=180)] | None = Field(...)
    azimuth: Annotated[float, Field(ge=0, le=360)] | None = Field(...)
    tvd: float | None = Field(...)

class Trajectory(Contract):
    representation: Literal['normalized'] = Field(...)
    source: Reference = Field(...)
    source_sha256: Annotated[str, Field(pattern='^[0-9a-f]{64}$')] = Field(...)
    interpretation: TypedInterpretation = Field(...)
    schema_: Literal['ophiolite.trajectory/1'] = Field(..., alias='schema')
    context: TrajectoryContext = Field(...)
    stations: Annotated[list[Station], Field(min_length=1, max_length=10000)] = Field(...)

class WellPathContext(Contract):
    type: Literal['well-path'] = Field(...)
    crs: Annotated[str, Field(pattern='^(EPSG:[0-9]{4,6}|unknown)$')] = Field(...)
    xy_unit: Annotated[str, Field(pattern='^([A-Za-z0-9 ./^()\\-]{1,32}|unknown)$')] = Field(...)
    depth_unit: Annotated[str, Field(pattern='^([A-Za-z0-9 ./^()\\-]{1,32}|unknown)$')] = Field(...)
    md_reference: Literal['KB', 'DF', 'RT', 'GL', 'MSL', 'unknown'] = Field(...)
    tvdss_datum: Literal['MSL', 'unknown'] = Field(...)
    count: Annotated[int, Field(ge=1, le=10000)] = Field(...)
    md_range: Annotated[list[float], Field(min_length=2, max_length=2)] = Field(...)
    tvdss_range: Annotated[list[float], Field(min_length=2, max_length=2)] = Field(...)
    fidelity: Fidelity = Field(...)

class WellPathStation(Contract):
    md: float = Field(...)
    x: float = Field(...)
    y: float = Field(...)
    tvdss: float = Field(...)

class WellPath(Contract):
    representation: Literal['normalized'] = Field(...)
    source: Reference = Field(...)
    source_sha256: Annotated[str, Field(pattern='^[0-9a-f]{64}$')] = Field(...)
    interpretation: TypedInterpretation = Field(...)
    schema_: Literal['ophiolite.well-path/1'] = Field(..., alias='schema')
    context: WellPathContext = Field(...)
    stations: Annotated[list[WellPathStation], Field(min_length=1, max_length=10000)] = Field(...)

class CurveContext(Contract):
    depth_index: Annotated[str, Field(min_length=1, max_length=512)] = Field(...)
    depth_unit: Annotated[str, Field(max_length=128)] = Field(...)
    depth_reference: Annotated[str, Field(min_length=1, max_length=512)] = Field(...)
    missing_value_marker: Annotated[str, Field(min_length=1, max_length=512)] = Field(...)
    missing_value_policy: Annotated[str, Field(min_length=1, max_length=512)] = Field(...)

class Interpretation(Contract):
    reader: Literal['asset_connectors.las_reader/1'] = Field(...)
    lasio_version: Annotated[str, Field(min_length=1, max_length=512)] = Field(...)
    mapping: Literal['application-curve/1'] = Field(...)
    null_policy: Annotated[str, Field(min_length=1, max_length=512)] = Field(...)
    parsing_policy: Literal['las2-strict-null/1'] = Field('las2-strict-null/1')

class CurveColumnsHeader(Contract):
    schema_: Literal['ophiolite.curve-columns/1'] = Field(..., alias='schema')
    representation: Literal['normalized'] = Field(...)
    curve: Annotated[str, Field(min_length=1, max_length=512)] = Field(...)
    unit: Annotated[str, Field(max_length=128)] = Field(...)
    context: CurveContext = Field(...)
    source: Reference = Field(...)
    source_sha256: Annotated[str, Field(pattern='^[0-9a-f]{64}$')] = Field(...)
    interpretation: Interpretation = Field(...)
    count: Annotated[int, Field(ge=0, le=4000000)] = Field(...)
    encoding: Literal['f64le'] = Field(...)

Reference.model_rebuild()
TypedInterpretation.model_rebuild()
Fidelity.model_rebuild()
TrajectoryContext.model_rebuild()
Station.model_rebuild()
Trajectory.model_rebuild()
WellPathContext.model_rebuild()
WellPathStation.model_rebuild()
WellPath.model_rebuild()
CurveContext.model_rebuild()
Interpretation.model_rebuild()
CurveColumnsHeader.model_rebuild()
