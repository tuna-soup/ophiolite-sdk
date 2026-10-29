"""Notebook display of what was sent or published, with a link back to the Workspace (E104 C2).

Kept out of `exchange.py`, so the portable core stays stdlib-only. The objects behave as the ones they extend
(`to_dict`, attributes, `str` and `repr` unchanged); only `_repr_html_` is added, and it makes no request: the link
comes from values the object holds. An object without context (built elsewhere) shows its name and version only.

"Send again" (C3) is the call as one Python line, from a snapshot of every argument taken at call time, pinned to the
version it builds on (`expected`), so it refuses once the folder holds a newer one.

"Run again" (E112 s3) is the same for a run on this computer, pinned to the procedure digest that ran, and for a
finished recipe; the results stay dicts, equal to the plain ones."""
import copy
import html
import json
import math
import os
import uuid
from pydantic import PrivateAttr
from .exchange import Exchange, Outcome
from .links import FAMILY_OF_KIND, item_url
from .models.api import PublicationReceipt
from .repr import _human, technical_vocabulary


SEND_AGAIN = ('Runs the same send with a new file: <code>ex</code> is this folder\'s exchange and <code>new_file</code> the '
              'new file. It adds the next version only while this folder still holds this one.')
SEND_NEW = ('Runs the same send with a new file: <code>ex</code> is this folder\'s exchange and <code>new_file</code> the '
            'new file. It sends another new item.')
PUBLISH_AGAIN = ('Publishes the next version with a new file: <code>client</code> is your client and <code>new_written</code> '
                 'the new file you wrote. It adds the next version only while this is still the latest; running it again '
                 'after a lost answer returns the same receipt.')
RECIPE_LIMIT = 4096


def _plain(value):
    if value is None or isinstance(value, (bool, int, str)): return True
    if isinstance(value, float): return math.isfinite(value)
    if isinstance(value, (list, tuple)): return all(_plain(v) for v in value)
    if isinstance(value, dict): return all(isinstance(k, str) and _plain(v) for k, v in value.items())
    return False


def _lists(value):
    if isinstance(value, (list, tuple)): return [_lists(v) for v in value]
    if isinstance(value, dict): return {k: _lists(v) for k, v in value.items()}
    return value


def send_again(arguments, asset, revision):
    """The "Send again" line for a send made with `arguments` whose result is `asset` at `revision`; None when an
    argument is not plain data or the line would pass RECIPE_LIMIT characters."""
    if not _plain(arguments): return None
    line = dict(arguments)
    if line.get('of') is not None: line['of'], line['expected'] = asset, revision
    else: line.pop('of', None); line.pop('expected', None)
    order = ('name', 'profile', 'how', 'based_on', 'of', 'declare', 'extra', 'expected')
    text = 'ex.send(new_file, ' + ', '.join('%s=%r' % (k, _lists(line[k])) for k in order if line.get(k) is not None) + ')'
    return text if len(text) <= RECIPE_LIMIT else None


def publication_recipe(*, name, from_, method, of_entity=None):
    """A snapshot of a `publish_derived` call's arguments, taken at call time; None when one is not plain data."""
    from .publish import _parent
    try:
        items = from_ if isinstance(from_, (list, tuple)) and not (len(from_) == 2 and isinstance(from_[0], str)) else [from_]
        arguments = {'name': name, 'from_': [[p['asset_id'], p['revision']] for p in map(_parent, items)],
                     'method': method.model_dump() if hasattr(method, 'model_dump') else dict(method),
                     'of_entity': dict(of_entity) if of_entity is not None else None}
        return {'call': 'publish_derived', 'arguments': copy.deepcopy(arguments)}
    except Exception:
        return None


def publish_again(arguments, asset, revision, command_id):
    """The "Publish again" line: the next version of `asset` on `revision`, under the minted `command_id`."""
    if not _plain(arguments): return None
    line = {**arguments, 'command_id': command_id, 'new_version_of': asset, 'expected_parent': revision}
    order = ('name', 'from_', 'method', 'of_entity', 'command_id', 'new_version_of', 'expected_parent')
    text = 'client.publish_derived(new_written, ' + ', '.join('%s=%r' % (k, _lists(line[k])) for k in order if line.get(k) is not None) + ')'
    return text if len(text) <= RECIPE_LIMIT else None


def _card(name, number, url, technical, hidden, recipe=None, note='', again='Send again', said=(), title=None):
    text = lambda value: html.escape(str(value), quote=True)
    shown = title or _human(name, 'an item', technical_vocabulary() | {str(v) for v in hidden if v})  # `title`: a person's label, checked by the caller
    link = ('<a href="' + text(url) + '">Open in Workspace</a><details><summary>Copy link</summary>'
            '<pre>' + text(url) + '</pre></details>') if url else ''  # E104 C8: JupyterLab disables an input in an untrusted output
    return ('<section aria-label="Result"><strong>' + text(shown) + '</strong>' + ('<p>Version %d</p>' % number if isinstance(number, int) else '')
            + ''.join('<p>' + text(line) + '</p>' for line in said)
            + link + ('<details><summary>' + again + '</summary><p>' + note + '</p><pre>' + text(recipe) + '</pre></details>' if recipe else '')
            + '<details><summary>Technical details</summary><pre>' + text(json.dumps(technical, indent=2, allow_nan=False, default=str))
            + '</pre></details></section>')


def _url(context, asset, revision):
    if not context or not asset or not revision: return None
    return item_url(context['origin'], context['project'], context['family'], asset, revision)


class PresentedOutcome(Outcome):
    """An Exchange outcome that can show itself in a notebook."""
    def __init__(self, outcome, sentence, facts=None, technical=None, context=None):
        Outcome.__init__(self, outcome, sentence, facts, technical)
        self._context = context

    def _repr_html_(self):
        t, context = self.technical, self._context or {}
        recipe = context.get('recipe') or {}
        line = send_again(recipe['arguments'], t.get('asset_id'), t.get('revision')) if recipe.get('call') == 'send' and t.get('revision') else None
        return _card(self.facts.get('name'), self.facts.get('number'), _url(self._context, t.get('asset_id'), t.get('revision')),
                     self.to_dict(), (t.get('asset_id'), t.get('revision'), t.get('command_id'), context.get('project')),
                     line, SEND_AGAIN if recipe.get('arguments', {}).get('of') is not None else SEND_NEW)


class PresentedExchange(Exchange):
    """`Exchange` whose `send` answers a `PresentedOutcome`; `origin` is the Workspace the link opens."""
    def __init__(self, transport, work, *, origin=None, **options):
        Exchange.__init__(self, transport, work, **options)
        self.origin = origin

    def send(self, data, **arguments):
        try: snapshot = copy.deepcopy(arguments)  # later changes to the caller's lists and dicts do not reach the line
        except Exception: snapshot = None
        outcome = Exchange.send(self, data, **arguments)
        recipe = {'call': 'send', 'arguments': snapshot} if snapshot is not None else None
        context = {'origin': self.origin, 'project': self.transport.project, 'family': FAMILY_OF_KIND['derived'], 'recipe': recipe} if self.origin else None
        return PresentedOutcome(outcome.outcome, outcome.sentence, outcome.facts, outcome.technical, context)


class PresentedReceipt(PublicationReceipt):
    """A `PublicationReceipt` that can show itself in a notebook; the context is private, so `model_dump` is unchanged."""
    _context: dict | None = PrivateAttr(default=None)

    @classmethod
    def present(cls, receipt, context=None):
        presented = cls.model_construct(receipt.model_fields_set, **dict(receipt))  # already validated; extras kept
        presented._context = context
        return presented

    def __repr__(self): return 'PublicationReceipt(' + self.__repr_str__(', ') + ')'

    def _repr_html_(self):
        context = self._context or {}
        recipe = context.get('recipe') or {}
        line = None
        if recipe.get('call') == 'publish_derived':
            minted = context.setdefault('minted', uuid.uuid4().hex)  # once per receipt: re-rendering shows the same line
            line = publish_again(recipe['arguments'], self.asset_id, self.revision, minted)
        return _card((recipe.get('arguments') or {}).get('name'), self.revision_number, _url(self._context, self.asset_id, self.revision),
                     self.model_dump(mode='json'), (self.asset_id, self.revision, self.command_id, self.profile, context.get('project')), line, PUBLISH_AGAIN)


# -- "Run again" (E112 s3): a run or a recipe on this computer, as one line from a snapshot taken when the call began --

RUN_AGAIN = ('Runs the same procedure version again: <code>procedures</code> is <code>ophiolite.procedures</code> and '
             '<code>new_output</code> a new folder for its outputs. It runs only while the procedure folder still holds the '
             'version that ran.')
RECIPE_AGAIN = ('Runs the recipe file as it is now in a new work folder <code>new_work</code>; you are asked again about any '
                'version you have not trusted.')
NO_LINE = {'project': 'No Run again here: this run read project versions, downloaded for this run only and removed after it.',
           'plain': 'No Run again here: one of its arguments is not plain text, numbers, lists or dicts, so it cannot be written as one line.',
           'long': 'No Run again here: the call would be longer than 4,096 characters.'}
STEP_WORDS = {'residuals': 'Residual report', 'publish': 'Publish the result', 'states': 'Outcome states', 'deliver': 'Deliver'}


def _text(value): return os.fspath(value) if isinstance(value, os.PathLike) else value


def _line(head, arguments, order):
    """`head` and the arguments that are set as one line, or (None, why) when one is not plain or the line too long."""
    if not _plain(arguments): return None, NO_LINE['plain']
    text = head + ''.join(', %s=%r' % (k, _lists(arguments[k])) for k in order if arguments.get(k) is not None) + ')'
    return (text, None) if len(text) <= RECIPE_LIMIT else (None, NO_LINE['long'])


def run_again(call, digest):
    """The "Run again" line for `procedures.run` called with `call` (its snapshot), pinned to `digest`: (line, None) or
    (None, the sentence that says why there is none)."""
    from .procedures import ProjectInput
    try:
        if any(isinstance(p, ProjectInput) for paths in (call['inputs'] or {}).values() for p in paths): return None, NO_LINE['project']
        arguments = {'inputs': None if call['inputs'] is None else {slot: [_text(p) for p in paths] for slot, paths in call['inputs'].items()},
                     'systems': None if call['systems'] is None else {slot: _text(p) for slot, p in call['systems'].items()},
                     'declared': None if call['declared'] is None else {slot: _text(v) for slot, v in call['declared'].items()},  # a file, or the dict
                     'kinds': call['kinds'], 'settings': call['settings'], 'expected_digest': digest}
        return _line('procedures.run(%r, new_output' % _text(call['folder']), arguments,
                     ('inputs', 'kinds', 'declared', 'systems', 'settings', 'expected_digest'))
    except Exception:
        return None, NO_LINE['plain']


class PresentedRun(dict):
    """The result of `procedures.run` (a dict, equal to the plain one) that shows itself in a notebook: the run in words,
    a "Run again" line (or why there is none) and the result under Technical details."""
    @classmethod
    def present(cls, result, call, label):
        presented = cls(result)
        presented._call, presented._label = call, label
        return presented

    def _again(self):
        return run_again(self._call, self['run']['procedure'].get('digest')) if self._call is not None else (None, NO_LINE['plain'])

    @property
    def again(self):
        """The "Run again" line the card shows, as text, or None."""
        return self._again()[0]

    def _repr_html_(self):
        from .procedures import contract
        procedure = self['run']['procedure']
        hidden = {procedure.get('name'), procedure.get('digest'), self.get('destination'), (self._call or {}).get('folder')}
        label = _human(self._label, 'A procedure', {str(v) for v in hidden if v})  # the person's label; contract words may be in it
        if 'report' in self:
            did = {'passed': 'passed', 'differed': 'differed', 'not_compared': 'not compared'}.get(self['report'].get('outcome'), 'checked')
        else:
            words = contract().RULES['kind_words']
            did = 'made ' + ', '.join(words.get(o['profile'], 'a file') for o in self['run']['outputs'].values())
        said = ['Ran %s, version %s, on this computer: %s. Nothing was published.' % (label, procedure.get('version'), did)]
        line, why = self._again()
        return _card(label, None, None, dict(self), hidden, line, RUN_AGAIN, 'Run again', said + ([why] if why else []), label)


class PresentedRecipe(dict):
    """The result of `recipe_runs.run` (a dict, equal to the plain one) that shows itself in a notebook: its steps in
    words and, once finished, a "Run again" line that never carries `yes`, `set_aside` or `wait`."""
    @classmethod
    def present(cls, result, call, name):
        presented = cls(result)
        presented._call, presented._name = call, name
        return presented

    def _again(self):
        if self['state'] != 'finished': return None, None  # its sentence already says to run the same command again (s2)
        try: head, arguments = ('recipe_runs.run(client, %r, new_work' % _text(self._call['recipe']),
                                {'inputs': None if self._call['inputs'] is None else {k: _text(v) for k, v in self._call['inputs'].items()}})
        except Exception: return None, NO_LINE['plain']
        return _line(head, arguments, ('inputs',))

    @property
    def again(self):
        """The "Run again" line the card shows, as text, or None."""
        return self._again()[0]

    def _repr_html_(self):
        from .recipe_runs import WORDS
        steps = self['steps']
        hidden = {self.get('work'), (self._call or {}).get('recipe')} | {s.get('folder') for s in steps}
        name = self._name if isinstance(self._name, str) and ' ' in self._name.strip() else None  # one word, `a-name-2`: an identifier
        name = _human(name, 'A recipe', {str(v) for v in hidden if v})
        stopped = next((n for n, s in enumerate(steps, 1) if s['state'] not in ('finished', 'set_aside')), None)
        if self['state'] == 'finished' or stopped is None:
            said = ['Finished: all %d steps.' % len(steps)]
        else:
            what = STEP_WORDS.get(steps[stopped - 1]['step'], 'A step')
            said = ['Stopped at step %d of %d (%s). Run the same command again to %s.' % (
                stopped, len(steps), what, 'ask again' if self['state'] == 'unknown' else 'continue')]
        said += ['%d. %s: %s' % (n, STEP_WORDS.get(s['step'], 'A step'), WORDS.get(s['state'], 'Needs attention')) for n, s in enumerate(steps, 1)]
        line, why = self._again()
        return _card(name, None, None, dict(self), hidden, line, RECIPE_AGAIN, 'Run again', said + ([why] if why else []), name)
