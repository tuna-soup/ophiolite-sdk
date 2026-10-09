"""Notebook display of what was sent or published, with a link back to the Workspace (E104 C2).

Kept out of `exchange.py`, so the portable core stays stdlib-only. The objects behave as the ones they extend
(`to_dict`, attributes, `str` and `repr` unchanged); only `_repr_html_` is added, and it makes no request: the link
comes from values the object holds. An object without context (built elsewhere) shows its name and version only."""
import html
import json
from pydantic import PrivateAttr
from .exchange import Exchange, Outcome
from .links import FAMILY_OF_KIND, item_url
from .models.api import PublicationReceipt
from .repr import _human, technical_vocabulary


def _card(name, number, url, technical, hidden):
    text = lambda value: html.escape(str(value), quote=True)
    shown = _human(name, 'an item', technical_vocabulary() | {str(v) for v in hidden if v})
    link = ('<a href="' + text(url) + '">Open in Workspace</a><details><summary>Copy link</summary>'
            '<input readonly aria-label="Link to this version" value="' + text(url) + '"></details>') if url else ''
    return ('<section aria-label="Result"><strong>' + text(shown) + '</strong>' + ('<p>Version %d</p>' % number if isinstance(number, int) else '')
            + link + '<details><summary>Technical details</summary><pre>' + text(json.dumps(technical, indent=2, allow_nan=False, default=str))
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
        t = self.technical
        return _card(self.facts.get('name'), self.facts.get('number'), _url(self._context, t.get('asset_id'), t.get('revision')),
                     self.to_dict(), (t.get('asset_id'), t.get('revision'), t.get('command_id'), (self._context or {}).get('project')))


class PresentedExchange(Exchange):
    """`Exchange` whose `send` answers a `PresentedOutcome`; `origin` is the Workspace the link opens."""
    def __init__(self, transport, work, *, origin=None, **options):
        Exchange.__init__(self, transport, work, **options)
        self.origin = origin

    def send(self, data, **arguments):
        outcome = Exchange.send(self, data, **arguments)
        context = {'origin': self.origin, 'project': self.transport.project, 'family': FAMILY_OF_KIND['derived'], 'recipe': None} if self.origin else None
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
        return _card((context.get('recipe') or {}).get('name'), self.revision_number, _url(self._context, self.asset_id, self.revision),
                     self.model_dump(mode='json'), (self.asset_id, self.revision, self.command_id, self.profile, context.get('project')))
