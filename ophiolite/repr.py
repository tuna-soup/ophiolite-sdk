"""Human notebook display with explicit technical disclosure; all content escaped."""
import html
import json
import re
from functools import lru_cache
from importlib.resources import files
from .models.invariants import registry


@lru_cache(maxsize=1)
def technical_vocabulary():
    """All declared contract enums/constants plus profile and schema identities."""
    root=files('ophiolite').joinpath('contracts')
    source=json.loads(root.joinpath('SOURCE.json').read_text())
    terms=set(registry()[1])
    def visit(value):
        if isinstance(value,dict):
            terms.update(item for item in value.get('enum',[]) if isinstance(item,str))
            if isinstance(value.get('const'),str):terms.add(value['const'])
            for child in value.values():visit(child)
        elif isinstance(value,list):
            for child in value:visit(child)
    for name in source['files']:
        if name.endswith('schema.json'):
            visit(json.loads(root.joinpath(name).read_text()))
    terms.update(row['id'] for row in registry()[0]['schemas'])
    return frozenset(terms)


def _human(value,fallback,technical):
    if not isinstance(value,str) or not value.strip():return fallback
    if any(re.search(r'(?<![A-Za-z0-9])'+re.escape(item)+r'(?![A-Za-z0-9])',value) for item in technical if item):return fallback
    if re.search(r'[0-9a-f]{32,}|[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}|(?:[a-z][a-z0-9.-]*/)+[0-9]+\b|[<>\x00-\x1f]',value):return fallback
    return value


def descriptor_html(meta):
    technical={meta.asset_id,meta.revision,meta.project,meta.authority,meta.origin,meta.profile,meta.evidence,meta.axis.order,meta.artifact_sha256}
    technical.update(meta.curve_sha256.values());technical.update(registry()[1])
    technical.update(technical_vocabulary())
    technical.update(str(value) for value in meta.interpretation.values())
    title=_human(meta.display.get('type'),meta.display_name,technical)
    held=_human(meta.display.get('held_as'),'Scientific curve data',technical)
    normalized=registry()[1][registry()[1][meta.profile]['normalized_profile']]['display_name']
    evidence={'live':'Read with the current reader','recorded':'Matches the saved reader record',
              'recorded-differs':'The current reader differs from the saved record','not-recorded':'Earlier reader details were not recorded','not-available':'Reader history is unavailable'}.get(meta.evidence,'Reader history is unavailable')
    text=lambda value:html.escape(str(value),quote=True)
    rows=''.join('<tr><th scope="row">'+text(name)+'</th><td>'+text(info.unit or 'Unknown unit')+'</td><td>'+str(info.sample_count)+'</td><td>'+str(info.missing_count)+'</td></tr>' for name,info in meta.curves.items())
    link=('<a href="'+text(meta.workspace_url)+'">Open this exact version in Workspace</a>') if meta.workspace_url else ''
    return ('<section aria-label="Scientific curve data"><strong>'+text(title)+'</strong><p>'+text(held)+'</p>'
            '<p>'+text(normalized)+'</p><p>'+text(evidence)+'</p><table><thead><tr><th>Curve</th><th>Unit</th><th>Samples</th><th>Missing</th></tr></thead><tbody>'+rows+'</tbody></table>'+link+
            '<details><summary>Technical details</summary><pre>'+text(json.dumps(meta.model_dump(),indent=2,allow_nan=False))+'</pre></details></section>')


def curve_set_html(data):
    from .scientific import descriptor
    from .errors import OphioliteError
    try:return descriptor_html(descriptor(data))
    except OphioliteError as error:
        message=html.escape(str(error),quote=True)
        technical=html.escape(json.dumps({'code':error.code,**error.details},indent=2),quote=True)
        return '<section aria-label="Scientific view unavailable"><p>'+message+'</p><details><summary>Technical details</summary><pre>'+technical+'</pre></details></section>'
