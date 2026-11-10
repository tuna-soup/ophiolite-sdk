"""E144 s3 (C2): the data rules' results of one exact version, as the server stored them at landing, and their words.

`client.rule_results(asset_id, revision)` answers `{asset_id, revision, results, lines}`: `results` is the
`ophiolite.rule-results/1` block (null when the version landed before rules ran) and `lines` one plain sentence per
result, worded by the server from the rule documents the block ran under (null when it cannot word them). A version you
cannot read answers as an unknown one. `summary(block)` is the one-line count (D9, the R-W1 ruling of 4 Nov), and
`local_lines(block)` words a block `ophiolite.rules.run` made on this computer, from this package's own rule snapshot,
in the server's form (D10); nothing here edits `ophiolite.rules` (D6).
"""
import re

NO_RESULTS = 'No rule results for this version: it landed before rules ran.'
NO_RULES = 'No rule reads this kind of file.'
NO_WORDS = 'These results cannot be shown in words; see Technical details.'
REASON_WORDS = {'no-column': 'it needs a column this file does not have', 'no-context': 'it needs other data in the project',
                'offline': 'it runs only on the server'}  # the Gateway's data_rules.REASON_WORDS, word for word


class RuleResultsClient:
    def rule_results(self, asset_id, revision):
        """The rules' results stored with this exact version, and one line per result."""
        return self._post('rule-results', 'get', {'asset_id': asset_id, 'revision': revision}, retry=True)


def summary(block):
    """"Checked by N rules: P passed, F failed, A did not apply." for a block with results."""
    states = [r['state'] for r in block['results']]
    count = len(states)
    return 'Checked by %d rule%s: %d passed, %d failed, %d did not apply.' % (
        count, '' if count == 1 else 's', states.count('passed'), states.count('failed'), states.count('not-applicable'))


def text(block, lines):
    """The words `ophiolite tools rules show|run` print: the summary, then each line; the neutral sentence without lines."""
    if block is None: return NO_RESULTS
    if not block['results']: return NO_RULES
    if lines is None: return '\n'.join([summary(block), NO_WORDS])
    return '\n'.join([summary(block)] + [line['sentence'] for line in lines])


def local_lines(block):
    """[{rule, state, sentence}] for a block run here, from this package's rule snapshot; None when a rule is missing."""
    from .rules import _registry
    version, rules = _registry()
    if block.get('registry_version') != version: return None
    found = {r['id']: r for r in rules}
    if any(result['rule'] not in found for result in block['results']): return None
    return [{'rule': r['rule'], 'state': r['state'], 'sentence': sentence(found[r['rule']], r)} for r in block['results']]


def sentence(rule, result):
    if result['state'] == 'failed': return _words(rule, result)
    if result['state'] == 'passed': return '%s: passed.' % rule['title']
    reason = REASON_WORDS.get(result.get('reason'))
    return '%s: did not apply; %s.' % (rule['title'], reason) if reason else '%s: did not apply.' % rule['title']


def _number(value):
    return str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)


def _words(rule, result):
    """The rule's title and its template rendered from the result, at most 300 characters (the Gateway's
    rule_runs.words, so a file checked here reads as the same file checked at landing)."""
    examples, parameters = rule['words']['examples'], {p['name']: p for p in rule['parameters']}
    first = result['examples'][0] if result['examples'] else None

    def one(match):
        token, name = match.group(0), match.group(1)
        if token in ('{{', '}}'): return token[0]
        if name == 'count': return str(result['count'])
        if name == 'first':
            if first is None: return ''
            return 'row %d' % first['row'] if examples == 'rows' else 'depth ' + _number(first['depth'])
        p = parameters[name]
        return _number(result['parameters'][name]) + (' ' + p['unit'] if p.get('unit') else '')
    return ('%s: %s' % (rule['title'], re.sub(r'\{\{|\}\}|\{(\w+)\}', one, rule['words']['template'])))[:300]
