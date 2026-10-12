"""E90: what new files start with (a project's New data settings) and the one control on an uploaded original.

    snap = client.new_data_defaults()               # the five settings and the revision they were read at
    client.set_new_data_defaults(snap, **fields)    # an administrator's save, conditional on snap's revision; no refetch
    snap = client.audience(asset)                   # who can see an original and who can build on it, with both generations
    client.set_audience(snap, state=..., people=..., reason=...)   # conditional on both generations of snap

A refusal keeps the deployment's own sentence (not an administrator, the settings changed since you read them, a
narrower change without a reason). Nothing is fetched again behind your back: a stale snapshot is refused, and you
read again and decide again. `client.share` and `ophiolite share` are unchanged.
"""
import uuid

from .errors import Refused

SETTINGS = ('visible_to', 'depth_reference', 'coordinate_system', 'unit_system', 'attribution')
STATES = ('me', 'people', 'project')
CODES = ('PERMISSION_DENIED', 'settings-changed', 'recipients-changed', 'reason-required', 'defaults-changed', 'integrity-conflict')
LABELS = {'visible_to': {'project': 'Everyone in this project', 'me': 'Only the person who adds it', None: 'Only the person who adds it (not chosen yet)'},
          'depth_reference': {None: 'Not set', 'GL': 'Ground level', 'KB': 'Kelly bushing', 'MSL': 'Mean sea level'},
          'unit_system': {'unknown': 'Not set', 'm': 'Metres', 'ft': 'Feet'}}
NAMES = {'visible_to': 'Who can see new files', 'depth_reference': 'Depth reference for wells', 'coordinate_system': 'Coordinate system',
         'unit_system': 'Unit system', 'attribution': 'Source attribution'}


def said(call):
    """A refusal in the deployment's own sentence; any other error as the transport raised it."""
    from .errors import OphioliteError
    try: return call()
    except OphioliteError as error:
        if error.code not in CODES or not error.server_message: raise
        raise type(error)(error.server_message, status=error.status, code=error.code, request_id=error.request_id, remedy=error.remedy,
                          docs=error.docs, server_message=error.server_message, details=error.details) from error


def _snapshot(answer):
    if not isinstance(answer, dict) or not isinstance(answer.get('settings'), dict) or type(answer.get('revision')) is not int:
        from .errors import VerificationFailed
        raise VerificationFailed('The new-data settings answered outside their documented shape.')
    return {**{k: answer['settings'].get(k) for k in SETTINGS}, 'revision': answer['revision'], 'legacy': bool(answer.get('legacy')),
            'administrator': bool(answer.get('administrator'))}


def defaults(client):
    """The project's New data settings as any member reads them: the five settings, `revision`, `legacy` (no one has
    chosen who sees new files: they behave as 'me') and whether you may change them (`administrator`)."""
    return _snapshot(said(lambda: client._post('context', 'new-data', {}, retry=True)))


def set_defaults(client, snap, **fields):
    """Replace the settings you reviewed in `snap` with `fields` changed; refused when they changed since `snap` was read
    (read them again, never refetched here) or when you do not administer the project."""
    unknown = sorted(set(fields) - set(SETTINGS))
    if unknown: raise Refused('New data has no setting %s; it has %s.' % (', '.join(unknown), ', '.join(SETTINGS)))
    if not isinstance(snap, dict) or type(snap.get('revision')) is not int: raise Refused('Pass the snapshot client.new_data_defaults() returned.')
    settings = {k: snap.get(k) for k in SETTINGS}
    settings.update(fields)
    if settings['visible_to'] is None: raise Refused("Choose who can see new files: 'project' or 'me'.")
    body = {'expected_revision': snap['revision'], 'settings': settings}
    return _snapshot(said(lambda: client._post('context', 'new-data-save', body)))


def lines(snap):
    """The settings in the Workspace's words, one per line."""
    out = []
    for key in SETTINGS:
        value = snap.get(key)
        shown = LABELS[key].get(value, value) if key in LABELS else (value or 'Not set')
        out.append('%s: %s' % (NAMES[key], shown))
    out.append('Settings revision %d%s' % (snap['revision'], '' if snap.get('administrator') else '; only a project administrator can change them'))
    return out


# --- the one control on an uploaded original (C3's routes) -------------------------------------------------------------

def audience(client, asset):
    """Who can see an uploaded original and who can build on it: `state` (me, people or project), `people` [{id, can_see
    (True, False or 'legacy': an earlier entry that may see it but holds no grant), build_on}] and both generations."""
    answer = said(lambda: client._post('las-uploads', 'audience', {'asset_id': _asset(asset)}, retry=True))
    return _audience_snapshot(answer, _asset(asset))


def _audience_snapshot(answer, asset):
    from .errors import VerificationFailed
    if (not isinstance(answer, dict) or answer.get('asset_id') != asset or answer.get('state') not in STATES or not isinstance(answer.get('people'), list)
            or type(answer.get('policy_generation')) is not int or type(answer.get('grants_generation')) is not int):
        raise VerificationFailed('Who can see this answered outside its documented shape.')
    people = [{'id': p['id'], 'can_see': 'legacy' if p.get('legacy') else bool(p.get('can_see')), 'build_on': bool(p.get('build_on'))} for p in answer['people']]
    return {'asset_id': asset, 'state': answer['state'], 'people': people, 'policy_generation': answer['policy_generation'],
            'grants_generation': answer['grants_generation'], **({'replayed': answer['replayed']} if 'replayed' in answer else {})}


def _asset(asset):
    if isinstance(asset, str): return asset
    if isinstance(asset, dict) and isinstance(asset.get('asset_id'), str): return asset['asset_id']
    return getattr(asset, 'asset_id')


def change(snap, state=None, people=None, build_on=None):
    """The save body for `snap` changed: `state`, `people` (ids who can see; None keeps snap's) and `build_on` (ids who can
    build on it; None keeps snap's). Someone who can build on it can also see it under 'people'. Naming people on an
    'only me' original, with no state, makes it 'people'."""
    if state is None: state = 'people' if snap['state'] == 'me' and (people or build_on) else snap['state']  # naming someone widens 'only me'
    if state not in STATES: raise Refused("Choose who can see it: 'me', 'people' or 'project'.")
    kept = {p['id']: dict(p) for p in snap['people']}
    if people is not None:
        named = list(dict.fromkeys(people))
        for p in kept.values():
            if p['id'] not in named and p['can_see'] is True: p['can_see'] = False
        for i in named: kept.setdefault(i, {'id': i, 'can_see': True, 'build_on': False})['can_see'] = True
    if build_on is not None:
        for p in kept.values(): p['build_on'] = p['id'] in build_on
        for i in build_on: kept.setdefault(i, {'id': i, 'can_see': state == 'people', 'build_on': True})
    if state == 'me': chosen = []
    else: chosen = [p for p in kept.values() if p['can_see'] in (True, 'legacy') or p['build_on']]
    return {'asset_id': snap['asset_id'], 'state': state, 'people': [{'id': p['id'], 'can_see': p['can_see'], 'build_on': p['build_on']} for p in chosen],
            'expected_generation': snap['policy_generation'], 'expected_grants_generation': snap['grants_generation']}


def preview(client, body):
    """What saving `body` would do, saved nowhere: {told, losing, narrower} (counts of people you may see)."""
    return said(lambda: client._post('las-uploads', 'audience-preview', body, retry=True))


def save(client, body, reason=None, command_id=None):
    """Save `body` (from `change`) once; an identical retry after an unknown outcome returns the first receipt."""
    sent = {**body, **({'reason': reason} if reason else {}), 'command_id': command_id or uuid.uuid4().hex}
    answer = said(lambda: client._post('las-uploads', 'audience-save', sent, retry=True))
    return _audience_snapshot(answer, body['asset_id'])


def preview_line(answer):
    """E72c's words: who will be told and who will lose access."""
    def people(n): return 'No one' if n == 0 else '1 person' if n == 1 else '%d people' % n
    told, losing = answer.get('told'), answer.get('losing')
    if told is None: return 'Saved for the people you chose.'
    first = '%s will be told.' % people(told)
    return first + ('' if not losing else ' %s will lose access.' % people(losing))
