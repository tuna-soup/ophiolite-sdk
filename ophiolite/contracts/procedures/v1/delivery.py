"""ophiolite.delivery/1 (E109 D3): the one check of the delivery a send procedure's run reports.

The payload is closed: exactly `{delivery_id, state, items}`. `delivery_id` is a uuid4 generated once, before the
writer runs (D2); `state` is one of rules.json's `delivery_states` (`confirmed`, `not-sent`, `unknown`); `items` is a
whole number from 0 to `limits.delivery_items`. A writer's reason text is never part of it (it stays in log.txt).

The Platform and the SDK run this same file (the SDK's copy is byte-identical, contracts/ snapshot), loaded from its
source text as procedure.py is. Standard library only (Python 3.10). The transition rule between states is the
server's (project_gateway.activity); this file only says whether one payload is well formed.
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCHEMA = 'ophiolite.delivery/1'
RULES = json.loads((HERE / 'rules.json').read_text(encoding='utf-8'))
RULES_VERSION = RULES['rules_version']
STATES = tuple(RULES['delivery_states'])
ITEMS = RULES['limits']['delivery_items']
FIELDS = ('delivery_id', 'state', 'items')
DELIVERY_ID = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')


class Invalid(ValueError):
    """A delivery Ophiolite does not accept: `code` keys the sentence in rules.json, `field` is the JSON path."""

    def __init__(self, code, field=''):
        self.code, self.field = code, field
        super().__init__(RULES['sentences'][code])


def check(payload):
    """Raise Invalid for the first defect of a parsed delivery payload; return it otherwise."""
    if not isinstance(payload, dict): raise Invalid('delivery-not-object')
    unknown = sorted(set(payload) - set(FIELDS))
    if unknown: raise Invalid('delivery-unknown-field', '/' + str(unknown[0]))
    for key in FIELDS:
        if key not in payload: raise Invalid('delivery-missing-field', '/' + key)
    if not isinstance(payload['delivery_id'], str) or not DELIVERY_ID.match(payload['delivery_id']): raise Invalid('delivery-bad-id', '/delivery_id')
    if not isinstance(payload['state'], str) or payload['state'] not in STATES: raise Invalid('delivery-bad-state', '/state')
    items = payload['items']
    if not isinstance(items, int) or isinstance(items, bool) or not 0 <= items <= ITEMS: raise Invalid('delivery-bad-count', '/items')
    return payload


def verdict(payload):
    """{'valid': True, 'rules_version'} or {'valid': False, 'rules_version', 'code', 'field', 'sentence'}; never raises
    for a defect of the payload."""
    try:
        check(payload)
        return {'valid': True, 'rules_version': RULES_VERSION}
    except Invalid as error:
        return {'valid': False, 'rules_version': RULES_VERSION, 'code': error.code, 'field': error.field, 'sentence': str(error)}
