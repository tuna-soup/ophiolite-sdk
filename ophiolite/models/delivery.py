"""E109 slice 0: the delivery a send procedure's run reports, and the report this computer sends about it.

`Delivery` is the closed payload `ophiolite.delivery/1` = {delivery_id, state, items}. Its rule of record is the
contract's own file, `ophiolite/contracts/procedures/v1/delivery.py`, byte-identical to the Platform's copy and loaded
from its source text (no bytecode is read or written), so a payload the SDK accepts is one the server accepts.
`DeliveryObservation` is the body of `activity/deliver` (profile `procedure-delivery/1`): the exact versions read,
the procedure, the destination's label (never its configuration) and the payload. Nothing in this release sends it:
`ophiolite deliver` answers that delivering is not available on this deployment yet.
"""
import types
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, model_validator

CONTRACT = Path(__file__).resolve().parent.parent / 'contracts' / 'procedures' / 'v1' / 'delivery.py'
PROFILE = 'procedure-delivery/1'
KIND = 'delivery.reported'
_contract = None


def contract():
    """The packaged delivery check (loaded once, from source text)."""
    global _contract
    if _contract is None:
        module = types.ModuleType('ophiolite_delivery_contract')
        module.__file__ = str(CONTRACT)
        exec(compile(CONTRACT.read_text(encoding='utf-8'), str(CONTRACT), 'exec'), module.__dict__)
        _contract = module
    return _contract


def verdict(payload):
    """The contract's verdict on a parsed payload: {'valid', 'rules_version'} or, refused, also code, field, sentence."""
    return contract().verdict(payload)


class _Closed(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Delivery(_Closed):
    """ophiolite.delivery/1: what a send procedure's run returns; the reason text a writer gives is never part of it."""
    delivery_id: StrictStr
    state: Literal['confirmed', 'not-sent', 'unknown']
    items: int = Field(ge=0, le=1000000, strict=True)

    @model_validator(mode='before')
    @classmethod
    def _contract(cls, value):
        contract().check(value)  # Invalid is a ValueError: the same verdict as the server's
        return value


class DeliveryRef(_Closed):
    """An exact version the send procedure read."""
    project_id: StrictStr = Field(min_length=1, max_length=160)
    asset_id: StrictStr = Field(min_length=1, max_length=256)
    revision: StrictStr = Field(pattern=r'^([1-9][0-9]{0,19}|[0-9a-f]{64})$')


class DeliveryProcedure(_Closed):
    """The send procedure that made the delivery, as the project's catalogue knows it."""
    digest: StrictStr = Field(pattern=r'^[0-9a-f]{64}$')
    label: StrictStr = Field(min_length=1, max_length=100)
    version: int = Field(ge=1, le=1000000, strict=True)


class DeliveryObservation(_Closed):
    """The report of one delivery's outcome (`activity/deliver`); the same refs, procedure and destination on every
    report of one delivery id."""
    project_id: StrictStr = Field(min_length=1, max_length=160)
    event_id: StrictStr = Field(pattern=r'^[a-zA-Z0-9-]{16,80}$')
    profile: Literal['procedure-delivery/1'] = PROFILE
    refs: list[DeliveryRef] = Field(min_length=1, max_length=64)
    procedure: DeliveryProcedure
    destination: StrictStr = Field(min_length=1, max_length=100)
    delivery: Delivery
