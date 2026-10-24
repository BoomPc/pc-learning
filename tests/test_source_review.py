import copy
import json
import pytest
from math_agent.source_review import check_reread, apply_reread
from math_agent.pipeline import Runner, NeedsInput
from math_agent.storage import write_json
from test_pipeline import MemoryCache, renderer


def example(sample):
    source=copy.deepcopy(sample[0])
    source['problem_text']='已知∠ABC=∠ADE=90°。求解各问。'
    source['conditions'][0]['text']='∠ABC=∠ADE=90°'
    issues=[{'id':'U1','text':'图上小方框不清楚，文字已明确∠ADE=90°'}]
    raw={'source':source,'decisions':[{'issue_id':'U1','verdict':'resolved_by_text','condition_ids':['C1'],
        'quote':'∠ADE=90°','reason':'原题文字已经明确同一角，不需要重复图示作为额外条件'}]}
    return raw,issues


def test_explicit_text_resolves_but_keeps_audit_evidence(sample):
    raw,issues=example(sample);original=copy.deepcopy(raw)
    value=check_reread(raw,issues,[])
    assert not apply_reread(value,issues).uncertainties
    assert raw==original and value.decisions[0].quote=='∠ADE=90°'


@pytest.mark.parametrize('change',['omit','fake_quote','unknown_condition','diagram_origin','empty_quote'])
def test_missing_or_invalid_resolution_cannot_pass(sample,change):
    raw,issues=example(sample)
    if change=='omit':raw['decisions']=[]
    elif change=='fake_quote':raw['decisions'][0]['quote']='AB=999'
    elif change=='unknown_condition':raw['decisions'][0]['condition_ids']=['C404']
    elif change=='diagram_origin':
        raw['source']['conditions'][0].update(origin='explicit_diagram_mark',image_ids=['I1'])
    else:raw['decisions'][0]['quote']=''
    with pytest.raises(ValueError):check_reread(raw,issues,[{'id':'I1','role':'question'}])


def test_unresolved_is_preserved_even_if_model_omits_uncertainty(sample):
    raw,issues=example(sample)
    raw['decisions'][0].update(verdict='unresolved',quote='',condition_ids=[])
    raw['source']['uncertainties']=[]
    value=check_reread(raw,issues,[])
    assert apply_reread(value,issues).uncertainties==[issues[0]['text']]


def test_mixed_or_new_uncertainties_still_block(sample):
    raw,issues=example(sample)
    issues.append({'id':'U2','text':'边长缺失'})
    raw['decisions'].append({'issue_id':'U2','verdict':'unresolved','quote':'','condition_ids':[],'reason':'没有明确边长'})
    raw['source']['uncertainties']=['新发现点名不清']
    value=apply_reread(check_reread(raw,issues,[]),issues)
    assert value.uncertainties==['新发现点名不清','边长缺失']


@pytest.mark.parametrize('resolved',[True,False])
def test_pipeline_only_advances_on_supported_resolution(settings,job,sample,resolved):
    raw,issues=example(sample);source=copy.deepcopy(raw['source']);source['uncertainties']=[issues[0]['text']]
    if not resolved:raw['decisions'][0].update(verdict='unresolved',quote='',condition_ids=[])
    # Existing OCR evidence enables the bounded independent reread; no network.
    write_json(job[2]/'request.json',{'text':source['problem_text'],'images':[],'force':True,
        'ocr_evidence':[{'image_id':'I1','role':'question','blocks':[],'warnings':[]}]})
    seen=[]
    class Model:
        def __init__(self,settings,audit):self.calls=0
        def close(self):pass
        def generate(self,stage,messages,**kwargs):
            self.calls+=1;seen.append(stage)
            context=json.loads(messages[-1]['content'][0]['text'])
            if stage=='source_review':
                assert context['ocr_evidence']==[]
                assert context['context']['issues']==issues
                return copy.deepcopy(raw)
            return copy.deepcopy(source)
    runner=Runner(settings,job[1],Model,MemoryCache,renderer)
    try:
        if resolved:assert not runner.extract().uncertainties
        else:
            with pytest.raises(NeedsInput):runner.extract()
        assert seen==['source','source_review']
        assert (job[2]/'source-question-review.json').exists()
    finally:runner.provider.close()


def test_additional_diagram_reference_cannot_replace_explicit_text(sample):
    raw,issues=example(sample)
    raw['source']['conditions'].append({'id':'C2','text':'D处直角标记','origin':'explicit_diagram_mark','image_ids':['I1'],'question_ids':[]})
    raw['decisions'][0]['condition_ids']=['C1','C2']
    assert check_reread(raw,issues,[{'id':'I1','role':'question'}]).decisions[0].verdict=='resolved_by_text'
    raw['decisions'][0]['condition_ids']=['C2']
    with pytest.raises(ValueError):check_reread(raw,issues,[{'id':'I1','role':'question'}])


def test_multiple_atomic_citations_resolve_split_conditions_without_joining_text(sample):
    raw,issues=example(sample)
    raw['source']['problem_text']='点A移动。D在射线AB上。'
    raw['source']['conditions']=[{'id':'C1','text':'点A移动。','origin':'question_text','image_ids':[]},
        {'id':'C2','text':'D在射线AB上。','origin':'question_text','image_ids':[]}]
    raw['decisions'][0].update(quote='',condition_ids=[],citations=[{'condition_id':'C1','quote':'点A移动'}, {'condition_id':'C2','quote':'D在射线AB上'}])
    assert check_reread(raw,issues,[]).decisions[0].verdict=='resolved_by_text'
    for bad in ['点A移动。D在射线AB上。','AB=999',' ']:
        modified=copy.deepcopy(raw);modified['decisions'][0]['citations'][0]['quote']=bad
        with pytest.raises(ValueError):check_reread(modified,issues,[])


@pytest.mark.parametrize('change',['mixed','unknown','image_only','wrong_condition'])
def test_atomic_citation_does_not_bypass_provenance_checks(sample,change):
    raw,issues=example(sample)
    raw['decisions'][0].update(quote='',condition_ids=[],citations=[{'condition_id':'C1','quote':'∠ADE=90°'}])
    if change=='mixed':raw['decisions'][0]['quote']='∠ADE=90°'
    elif change=='unknown':raw['decisions'][0]['citations'][0]['condition_id']='C404'
    elif change=='image_only':raw['source']['conditions'][0].update(origin='explicit_diagram_mark',image_ids=['I1'])
    else:raw['source']['conditions'][0]['text']='无关条件'
    with pytest.raises(ValueError):check_reread(raw,issues,[{'id':'I1','role':'question'}])


def test_source_quote_separates_verbatim_evidence_from_paraphrase(sample):
    raw,issues=example(sample)
    raw['source']['conditions'][0].update(text='两个指定角均为直角',quote='∠ABC=∠ADE=90°')
    raw['decisions'][0].update(evidence_ids=['C1'],quote='',condition_ids=[])
    value=check_reread(raw,issues,[])
    assert value.decisions[0].evidence_ids==['C1']
    assert value.source.conditions[0].quote=='∠ABC=∠ADE=90°'
    for quote in ['AB=999',' ']:
        changed=copy.deepcopy(raw);changed['source']['conditions'][0]['quote']=quote
        with pytest.raises(ValueError):check_reread(changed,issues,[])


def test_evidence_ids_cannot_cite_unanchored_paraphrase_or_image(sample):
    raw,issues=example(sample);raw['decisions'][0].update(evidence_ids=['C1'],quote='',condition_ids=[])
    raw['source']['conditions'][0]['text']='由图看着应该是直角'
    with pytest.raises(ValueError):check_reread(raw,issues,[])
    raw['source']['conditions'][0].update(origin='question_image',image_ids=['I1'],quote='∠ADE=90°')
    with pytest.raises(ValueError):check_reread(raw,issues,[{'id':'I1','role':'question'}])


def test_typographic_width_equivalence_does_not_change_math_symbols(sample):
    from math_agent.text_evidence import normalized_quote
    assert normalized_quote('α（０°＜α＜１８０°）')==normalized_quote('α(0°<α<180°)')
    for a,b in [('x²','x2'),('BC′','B′C′'),('AB=-2','AB=2'),('AB=2','AB=3')]:
        assert normalized_quote(a)!=normalized_quote(b)
    raw,issues=example(sample)
    raw['source']['problem_text']='旋转α（0°<α<180°）'
    raw['source']['conditions'][0].update(text='旋转角属于开区间',quote='α(0°<α<180°)')
    raw['decisions'][0].update(evidence_ids=['C1'],condition_ids=[],quote='')
    assert check_reread(raw,issues,[]).decisions[0].verdict=='resolved_by_text'

@pytest.mark.parametrize('stage',['source','source_review'])
def test_source_correction_stays_in_reading_stage(settings,job,stage):
    runner=Runner(settings,job[1],cache_factory=MemoryCache)
    calls=[]
    def ask(current,payload,request_override=None):
        calls.append(payload)
        if len(calls)==2:
            instruction=payload['structured_output_correction']['instruction']
            assert '这是读题输出纠错' in instruction
            assert '按source的小问数量与顺序组织' not in instruction
        return {'valid':len(calls)==2}
    runner.ask=ask
    def validate(raw):
        if not raw['valid']:raise ValueError('quote mismatch')
        return raw
    try:
        assert runner.validated(stage,{},validate)=={'valid':True}
        assert len(calls)==2
    finally:runner.provider.close()


def test_sentence_stop_equivalence_does_not_change_decimals_or_products():
    from math_agent.text_evidence import normalized_quote
    assert normalized_quote('D，E，F．连接AB')==normalized_quote('D,E,F。连接AB')
    assert normalized_quote('1.2')!=normalized_quote('12')
    assert normalized_quote('1.2')!=normalized_quote('1。2')
    assert normalized_quote('AB·BC')!=normalized_quote('ABBC')
