"""E132: a person's verdict on one exact result version, accepted or rejected, with a reason (`ophiolite.verdict/1`,
`ophiolite/contracts/scientific/v1/verdict.json`). The server sets who gave it, when, and which earlier verdict of
theirs it supersedes; a client sends only the verdict, the reason, what it was judged against and, when it wants the
server to check, which verdict it expects to supersede.

`supersedes` has three states: left out (the default), the new verdict supersedes your current one on this version,
whatever it is; `None`, you expect to have none there yet; an id, it must be your current one. A server that does not
record verdicts yet answers "Recording verdicts is not available on this deployment yet." (slice 0).
"""
from __future__ import annotations  # E217 s0 (D1): annotations stay strings; nothing below is imported to run

import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # E217 s0 (D1): read by a type checker only
    from typing import Any


class _Unset:
    def __repr__(self): return 'UNSET'


UNSET = _Unset()


def against_outcome(outcome_id, version):
    return {'kind': 'outcome', 'outcome_id': outcome_id, 'version': version}


def against_check(key):
    return {'kind': 'check', 'key': key}


class VerdictClient:
    def record_verdict(self, asset_id: str, revision: str, verdict: str, reason: str | None = None, against=None, supersedes=UNSET, *,
                       command_id: str | None = None) -> dict[str, Any]:
        """Record `accepted` or `rejected` on this exact version, with a reason when rejected.

        The reason is at most 2000 characters. The same `command_id` and body answer the stored verdict again.
        """
        body = {'asset_id': asset_id, 'revision': revision, 'verdict': verdict,
                'command_id': command_id or 'verdict-%s' % uuid.uuid4().hex}
        if reason is not None: body['reason'] = reason
        if against is not None: body['against'] = against
        if supersedes is not UNSET: body['supersedes'] = supersedes
        return self._post('verdicts', 'record', body, retry=True)

    def verdicts(self, asset_id: str, revision: str) -> dict[str, Any]:
        """Every verdict on this exact version you may read, oldest first: {verdicts: [{record, current, line}]}."""
        return self._post('verdicts', 'list', {'asset_id': asset_id, 'revision': revision}, retry=True)

    def withdraw(self, asset_id: str, revision: str, reason: str, *, command_id: str | None = None) -> dict[str, Any]:
        """Withdraw this exact result version with your reason, which the server also records as your rejection of it.

        The rejection is shown by `verdicts` and the story. Reads the version's stage generation, then sends one
        transition; a lost answer is sent again with the same `command_id`, which answers the same withdrawal. Answers
        the version's stage view; nothing is read after the transition.
        """
        # E132 s2
        stage = self._post('stages', 'get', {'asset_id': asset_id, 'revision': revision}, retry=True)
        body = {'asset_id': asset_id, 'revision': revision, 'action': 'withdraw', 'expected_generation': stage['generation'],
                'reason': reason, 'command_id': command_id or 'withdraw-%s' % uuid.uuid4().hex}
        return self._post('stages', 'transition', body, retry=True)
