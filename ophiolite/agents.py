"""An agent's side of Ophiolite (E5): propose exact changes, wait for approval, execute, recover.

An agent credential (`oph_agent_…`) is issued by a person in Workspace Settings → Agents and
acts for that person with narrower scopes, budgets and an expiry. Reads work directly. Every
change is proposed first; the gateway hashes the exact request, the person (or their policy)
approves it, and the agent then executes that same request with the plan. If the response is
lost, `recover()` returns what was recorded; executing the same plan again returns the same
response and never runs twice.

    agent = AgentClient('https://ophiolite.example', 'project-id', credential)
    run = agent.run('applications/start', {'id': binding, 'generation': 1, 'command_id': 'run-1',
                                           'application_version': 'my-script/1'})
"""
import time
import httpx
from .errors import (OphioliteError, AuthenticationRequired, PermissionRefused, Unavailable, IntegrityConflict,
                     Refused, Busy)

CHANGES = ('applications/configure', 'applications/start', 'applications/publish', 'applications/share', 'runners/submit', 'runners/cancel')


class PlanDeclined(OphioliteError): code = 'plan-declined'
class PlanExpired(OphioliteError): code = 'plan-expired'
class BudgetExhausted(OphioliteError): code = 'budget-exhausted'
class CommandOwned(IntegrityConflict): code = 'command-owned'


class AgentClient:
    def __init__(self, base_url, project, credential, *, http=None):
        """`credential` is an agent key (`oph_agent_…`) or, for an assistant acting through your own
        sign-in, the saved credential from `device_login(..., assistant='name')`."""
        from .auth import Credential
        self.url, self.project = base_url.rstrip('/'), project
        self.http = http or httpx.Client(timeout=60, follow_redirects=False, trust_env=False)
        if isinstance(credential, Credential):
            self._credential, self._headers = credential, None
        elif isinstance(credential, str) and credential.startswith('oph_agent_'):
            self._credential, self._headers = None, {'Authorization': 'Bearer ' + credential}
        else:
            raise AuthenticationRequired('Use the agent credential shown once in Settings → Agents, or an assistant sign-in.')

    def _auth(self):
        return self._credential.headers(self.url, self.project) if self._credential else self._headers

    def _post(self, area, operation, body, plan=None):
        headers = {**self._auth(), **({'X-Ophiolite-Plan': plan} if plan else {})}
        try:
            response = self.http.post('%s/api/v1/projects/%s/%s/%s' % (self.url, self.project, area, operation),
                                      json={'project_id': self.project, **body}, headers=headers)
        except httpx.HTTPError:
            raise Unavailable('Cannot reach the service. Check its address and network connection.', code='unreachable') from None
        if response.status_code == 200: return response.json()
        try: payload = response.json()
        except ValueError: payload = {}
        code, message = payload.get('code', ''), payload.get('error') or 'The request was refused.'
        kind = {'budget-exhausted': BudgetExhausted, 'command-owned': CommandOwned}.get(code)
        if kind is None:
            kind = {401: AuthenticationRequired, 403: PermissionRefused, 404: Unavailable, 409: IntegrityConflict,
                    429: BudgetExhausted, 503: Busy}.get(response.status_code, Refused)
        raise kind(message, status=response.status_code, code=code or None)

    def read(self, operation, body=None):
        """A read operation such as 'applications/result-list'; reads need no plan."""
        area, name = operation.split('/', 1)
        return self._post(area, name, body or {})

    def capabilities(self):
        """What this agent may ask for: every operation with eligibility, whether it needs a plan,
        the agent's scopes, budgets (used by the admission rule) and expiry, and the MCP endpoint."""
        return self._post('capabilities', 'describe', {})

    def mcp_settings(self):
        """The address and header an MCP client needs to use this agent key over the remote MCP endpoint.
        (An assistant's MCP client signs in itself; its access token expires and is refreshed by that client.)"""
        if self._headers is None: raise Refused('An assistant\'s MCP client signs in itself; no key is handed over.')
        return mcp_settings(self.url, self._headers['Authorization'][7:])

    def propose(self, operation, request, summary=''):
        if operation not in CHANGES: raise Refused('Agents change application configurations, runs, publications, recipients and runner jobs only.')
        return self._post('agents', 'propose', {'operation': operation, 'request': {'project_id': self.project, **request}, 'summary': summary})

    def status(self, plan):
        return self._post('agents', 'status', {'hash': plan})['state']

    def wait(self, plan, *, timeout=3600, interval=5, clock=time.monotonic, sleep=time.sleep):
        """Until the person decides: returns on approval, raises when declined or expired."""
        deadline = clock() + timeout
        while True:
            state = self.status(plan)
            if state in ('approved', 'consumed'): return state
            if state == 'declined': raise PlanDeclined('The person declined this plan.')
            if state == 'expired': raise PlanExpired('The plan expired before a decision; propose it again.')
            if clock() >= deadline: raise PlanExpired('No decision within the wait; the plan stays pending.', code='plan-pending')
            sleep(interval)

    def execute(self, operation, request, plan):
        area, name = operation.split('/', 1)
        return self._post(area, name, request, plan)

    def run(self, operation, request, summary='', **wait):
        """Propose, wait for approval, execute. Safe to repeat: the same request is the same plan."""
        plan = self.propose(operation, request, summary)['hash']
        self.wait(plan, **wait)
        return self.execute(operation, request, plan)

    def job(self, job_id):
        """A runner job (E13): state, reason, limits, bounded logs and the published result."""
        return self._post('runners', 'job', {'id': job_id})

    def recover(self, *, command_id=None, plan=None):
        """The recorded outcome of an execution whose response was lost."""
        if bool(command_id) == bool(plan): raise Refused('Name either the command id or the plan.')
        return self._post('agents', 'command', {'command_id': command_id} if command_id else {'plan': plan})


def mcp_settings(base_url, credential):
    """MCP client settings for an agent credential: the streamable HTTP endpoint and its header.
    The credential is sent to that endpoint only; keep the returned value as secret as the key."""
    if not isinstance(credential, str) or not credential.startswith('oph_agent_'):
        raise AuthenticationRequired('Use the agent credential shown once in Settings → Agents.')
    url = base_url.rstrip('/')
    if not url.startswith('https://') and not url.startswith(('http://127.0.0.1', 'http://localhost', 'http://[::1]')):
        raise Refused('Use the HTTPS address of the service (plain HTTP only for this computer).')
    return {'url': url + '/mcp', 'transport': 'streamable-http', 'headers': {'Authorization': 'Bearer ' + credential}}
