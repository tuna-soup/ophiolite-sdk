"""E94: a story page (`results/story` or `results/dependents`) as plain lines, the way `ophiolite story` prints it.

The Workspace words the same JSON in the Journey's sentences with dates in words (its app/tests/story.mjs); these lines
keep ISO dates. Identifiers stay out of the lines: they are under `technical` in the JSON (`--json`)."""

NOT_RECORDED = 'Not recorded'
RESTRICTED = {'ophiolite.story/1': 'Some earlier steps are not shown because you cannot open them.',
              'ophiolite.dependents/1': 'Some results made from this are not shown because you cannot open them.'}
LONG = 'This history is long. Open one of these results to continue:'


def _title(node):
    return (node.get('name') or NOT_RECORDED) + (', version %d' % node['version'] if node.get('version') else '')


def _day(at):
    return at[:10] if isinstance(at, str) and at else NOT_RECORDED


def _through(through):
    """The server sends the sentence ("Through the Python library 0.1.0", E93 `through_words`); an older answer sent the
    bare name. Either reads once as "Through …."."""
    if not through: return 'Through: %s.' % NOT_RECORDED
    return (through if through.startswith('Through ') else 'Through ' + through).rstrip('.') + '.'


UNNAMED = 'an unnamed item'
HIDDEN = 'other inputs you cannot open'


def _readable(text):
    from .procedures import contract
    return contract().labels.readable_label(text) if isinstance(text, str) else None


def _file(name):
    """A plain file name whose stem reads as a name, else None (a path, UUID or hash never reads)."""
    if not isinstance(name, str) or '/' in name or '\\' in name: return None
    stem = name.rsplit('.', 1)[0] if '.' in name[1:] else name
    return name if stem and _readable(stem) else None


def _basis(b):
    """E109 s4 (D2): one basis in words: "the upload FILE (TITLE)", "the map TITLE", "the reference TITLE" or "TITLE"."""
    title = (_readable(b.get('name')) or UNNAMED) + (', version %d' % b['version'] if b.get('version') else '')
    kind = b.get('kind')
    if kind == 'upload':
        file = _file(b.get('file'))
        return 'the upload %s (%s)' % (file, title) if file else 'the upload ' + title
    if kind in ('map', 'reference'): return 'the %s %s' % (kind, title)
    return title


def based_on(node):
    """E109 s4 (D2): "Based on X.", "Based on X and Y.", "Based on X, Y and 2 more.", "Based on X and other inputs you
    cannot open.", "Based on inputs you cannot open."; None when the node names no basis."""
    shown, hidden = [_basis(b) for b in node.get('based_on') or []], bool(node.get('based_on_hidden'))
    if not shown: return 'Based on inputs you cannot open.' if hidden else None
    parts = shown[:2] + (['%d more' % (len(shown) - 2)] if len(shown) > 2 else []) + ([HIDDEN] if hidden else [])
    return 'Based on %s.' % (parts[0] if len(parts) == 1 else ', '.join(parts[:-1]) + ' and ' + parts[-1])


def details(node, names):
    """The lines under one node's title."""
    who = lambda ident: (names.get(ident) or ident) if ident else NOT_RECORDED
    kind, made, method = node['kind'], node.get('made') or {}, node.get('method')
    out = []
    if kind == 'reported':  # E106: made with a catalogue procedure on a person's computer (or by an agent, for its delegator)
        if made.get('by_kind') == 'agent':
            on = 'by %s' % (made.get('by_name') or 'an agent') + (' for %s' % who(made['on_behalf_of']) if made.get('on_behalf_of') else '')
        else: on = "on %s's computer" % who(made.get('reported_by'))
        if method: out.append('Made with %s %s %s; Ophiolite did not run this calculation.' % (method['display'], method['version_label'], on))
    elif kind == 'declared' or made.get('reported_by'):
        out.append('Reported by %s; Ophiolite did not run this calculation.' % who(made.get('reported_by')))
        if method: out.append(method['display'] + '.' if method['display'].startswith('Method') else 'Method: %s.' % method['display'])
        basis = based_on(node)
        if basis: out.append(basis)  # E109 s4 (D5): after the method line, before "Made again from"
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
        out.append(_through(made.get('through')))
        if method: out.append('Made with %s, %s, %s.' % (method['display'], method['version_label'], method['release']))
    elif kind == 'not-recorded':
        out.append('How this was made was not recorded.')
    if node.get('settings'):
        out.append('Settings: ' + '; '.join('%s: %s%s' % (s['label'], s['value'], ' ' + s['unit'] if s.get('unit') else '') for s in node['settings']) + '.')
    if node.get('history'): out.append(node['history'] + ('' if node['history'].endswith('.') else '.'))
    again = node.get('made_again_from')
    if again: out.append('Made again from %s.' % _title(again))
    if node.get('newer_input'): out.append('Newer input available.')
    out.extend(v['line'] for v in node.get('verdicts') or [])  # E132: the server's line, verbatim (a reason keeps its newlines)
    return out


SOMEONE = 'a project member'
NOT_REPORTED = 'allowed to be delivered; no delivery reported yet'  # E120 s7: the Workspace's words for a claim with no delivery yet


def _state(o):
    """E120 s7: an outcome's state line as `outcomes/states` serves it; a rejected head reads as the Workspace result page
    reads it (E121 P7, P10: the line says what a version is), and a line that does not name its outcome gets the outcome's
    name."""
    line, head = o['line'], 'Rejected under %s version %d: ' % (o['label'], o['version'])
    if o['state'] == 'rejected' and line.startswith(head):
        return 'Fails the outcome "%s", declared at version %d (a change to its rule makes a new version): %s' % (
            o['label'], o['version'], line[len(head):])
    return line if o['label'] in line else '%s: %s' % (o['label'], line)


def _claim(c, o, names):
    said = NOT_REPORTED if c['state'] == 'claimed' else c['line']
    by = ' (by an agent for %s)' % (names.get(c.get('person')) or SOMEONE) if c.get('agent') else ''
    return 'Delivered as %s version %d: %s%s.' % (c.get('label') or o['label'], c['version'], said, by)


def outcome_lines(node, states, names):
    """E120 s7: the root version's outcome lines, in the Workspace result page's words (`OutcomeLines.tsx`): per current
    outcome its state, its earlier publications and versions, and the node's "Deliver as" claims for it."""
    out = []
    for o in (states or {}).get('outcomes') or []:
        out.append(_state(o))
        out += o.get('earlier_publications', []) + o.get('earlier_versions', [])
        out += [_claim(c, o, names) for c in node.get('outcomes') or [] if c.get('outcome_id') == o['outcome_id']]
    return out


def lines(page, states=None):
    """The page as a tree: each node once (a node reached again reads "(shown above)"), children in the order given.
    E120 s7: `states` (an `outcomes/states` answer for the root version) adds its outcome lines after the root's own."""
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
        if ident == page['root']: out.extend(pad + '  ' + line for line in outcome_lines(node, states, names))
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
