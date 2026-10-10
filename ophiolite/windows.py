"""E100a: a depth window of one exact curve revision, for display (`ophiolite.curve-window/1`).

A window is not a CurveSet: at levels 1..17 it holds blocks with their extrema, not samples, so every
place that needs exact samples (`to_numpy`, `write_curves`, `validate_derived_curves`) refuses it.
`Window` is the page loop both clients drive: it names each page's path, verifies each page against
the request and the curve's descriptor, and concatenates them; nothing partial is ever returned."""
import json
import math
import re
from urllib.parse import quote
from .errors import Refused, VerificationFailed

DISPLAY_ONLY='A window is for display; read the exact curve'
SCHEMA='ophiolite.curve-window/1'
LIMIT,LEVELS=2048,17
PAGE_BYTES=4*1024*1024  # 2,048 items of at most 14 numbers each
BLOCK_FIELDS=('run','first_index','last_index','first_depth','last_depth','first','last','min','min_index','min_depth',
              'max','max_index','max_depth','count')
HEX=re.compile('[0-9a-f]{64}')


def refuse_window(*values):
    """Refuse a CurveWindow wherever exact samples are needed."""
    if any(isinstance(v,CurveWindow) for v in values):raise Refused(DISPLAY_ONLY)


class CurveWindow:
    """The complete window: `sample_index`, `depth` and `value` at level 0 (exact), otherwise `runs`,
    `blocks` (columns of BLOCK_FIELDS) and `missing`. `pages` is how many pages were read; `etag` and
    `access_generation` are those of the first page."""
    def __init__(self,first,*,pages,etag,access_generation,sample_index=None,depth=None,value=None,runs=None,blocks=None,missing=None,range_=None):
        self.identity=dict(first['identity']);self.source_digest=first['source']['source_digest']
        self.unit,self.depth_unit,self.reference=first['unit'],first['depth_unit'],first['reference']
        self.shape,self.level,self.exact=first['shape'],first['level'],first['exact']
        self.items,self.rows_met,self.top,self.base=first['items'],first['rows_met'],first['request']['top'],first['request']['base']
        self.before,self.after,self.range=first['before'],first['after'],range_
        self.pages,self.etag,self.access_generation=pages,etag,access_generation
        self.sample_index,self.depth,self.value=sample_index,depth,value
        self.runs,self.blocks,self.missing=runs,blocks,missing

    def __len__(self):return len(self.sample_index) if self.exact else len(self.blocks['run'])
    def __repr__(self):
        return 'CurveWindow(%r, revision %s, %s..%s, level %d, %d %s, %d page%s)' % (
            self.identity['curve'],self.identity['revision'],self.top,self.base,self.level,len(self),
            'samples' if self.exact else 'blocks',self.pages,'' if self.pages==1 else 's')

    def to_dict(self):
        out={'schema':SCHEMA,'shape':self.shape,'identity':self.identity,'unit':self.unit,'reference':self.reference,'depth_unit':self.depth_unit,
             'source_digest':self.source_digest,'top':self.top,'base':self.base,'level':self.level,'exact':self.exact,'items':self.items,
             'rows_met':self.rows_met,'pages':self.pages,'range':self.range,'before':self.before,'after':self.after}
        if self.exact:out.update(sample_index=self.sample_index,depth=self.depth,value=self.value)
        else:out.update(runs=self.runs,blocks=self.blocks,missing=self.missing)
        return out


class Window:
    """The page loop of one `curve_window` call: path() -> fetch -> accept(body, headers) until done."""
    def __init__(self,project,asset,revision,curve,top,base,level,rows,max_pages):
        if (level is None)==(rows is None):raise Refused('Ask for a level or a number of rows, not both and not neither.')
        if level is not None and (type(level) is not int or not 0<=level<=LEVELS):raise Refused('Choose a level from 0 to 17.')
        if rows is not None and (type(rows) is not int or not 1<=rows<=LIMIT):raise Refused('Choose from 1 to 2048 rows.')
        if type(max_pages) is not int or max_pages<1:raise Refused('Choose at least one page.')
        try:top,base=float(top),float(base)
        except (TypeError,ValueError):raise Refused('Give the top and base depths as numbers.') from None
        if not (math.isfinite(top) and math.isfinite(base) and top<base):raise Refused('The top must be above the base.')
        self.project,self.asset,self.revision,self.curve=project,asset,revision,curve
        self.top,self.base,self.level,self.rows,self.max_pages=top,base,level,rows,max_pages
        self.digest=None;self.cursor=None;self.pages=[];self.headers={}

    def bind(self,descriptor):
        """The digest every page must carry: the descriptor's normalized representation of this curve."""
        normalized=next((r for r in descriptor['representations'] if r['kind']=='normalized'),None)
        digest=normalized and normalized.get('sha256')
        if not (isinstance(digest,str) and HEX.fullmatch(digest)):raise VerificationFailed('The curve descriptor carries no normalized digest.')
        self.digest=digest

    def path(self,prefix):
        query='?curve='+quote(self.curve,safe='')+'&top='+repr(self.top)+'&base='+repr(self.base)
        query+=('&level=%d' % self.level) if self.level is not None else ('&rows=%d' % self.rows)
        if self.cursor is not None:query+='&cursor='+quote(self.cursor,safe='')
        return prefix+'/windows'+query

    def accept(self,body,headers):
        """Verify one page; True when another page is needed."""
        from .validate import model
        from .models.generated import Curvewindow
        try:page=json.loads(body)
        except (ValueError,UnicodeError):raise VerificationFailed('The window page is not valid JSON.') from None
        page=model(Curvewindow,page).model_dump(by_alias=True,exclude_unset=True)
        want={'kind':'retained','project_id':self.project,'asset_id':self.asset,'revision':self.revision,'curve':self.curve}
        if page['identity']!=want:raise VerificationFailed('The window does not match the requested exact identity.')
        if page['source']['source_digest']!=self.digest:raise VerificationFailed('The window was computed from other data than this exact revision.')
        request=page['request']
        if (request['top'],request['base'],request['rows'],request['cursor'])!=(self.top,self.base,self.rows,self.cursor) or \
           request['level']!=self.level:raise VerificationFailed('The window answers another request.')
        if self.level is not None and page['level']!=self.level:raise VerificationFailed('The window is at another level than requested.')
        if page['exact']!=(page['level']==0) or (page['shape']=='raw')!=(page['level']==0):raise VerificationFailed('Only a level 0 window is exact.')
        if self.pages and any(page[k]!=self.pages[0][k] for k in ('level','items','rows_met','before','after','unit','depth_unit')):
            raise VerificationFailed('The window pages do not belong together.')
        _check_columns(page)
        if not self.pages:self.headers=headers
        self.pages.append(page)
        if page['next'] is None:return False
        if len(self.pages)>=self.max_pages:raise Refused('This window needs more than %d pages; ask for fewer rows or a higher level.' % self.max_pages)
        if page['next']==self.cursor:raise VerificationFailed('The window repeats a page link.')
        self.cursor=page['next'];return True

    def result(self):
        first=self.pages[0];raw=first['level']==0
        options=dict(pages=len(self.pages),etag=self.headers.get('etag'),access_generation=self.headers.get('x-ophiolite-access-generation'))
        served=[p['range'] for p in self.pages if p['range'] is not None]
        options['range_']={'served_first_depth':min(r['served_first_depth'] for r in served),'served_last_depth':max(r['served_last_depth'] for r in served)} if served else None
        if raw:
            for name in ('sample_index','depth','value'):options[name]=[v for p in self.pages for v in p[name]]
            _increasing(options['sample_index'],'sample')
        else:
            options['runs']=[r for p in self.pages for r in p['runs']]
            options['missing']=[m for p in self.pages for m in p['missing']]
            options['blocks']={f:[v for p in self.pages for v in p['blocks'][f]] for f in BLOCK_FIELDS}
            _increasing([r['run'] for r in options['runs']],'run');_increasing(options['blocks']['first_index'],'block')
            _increasing([m['from_index'] for m in options['missing']],'missing stretch')
        count=len(options['sample_index'] if raw else options['runs'])+(0 if raw else len(options['blocks']['run'])+len(options['missing']))
        if count!=first['items']:raise VerificationFailed('The window pages do not add up to its %d items.' % first['items'])
        return CurveWindow(first,**options)


def _check_columns(page):
    raw=page['level']==0;names=('sample_index','depth','value');summary=('runs','blocks','missing')
    if any((n in page)!=raw for n in names) or any((n in page)==raw for n in summary):raise VerificationFailed('The window page has the wrong shape for its level.')
    if raw:
        if not len(page['sample_index'])==len(page['depth'])==len(page['value']):raise VerificationFailed('The window columns differ in length.')
        _increasing(page['sample_index'],'sample')
    else:
        if len({len(page['blocks'][f]) for f in BLOCK_FIELDS})!=1:raise VerificationFailed('The window columns differ in length.')
        _increasing(page['blocks']['first_index'],'block')


def _increasing(values,what):
    if any(b<=a for a,b in zip(values,values[1:])):raise VerificationFailed('The window %s indices do not increase.' % what)
