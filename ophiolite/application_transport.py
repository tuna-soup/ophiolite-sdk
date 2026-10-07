"""Shared application response/retry policy for sync and async HTTP drivers."""
import json
import math
import re
from .errors import (AuthenticationRequired,PermissionRefused,Unavailable,IntegrityConflict,
                     CapacityExceeded,Refused,Busy,ShareOutcomeUnknown,VerificationFailed,
                     SourceNeedsReview,SourceRevisionUnavailable,SourceDetached,SOURCE_GUIDE)

MAX_RESPONSE=48*1024*1024  # bounded JSON envelope including a 32 MiB base64 artifact
SHARE_RECOVERY='Read the current recipients first with client.grants(asset), then decide and call share again with the full intended audience and expected_generation from that snapshot.'


# E50a: the source refusals, selected by the server's code before its HTTP status (one table). The server's message
# is passed on verbatim (it states the bound when a table is over it); its remedy, docs and request id are kept.
SOURCE_CODES={'SOURCE_NEEDS_REVIEW':SourceNeedsReview,'SOURCE_REVISION_UNAVAILABLE':SourceRevisionUnavailable,
              'SOURCE_DETACHED':SourceDetached,'SOURCE_ACCESS_DENIED':PermissionRefused,'SOURCE_MISSING':Unavailable,
              'SOURCE_DELETED':Unavailable,'SOURCE_OFFLINE':Busy,'SOURCE_PENDING':Busy}
SOURCE_REMEDIES={'SOURCE_DETACHED':'This source was removed from the project. Ask a project administrator to resume it; selecting it again does not bring it back.'}
FINAL_CODES={code for code,kind in SOURCE_CODES.items() if not getattr(kind,'retryable',False)}  # a 429/503 naming one is never retried


def too_large():
    """E50a: the SDK's own response bound, stated in bytes with what to do (shared by the sync and async drivers)."""
    return CapacityExceeded('The response exceeds the SDK bound of %s bytes (%d MiB).' % (format(MAX_RESPONSE,','),MAX_RESPONSE//(1024*1024)),
                            'Read a smaller table: ask for an approved view with fewer rows or columns.',
                            remedy='Read a smaller table: ask for an approved view with fewer rows or columns.',docs=SOURCE_GUIDE+'#capacity-exceeded')


def retried(response,raw):
    """A 429/503 is retried unless its envelope names a final state (R4: a detached source is not busy)."""
    return envelope(response,raw).get('code') not in FINAL_CODES


def head_bytes(response):
    """The first bytes of a synchronous refusal's body, at most one past the bound."""
    raw=bytearray()
    try:
        for chunk in response.iter_bytes():
            raw.extend(chunk)
            if len(raw)>ENVELOPE_LIMIT:break
    except Exception:return b''
    return bytes(raw)


def delay(response):
    try:value=float(response.headers.get('Retry-After','0'))
    except ValueError:return 0
    return value if math.isfinite(value) and 0<=value<=60 else 0


ENVELOPE_LIMIT=16*1024  # an error body is small; never read more of a refusal than this
CODE=re.compile(r'^[A-Za-z0-9_.-]{1,64}$')
STAGE=re.compile(r'^[a-z][a-z-]{0,39}$')


async def bounded(response):
    """The first bytes of an async refusal's body, at most one past the bound (the caller then trusts none of it)."""
    raw=bytearray()
    try:
        async for chunk in response.aiter_bytes():
            raw.extend(chunk)
            if len(raw)>ENVELOPE_LIMIT:break
    except Exception:return b''
    return bytes(raw)


def envelope(response,raw=None):
    """E31: the server's error metadata ({code, message, remedy, docs, request_id}), read with a bound.

    A pre-E31 body, a malformed or truncated one, or one larger than the bound yields only what is safe:
    nothing, or the X-Request-Id header. Values are length-checked strings; nothing else is trusted."""
    meta={}
    rid=response.headers.get('X-Request-Id')
    if isinstance(rid,str) and 0<len(rid)<=64:meta['request_id']=rid
    try:
        if raw is None:
            raw=bytearray()
            for chunk in response.iter_bytes():
                raw.extend(chunk)
                if len(raw)>ENVELOPE_LIMIT:return meta
        if len(raw)>ENVELOPE_LIMIT:return meta
        body=json.loads(bytes(raw))
    except Exception:return meta
    if not isinstance(body,dict):return meta
    for key,limit in (('message',1000),('remedy',1000),('docs',300),('request_id',64)):
        value=body.get(key)
        if isinstance(value,str) and 0<len(value)<=limit:meta[key]=value
    if 'message' not in meta and isinstance(body.get('error'),str) and 0<len(body['error'])<=1000:meta['message']=body['error']
    if isinstance(body.get('code'),str) and CODE.match(body['code']):meta['code']=body['code']
    if isinstance(body.get('stage'),str) and STAGE.match(body['stage']):meta['stage']=body['stage']  # E51a
    return meta


def carried(meta):
    """The error keyword arguments a parsed envelope supplies (E51a: also the server's own sentence and a credential's stage)."""
    return {'remedy':meta.get('remedy'),'docs':meta.get('docs'),'request_id':meta.get('request_id'),'stage':meta.get('stage'),'server_message':meta.get('message')}


def status(response,operation,raw=None):
    code=response.status_code
    if 200<=code<300:return
    meta=envelope(response,raw)  # E31: first, so every category below keeps the server's metadata
    source=SOURCE_CODES.get(meta.get('code'))
    if source is not None:
        message=meta.get('message') or 'The source refused this read.'
        extra=carried(meta)
        if meta['code'] in SOURCE_REMEDIES:  # the server has no remedy of its own for these (its envelope falls back to "retry once")
            extra.update(remedy=SOURCE_REMEDIES[meta['code']],docs=SOURCE_GUIDE+'#'+meta['code'].lower().replace('_','-'))
        recovery=extra.get('remedy') or ''
        if source is Busy:raise Busy(message,recovery,status=code,retry_after=delay(response),code=meta['code'],**extra)
        raise source(message,recovery,status=code,code=meta['code'],**extra)
    if operation=='share' and code>=500:
        raise ShareOutcomeUnknown('The sharing outcome is unknown.',SHARE_RECOVERY,status=code,**carried(meta))
    if operation=='share' and code==409:
        raise IntegrityConflict('The recipients changed since you read them.',SHARE_RECOVERY,status=code,code=meta.get('code'),**carried(meta))
    kind,message={401:(AuthenticationRequired,'Sign in again.'),403:(PermissionRefused,'Check project access and the approved grant.'),
        404:(Unavailable,'The requested application data is unavailable or not permitted.'),
        409:(IntegrityConflict,'The request conflicts with the stored result.'),
        413:(CapacityExceeded,'This operation exceeds its supported size.'),
        429:(Busy,'The service is busy.'),503:(Busy,'The service is busy.')}.get(code,(Refused,'The application request was refused. Check the input and supported profile.'))
    recovery=meta.get('remedy','')
    if meta.get('code') in UPLOAD_CODES and meta.get('message') and kind is Busy:message=meta['message']  # E85b: busy fetching
    if kind is Busy:raise Busy(message,recovery,status=code,retry_after=delay(response),code=meta.get('code'),**carried(meta))
    if code==413:message=upload_limit(meta) or message
    if meta.get('code') in UPLOAD_CODES and meta.get('message'):message=meta['message']  # E54: the server's sentence for a file sent in parts
    raise kind(message,recovery,status=code,code=meta.get('code'),**carried(meta))


UPLOAD_CODES={'file-too-large','no-room','part-corrupt','file-mismatch','access-lost','not-a-volume','expired','unknown-upload',
              'unknown-run','claimed','session-mismatch','run-ended','too-many-runs','head-too-large',  # E55: a folder upload's refusals
              'address-invalid','address-not-found','address-private','address-certificate','address-other-site','address-redirects','address-sign-in',
              'address-answer','address-too-large','address-too-large-unknown','address-too-slow','address-compressed','address-off','address-busy',
              'address-other-run'}  # E85b: an address's refusals, the deployment's sentence (it names the host only)


def upload_limit(meta):
    """E22b: the deployment's own upload-limit refusal names its limit; pass exactly that sentence on."""
    text=meta.get('message')
    return text if isinstance(text,str) and text.startswith("The file exceeds this deployment's upload limit") and len(text)<120 else None


def decode(raw):
    def invalid(value):raise ValueError('nonfinite')
    try:value=json.loads(raw,parse_constant=invalid)
    except (ValueError,UnicodeError):raise VerificationFailed('The application response is not finite JSON.') from None
    if not isinstance(value,dict):raise VerificationFailed('The application response must be an object.')
    return value


def disconnected(operation):
    if operation=='share':raise ShareOutcomeUnknown('The sharing outcome is unknown.',SHARE_RECOVERY)
    raise Unavailable('The application response did not arrive. Keep the work folder and recover the same request.',code='outcome-unknown')
