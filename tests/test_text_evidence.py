import copy,json
from pathlib import Path
import pytest
from math_agent.text_evidence import normalized_quote, quote_in_text
from math_agent.contracts import Source,check_source


@pytest.mark.parametrize('a,b',[(r'BG\parallel AC','BG∥AC'),('BG//AC','BG∥AC'),('A′B//C1D','A′B∥C1D'),('AB‖CD','AB∥CD')])
def test_named_line_parallel_encoding_aliases(a,b):
    assert normalized_quote(a)==normalized_quote(b)


@pytest.mark.parametrize('a,b',[('A′B//CD','AB∥CD'),('AB//C′D','AB∥CD'),('AB//C1D','AB∥CD'),
 ('AB=-2','AB=2'),('x²','x2'),('AB<CD','AB=CD'),('6//2','6∥2')])
def test_symbol_normalization_does_not_change_mathematics(a,b):
    assert normalized_quote(a)!=normalized_quote(b)


def test_parallel_alias_passes_verbatim_check_without_rewriting_raw_text(sample):
    raw=copy.deepcopy(sample[0]);raw['problem_text']='过点B作BG∥AC交AD延长线于点G。'
    raw['conditions'][0].update(text='BG∥AC',quote='BG//AC')
    src=Source.model_validate(raw);check_source(src,[])
    assert src.conditions[0].quote=='BG//AC' and src.problem_text==raw['problem_text']


@pytest.mark.parametrize('quote,text',[
    ('AB=CD．','已知AB=CD．连接AC。'),
    ('互为“中心对称函数”．','定义两个函数互为“中心对称函数”．例如：y=x。'),
    ('x=1.2','已知x=1.2。')])
def test_verbatim_substring_cannot_fail_due_to_normalization_context(sample,quote,text):
    assert quote in text and quote_in_text(quote,text)
    raw=copy.deepcopy(sample[0]);raw['problem_text']=text;raw['conditions'][0].update(quote=quote,text=quote)
    check_source(Source.model_validate(raw),[])


@pytest.mark.parametrize('quote,text',[
    ('AB=2','已知AB=-2。'),('x²=2','已知x2=2。'),
    ('A′B=3','已知AB=3。'),('x=1.2','已知x=12。')])
def test_exact_match_first_does_not_loosen_mathematical_evidence(quote,text):
    assert not quote_in_text(quote,text)
