"""Notebook display of what was sent or published, with a link back to the Workspace (E104 C2).

Kept out of `exchange.py`, so the portable core stays stdlib-only. The objects behave as the ones they extend
(`to_dict`, attributes, `str` and `repr` unchanged); only `_repr_html_` is added, and it makes no request: the link
comes from values the object holds. An object without context (built elsewhere) shows its name and version only.

"Send again" (C3) is the call as one Python line, from a snapshot of every argument taken at call time, pinned to the
version it builds on (`expected`), so it refuses once the folder holds a newer one."""
import copy
import html
import json
import math
from pydantic import PrivateAttr
from .exchange import Exchange, Outcome
from .links import FAMILY_OF_KIND, item_url
from .models.api import PublicationReceipt
from .repr import _human, technical_vocabulary


SEND_AGAIN = ('Runs the same send with a new file: <code>ex</code> is this folder\'s exchange and <code>new_file</code> the '
              'new file. It adds the next version only while this folder still holds this one.')
SEND_NEW = ('Runs the same send with a new file: <code>ex</code> is this folder\'s exchange and <code>new_file</code> the '
            'new file. It sends another new item.')
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


def _card(name, number, url, technical, hidden, recipe=None, note=''):
    text = lambda value: html.escape(str(value), quote=True)
    shown = _human(name, 'an item', technical_vocabulary() | {str(v) for v in hidden if v})
    link = ('<a href="' + text(url) + '">Open in Workspace</a><details><summary>Copy link</summary>'
            '<input readonly aria-label="Link to this version" value="' + text(url) + '"></details>') if url else ''
    return ('<section aria-label="Result"><strong>' + text(shown) + '</strong>' + ('<p>Version %d</p>' % number if isinstance(number, int) else '')
            + link + ('<details><summary>Send again</summary><p>' + note + '</p><pre>' + text(recipe) + '</pre></details>' if recipe else '')
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
        return _card(((context.get('recipe') or {}).get('arguments') or {}).get('name'), self.revision_number, _url(self._context, self.asset_id, self.revision),
                     self.model_dump(mode='json'), (self.asset_id, self.revision, self.command_id, self.profile, context.get('project')))
