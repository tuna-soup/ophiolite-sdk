"""E94: a story page (`results/story` or `results/dependents`) as plain lines, the way `ophiolite story` prints it.

The same JSON gives the same lines in the Workspace (its test asserts tests/fixtures/story/story-lines.txt). Identifiers
stay out of the lines: they are under `technical` in the JSON (`--json`)."""

NOT_RECORDED = 'Not recorded'
RESTRICTED = {'ophiolite.story/1': 'Some earlier steps are not shown because you cannot open them.',
              'ophiolite.dependents/1': 'Some results made from this are not shown because you cannot open them.'}
LONG = 'This history is long. Open one of these results to continue:'


def _title(node):
    return (node.get('name') or NOT_RECORDED) + (', version %d' % node['version'] if node.get('version') else '')


def _day(at):
    return at[:10] if isinstance(at, str) and at else NOT_RECORDED


def details(node, names):
    """The lines under one node's title."""
    who = lambda ident: (names.get(ident) or ident) if ident else NOT_RECORDED
    kind, made, method = node['kind'], node.get('made') or {}, node.get('method')
    out = []
    if kind == 'declared' or made.get('reported_by'):
        out.append('Reported by %s; Ophiolite did not run this calculation.' % who(made.get('reported_by')))
        if method: out.append(method['display'] + '.' if method['display'].startswith('Method') else 'Method: %s.' % method['display'])
    elif kind == 'edited':
        out.append('Corrected by hand by %s on %s.' % (who(made.get('by')), _day(made.get('at'))))
    elif kind == 'original':
        added = 'A file added by %s on %s' % (who(made.get('by')), _day(made.get('at')))
        out.append(added + (': %s.' % node['file'] if node.get('file') else '.'))
    elif kind == 'executed':
        if made.get('by_kind') == 'person' or made.get('by'): by = who(made.get('by'))
        else: by = made.get('by_name') or ('an agent' if made.get('by_kind') == 'agent' else NOT_RECORDED)
        behalf = ', on behalf of %s,' % who(made['on_behalf_of']) if made.get('on_behalf_of') else ''
        out.append('Made by %s%s on %s.' % (by, behalf, _day(made.get('at'))))
        out.append('Through %s.' % made['through'] if made.get('through') else 'Through: %s.' % NOT_RECORDED)
        if method: out.append('Made with %s, %s, %s.' % (method['display'], method['version_label'], method['release']))
    elif kind == 'not-recorded':
        out.append('How this was made was not recorded.')
    if node.get('settings'):
        out.append('Settings: ' + '; '.join('%s: %s%s' % (s['label'], s['value'], ' ' + s['unit'] if s.get('unit') else '') for s in node['settings']) + '.')
    if node.get('history'): out.append(node['history'] + ('' if node['history'].endswith('.') else '.'))
    again = node.get('made_again_from')
    if again: out.append('Made again from %s.' % _title(again))
    if node.get('newer_input'): out.append('Newer input available.')
    return out


def lines(page):
    """The page as a tree: each node once (a node reached again reads "(shown above)"), children in the order given."""
    names = (page.get('display') or {}).get('member_names') or {}
    nodes = {n['id']: n for n in page['nodes']}
    follow = 'dependents' if page['schema'] == 'ophiolite.dependents/1' else 'inputs'
    out, seen = [], set()

    def walk(ident, depth):
        node = nodes.get(ident)
        if node is None: return  # on a later page
        pad = '  ' * depth
        if ident in seen:
            out.append(pad + _title(node) + ' (shown above)'); return
        seen.add(ident)
        out.append(pad + _title(node))
        out.extend(pad + '  ' + line for line in details(node, names))
        for link in node.get(follow) or []: walk(link['id'], depth + 1)

    walk(page['root'], 0)
    for node in page['nodes']:
        if node['id'] not in seen: walk(node['id'], 0)
    if page.get('restricted'): out.append(RESTRICTED[page['schema']])
    if page.get('continue_from'):
        out.append(LONG)
        out.extend('  ' + _title(c) for c in page['continue_from'])
    if page.get('next_cursor'): out.append('More on the next page.')
    return out
