from html.parser import HTMLParser
import pytest
from ophiolite import Credential
from ophiolite.models.generated import Display
from test_scientific import view

class Visible(HTMLParser):
    # E104 C2: a closed details still shows its own summary, and an input shows its value.
    def __init__(self):super().__init__();self.closed=0;self.text=[];self.details=[];self.summary=0
    def _shown(self):return not self.closed or self.summary and self.closed==1 and self.details[-1]
    def handle_starttag(self,tag,attrs):
        if tag=='details':
            hidden=not any(key=='open' for key,value in attrs);self.details.append(hidden);self.closed+=int(hidden)
        if tag=='summary':self.summary+=1
        if self._shown():
            self.text.extend(value for key,value in attrs if key in ('aria-label','aria-description','title','alt') or tag=='input' and key=='value' if value)
    def handle_endtag(self,tag):
        if tag=='details':self.closed-=int(self.details.pop())
        if tag=='summary':self.summary-=1
    def handle_data(self,value):
        if self._shown():self.text.append(value)

def visible(raw):
    parser=Visible();parser.feed(raw);return ' '.join(parser.text)


def test_default_human_layer_and_disclosure():
    data,_=view();data.credential=Credential.bearer('SDK_REPR_CREDENTIAL_CANARY')
    raw=data._repr_html_();text=visible(raw)
    assert 'LAS 2.0 well log file' in text and 'Normalized well log curve' in text
    assert 'gAPI' in text and 'g/cm3' in text and 'Samples' in text and 'Missing' in text
    for word in (data.descriptors[0].asset_id,data.descriptors[0].revision,'synthetic-file','source-reference','las2/1','asset_connectors.las_reader/1'):
        assert word not in text
        assert word in raw
    assert 'SDK_REPR_CREDENTIAL_CANARY' not in raw and 'SDK_REPR_CREDENTIAL_CANARY' not in repr(data)
    assert '<details><summary>Technical details</summary>' in raw
    assert '<details open' not in raw
    assert data.descriptors[0].asset_id in visible(raw.replace('<details>', '<details open>'))


def test_human_display_overrides_registry():
    data,_=view();data.descriptors[0].display=Display(type='Laboratory calibration log',held_as='Saved by your team')
    text=visible(data._repr_html_())
    assert 'Laboratory calibration log' in text and 'Saved by your team' in text

@pytest.mark.parametrize('bad',['<img src=x onerror=alert(1)>','Injected native-external/1','a'*64,'98765432-1234-4321-aaaa-123456789abc','Hidden\ncontrol','source-declared','script-declared','managed-derived','not-evaluated','use-as-input','recorded-differs'])
def test_hostile_or_engineering_display_falls_back(bad):
    data,_=view();data.descriptors[0].display=Display(type=bad,held_as=bad)
    raw=data._repr_html_();text=visible(raw)
    assert bad not in text and 'LAS 2.0 well log file' in text
    assert '<img' not in raw and 'onerror=' not in text


def test_error_default_text_is_human():
    data,_=view();data.curves[1].context.depth_unit='FT'
    raw=data._repr_html_();text=visible(raw)
    assert 'different depth units' in text and 'align them explicitly' in text
    assert 'axis-mismatch' not in text and 'axis-mismatch' in raw


def test_missing_link_has_no_invented_generic_destination():
    data,_=view();data.url=''
    assert '<a ' not in data._repr_html_()


def test_vocabulary_contains_other_origins_and_contract_constants():
    from ophiolite.repr import technical_vocabulary
    assert {'managed-derived','not-evaluated','use-as-input','recorded-differs',
            'ophiolite.contract-profile/1','ophiolite.contracts-registry/1'} <= technical_vocabulary()


def test_oracle_sees_summaries_and_input_values():
    # E104 C2: proof that the oracle can fail. Mutations: summaries hidden again; input values ignored.
    assert 'SECRETID' in visible('<details><summary>SECRETID</summary><pre>x</pre></details>')
    assert 'SECRETID' not in visible('<details><summary>Shown</summary><pre>SECRETID</pre></details>')
    assert 'SECRETID' not in visible('<details><summary>Shown</summary><details><summary>SECRETID</summary></details></details>')
    assert 'SECRETID' in visible('<details><summary aria-label="SECRETID">x</summary></details>')
    assert 'SECRETID' in visible('<p><input readonly value="SECRETID"></p>')
    assert 'SECRETID' not in visible('<details><summary>Copy link</summary><input readonly value="SECRETID"></details>')
