"""Typed preview catalogue and browser-application grant responses."""
from pydantic import Field
from .generated import Contract, AssetSummary

class ListPage(Contract):
    items: list[AssetSummary]
    next_cursor: str | None = None

class Grant(Contract):
    id: str
    user_id: str
    project_id: str
    scopes: list[str]
    label: str
    confirmation_code: str
    state: str
    created_at: str
    expires_at: str
    capability: int = Field(ge=1)
