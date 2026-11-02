"""E132: a person's verdict on one exact result version, accepted or rejected, with a reason (`ophiolite.verdict/1`,
`ophiolite/contracts/scientific/v1/verdict.json`). The server sets who gave it, when, and which earlier verdict of
theirs it supersedes; a client sends only the verdict, the reason, what it was judged against and, when it wants the
server to check, which verdict it expects to supersede.

`supersedes` has three states: left out (the default), the new verdict supersedes your current one on this version,
whatever it is; `None`, you expect to have none there yet; an id, it must be your current one. A server that does not
record verdicts yet answers "Recording verdicts is not available on this deployment yet." (slice 0).
"""
import uuid


class _Unset:
    def __repr__(self): return 'UNSET'


UNSET = _Unset()


def against_outcome(outcome_id, version):
    return {'kind': 'outcome', 'outcome_id': outcome_id, 'version': version}


def against_check(key):
    return {'kind': 'check', 'key': key}


class VerdictClient:
    def record_verdict(self, asset_id, revision, verdict, reason=None, against=None, supersedes=UNSET, *, command_id=None):
        """Record `accepted` or `rejected` on this exact version (a reason is required when rejected, at most 2000
        characters). The same `command_id` and body answer the stored verdict again."""
        body = {'asset_id': asset_id, 'revision': revision, 'verdict': verdict,
                'command_id': command_id or 'verdict-%s' % uuid.uuid4().hex}
        if reason is not None: body['reason'] = reason
        if against is not None: body['against'] = against
        if supersedes is not UNSET: body['supersedes'] = supersedes
        return self._post('verdicts', 'record', body, retry=True)

    def verdicts(self, asset_id, revision):
        """Every verdict on this exact version you may read, oldest first: {verdicts: [{record, current, line}]}."""
        return self._post('verdicts', 'list', {'asset_id': asset_id, 'revision': revision}, retry=True)

    def withdraw(self, asset_id, revision, reason, *, command_id=None):
        """E132 s2: withdraw this exact result version with your reason; the server also records your rejection of it
        with that reason (shown by `verdicts` and the story). Reads the version's stage generation, then sends one
        transition; a lost answer is sent again with the same `command_id`, which answers the same withdrawal. Answers
        the version's stage view; nothing is read after the transition."""
        stage = self._post('stages', 'get', {'asset_id': asset_id, 'revision': revision}, retry=True)
        body = {'asset_id': asset_id, 'revision': revision, 'action': 'withdraw', 'expected_generation': stage['generation'],
                'reason': reason, 'command_id': command_id or 'withdraw-%s' % uuid.uuid4().hex}
        return self._post('stages', 'transition', body, retry=True)
