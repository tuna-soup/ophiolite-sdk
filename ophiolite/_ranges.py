"""E100d1 A4: reading a stored file by byte ranges, shared by Client and AsyncClient (and download_original, E54).
A deployment serves one representation whole only up to WHOLE_BYTES; a larger one is read in parts. Each part must
start where the last ended, state the same total and the same file digest, and not be empty; the whole digest is
checked by the caller against what it expected."""
import hashlib
import re
from .errors import VerificationFailed

WHOLE_BYTES=32*1024*1024  # the largest answer a deployment gives without a Range (Platform RESULT_BYTES)
PART_BYTES=8*1024*1024
OTHER_PART='The deployment answered another part of the file.'


def content_range(value):
    """(first byte, total) of a `Content-Range: bytes a-b/N` answer."""
    match=re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',value or '')
    if match is None:raise VerificationFailed('The deployment did not say which bytes it sent.')
    return int(match.group(1)),int(match.group(3))


class Parts:
    """The state of one ranged read: ask `range()` while `pending()`, hand each answer to `accept`."""
    def __init__(self,part_bytes=None,*,size=None):
        self.part_bytes,self.at,self.size,self.expected,self.whole=part_bytes or PART_BYTES,0,size,None,hashlib.sha256()

    def pending(self):return self.size is None or self.at<self.size

    def range(self):return 'bytes=%d-%d'%(self.at,self.at+self.part_bytes-1)

    def accept(self,raw,answer):
        first,total=content_range(answer.get('content-range'))
        stated=answer.get('x-content-sha256')
        if first!=self.at or (self.size is not None and total!=self.size) or (self.expected is not None and stated!=self.expected) or not raw or self.at+len(raw)>total:
            raise VerificationFailed(OTHER_PART)
        self.size,self.expected=total,stated
        self.whole.update(raw);self.at+=len(raw)
        return raw

    def digest(self):return self.whole.hexdigest()
