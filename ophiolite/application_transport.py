"""Shared application response/retry policy for sync and async HTTP drivers."""
import json
import math
import re
from .errors import (AuthenticationRequired,PermissionRefused,Unavailable,IntegrityConflict,
                     CapacityExceeded,Refused,Busy,ShareOutcomeUnknown,VerificationFailed)

MAX_RESPONSE=48*1024*1024  # bounded JSON envelope including a 32 MiB base64 artifact
SHARE_RECOVERY='Read the current recipients first with client.grants(asset), then decide and call share again with the full intended audience and expected_generation from that snapshot.'


def delay(response):
    try:value=float(response.headers.get('Retry-After','0'))
    except ValueError:return 0
    return value if math.isfinite(value) and 0<=value<=60 else 0


ENVELOPE_LIMIT=16*1024  # an error body is small; never read more of a refusal than this
CODE=re.compile(r'^[A-Za-z0-9_.-]{1,64}$')


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
    return meta


def carried(meta):
    """The error keyword arguments a parsed envelope supplies."""
    return {'remedy':meta.get('remedy'),'docs':meta.get('docs'),'request_id':meta.get('request_id')}


def status(response,operation,raw=None):
    code=response.status_code
    if 200<=code<300:return
    meta=envelope(response,raw)  # E31: first, so every category below keeps the server's metadata
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
    if kind is Busy:raise Busy(message,recovery,status=code,retry_after=delay(response),code=meta.get('code'),**carried(meta))
    if code==413:message=upload_limit(meta) or message
    raise kind(message,recovery,status=code,code=meta.get('code'),**carried(meta))


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
