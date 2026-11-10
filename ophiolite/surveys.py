"""E142 s1: a survey read as one unit (ophiolite.survey/1 pages put together) and the bodies of its commands.

`Survey` holds every member and relation the caller may read at one survey revision, gathered page by page; a
page's `count` is the caller's, so a survey read by someone who may read fewer members is smaller, never abridged.
Every command carries a `command_id`; the SDK makes a fresh one when none is given and keeps it across its own retry,
so a lost answer replays the receipt instead of making a second revision.
"""
import uuid
from dataclasses import dataclass, field

from .errors import VerificationFailed

MAX_PAGES = 200  # 10,000 members at the smallest useful page of 50; more means a looping cursor


@dataclass(frozen=True)
class Survey:
    survey_id: str
    name: str
    identity: object
    source: object
    context: object
    revision: int
    view: str
    count: int
    members: list = field(default_factory=list)
    relations: list = field(default_factory=list)

    def member(self, asset_id):
        """The served member of this asset, or None when the caller may not read it here."""
        return next((m for m in self.members if m.asset_id == asset_id), None)


def gathered(pages):
    """One Survey from its pages (SurveyPage models, first page first); every page must be of one survey revision."""
    first, members, relations = None, [], []
    for page in pages:
        if first is None: first = page
        elif (page.survey_id, page.revision, page.view) != (first.survey_id, first.revision, first.view):
            raise VerificationFailed('A survey page belongs to another survey revision.')
        members += page.members; relations += page.relations
    if first is None: raise VerificationFailed('The survey answered no page.')
    if len({(m.asset_id, m.revision) for m in members}) != len(members): raise VerificationFailed('A survey member was served twice.')
    return Survey(first.survey_id, first.name, first.identity, first.source, first.context, first.revision, first.view,
                  first.count, members, relations)


def key(member):
    """{asset_id, revision} of a served member, a (asset_id, revision) pair or a mapping."""
    if isinstance(member, (tuple, list)): return {'asset_id': member[0], 'revision': member[1]}
    if isinstance(member, dict): return {'asset_id': member['asset_id'], 'revision': member['revision']}
    return {'asset_id': member.asset_id, 'revision': member.revision}


def command(body, command_id=None):
    return {**body, 'command_id': command_id or uuid.uuid4().hex}
