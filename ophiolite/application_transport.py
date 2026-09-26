"""Shared application response/retry policy for sync and async HTTP drivers."""
import json
import math
from .errors import (AuthenticationRequired,PermissionRefused,Unavailable,IntegrityConflict,
                     CapacityExceeded,Refused,Busy,ShareOutcomeUnknown,VerificationFailed)

MAX_RESPONSE=48*1024*1024  # bounded JSON envelope including a 32 MiB base64 artifact
SHARE_RECOVERY='Read the current recipients first with client.grants(asset), then decide and call share again with the full intended audience and expected_generation from that snapshot.'


def delay(response):
    try:value=float(response.headers.get('Retry-After','0'))
    except ValueError:return 0
    return value if math.isfinite(value) and 0<=value<=60 else 0


def status(response,operation):
    code=response.status_code
    if 200<=code<300:return
    if operation=='share' and code>=500:
        raise ShareOutcomeUnknown('The sharing outcome is unknown.',SHARE_RECOVERY,status=code)
    if operation=='share' and code==409:
        raise IntegrityConflict('The recipients changed since you read them.',SHARE_RECOVERY,status=code)
    kind,message={401:(AuthenticationRequired,'Sign in again.'),403:(PermissionRefused,'Check project access and the approved grant.'),
        404:(Unavailable,'The requested application data is unavailable or not permitted.'),
        409:(IntegrityConflict,'The request conflicts with the stored result.'),
        413:(CapacityExceeded,'This operation exceeds its supported size.'),
        429:(Busy,'The service is busy.'),503:(Busy,'The service is busy.')}.get(code,(Refused,'The application request was refused. Check the input and supported profile.'))
    if kind is Busy:raise Busy(message,status=code,retry_after=delay(response))
    raise kind(message,status=code)


def decode(raw):
    def invalid(value):raise ValueError('nonfinite')
    try:value=json.loads(raw,parse_constant=invalid)
    except (ValueError,UnicodeError):raise VerificationFailed('The application response is not finite JSON.') from None
    if not isinstance(value,dict):raise VerificationFailed('The application response must be an object.')
    return value


def disconnected(operation):
    if operation=='share':raise ShareOutcomeUnknown('The sharing outcome is unknown.',SHARE_RECOVERY)
    raise Unavailable('The application response did not arrive. Keep the work folder and recover the same request.',code='outcome-unknown')
