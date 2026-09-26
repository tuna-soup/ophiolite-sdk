"""Explicit fixture transport; never installed as a production fallback."""
import base64
import json
from pathlib import Path
import httpx

class FixtureTransport(httpx.MockTransport):
    """Replay ordered public request/response records without authentication material."""
    def __init__(self,recording):
        self.records=json.loads(Path(recording).read_text()) if isinstance(recording,(str,Path)) else recording
        self.index=0
        super().__init__(self.respond)

    def respond(self,request):
        if self.index>=len(self.records):raise AssertionError('Unexpected additional fixture request')
        row=self.records[self.index];self.index+=1
        if request.method!=row['method'] or request.url.raw_path.decode()!=row['path']:
            raise AssertionError('Fixture request differs from the recorded public request')
        return httpx.Response(row['status'],content=base64.b64decode(row['body_base64']),headers=row.get('headers',{}))
