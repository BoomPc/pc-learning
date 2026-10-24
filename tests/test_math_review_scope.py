import copy
from dataclasses import replace
import pytest
from math_agent.contracts import Source, Candidate, Review
from math_agent.pipeline import Runner, canonical_page
from math_agent.math_review_scope import capture, plan, merge, receipt, check_receipts
from math_agent.prompts import messages
from test_pipeline import MemoryCache, renderer


def fixture(sample, tmp_path):
    s=Source.model_validate(sample[0]);c=Candidate.model_validate(sample[1]);r=Review.model_validate(sample[2])
    for sol in c.solutions:
        for step in sol.steps:step.basis_ids=['C1']
    canonical_page(c,s)
    request={'text':'夹具','images':[]}
    snap=capture(s,c,r,request,tmp_path)
    new=c.model_copy(deep=True);new.solutions[1].steps[0].conclusion+='；补充独立边界推导'
    canonical_page(new,s)
    return s,c,r,request,snap,new


def scoped_raw(s):
    return {'verdict':'pass','conditions':{c.id:{'verdict':'pass','evidence':'重新核对原题全部条件'} for c in s.conditions},
            'questions':{'Q2':{'verdict':'pass','evidence':'修订的证明及边界独立核对'}},'issues':[]}


def test_only_unchanged_previously_accepted_independent_question_is_reused(sample,tmp_path):
    s,c,r,req,snap,new=fixture(sample,tmp_path);scope=plan(snap,s,new,req,tmp_path)
    assert scope['question_ids']==['Q2'] and scope['reused_questions']==['Q1']
    out=merge(scoped_raw(s),scope,s)
    assert out.questions[0]==r.questions[0] and out.verdict=='pass'
    records=[receipt(scope,scoped_raw(s),out)];check_receipts(records,s)
    records[0]['merged']['questions'][0]['evidence']='伪造旧证据'
    with pytest.raises(ValueError):check_receipts(records,s)


@pytest.mark.parametrize('change',['source','text','drawing','unknown','condition_issue','unbound_issue','diagram_issue','no_basis','unrelated_page','noncanonical'])
def test_changed_identity_or_ambiguous_scope_falls_back_to_full_review(sample,tmp_path,change):
    s,c,r,req,snap,new=fixture(sample,tmp_path)
    if change=='source':s.reference_summary+='新增答案条件'
    elif change=='text':req['text']+='变化'
    elif change=='drawing':new.spec['tabs'][0]['board']['objects'][0]['visible']=False
    elif change=='unknown':snap['review']['questions'][0]['verdict']='unknown'
    elif change=='condition_issue':snap['review']['conditions'][0]['verdict']='issue'
    elif change=='unbound_issue':snap['review'].update(verdict='revise',issues=[{'stage':'math','target':'边界证明','detail':'未明确属于哪问'}])
    elif change=='diagram_issue':snap['review'].update(verdict='revise',issues=[{'stage':'diagram','target':'Q2','detail':'构图需要修正'}])
    elif change=='no_basis':new.solutions[1].steps[0].basis_ids=[]
    elif change=='unrelated_page':new.spec['title']+='变化'
    elif change=='noncanonical':new.spec['tabs'][0]['conclusion']='未从证明派生'
    # Unknown/nonpass data is intentionally modeled as an incomplete prior review.
    if change in {'unknown','condition_issue'}:snap['review']['verdict']='needs_input'
    assert plan(snap,s,new,req,tmp_path) is None


def test_changed_dependency_invalidates_otherwise_unchanged_question(sample,tmp_path):
    s,c,r,req,snap,new=fixture(sample,tmp_path)
    c.solutions[1].steps[0].basis_ids=['Q1:S1'];canonical_page(c,s)
    snap=capture(s,c,r,req,tmp_path)
    new=c.model_copy(deep=True);new.solutions[0].steps[0].conclusion+='；修改前问';canonical_page(new,s)
    assert plan(snap,s,new,req,tmp_path) is None


def test_missing_changed_question_or_new_cross_question_error_cannot_pass(sample,tmp_path):
    s,c,r,req,snap,new=fixture(sample,tmp_path);scope=plan(snap,s,new,req,tmp_path)
    raw=scoped_raw(s);raw['questions']={}
    with pytest.raises(ValueError):merge(raw,scope,s)
    raw=scoped_raw(s);raw['issues']=[{'stage':'math','target':'Q1','detail':'新发现未修改问也有真实错误'}]
    result=merge(raw,scope,s)
    assert result.verdict=='revise' and result.questions[0].verdict=='issue' and result.issues


def test_actual_image_bytes_change_invalidates_reuse(sample,tmp_path):
    s,c,r,req,snap,new=fixture(sample,tmp_path)
    (tmp_path/'original.png').write_bytes(b'old')
    req['images']=[{'id':'img1','role':'question','file':'original.png'}]
    snap=capture(s,c,r,req,tmp_path)
    (tmp_path/'original.png').write_bytes(b'new')
    assert plan(snap,s,new,req,tmp_path) is None


def test_runtime_uses_scoped_native_schema_and_retains_original_tabs_tools_and_all_conditions(settings,job,sample,monkeypatch):
    store,jid,directory=job;s,c,r,req,snap,new=fixture(sample,directory)
    settings=replace(settings,compact_tools=True,review_responses=True,incremental_math_review=True)
    seen=[]
    class Model:
        calls=0
        def __init__(self,*args):pass
        def generate(self,stage,prompt,**kwargs):
            self.calls+=1;seen.append((stage,prompt,kwargs));return scoped_raw(s)
    runner=Runner(settings,jid,provider_factory=Model,cache_factory=MemoryCache,renderer=renderer)
    # Binding uses the actual job request; no cached/fabricated reviewer is called.
    runner.math_review_baseline=capture(s,c,r,runner.request,directory)
    monkeypatch.setattr('math_agent.proof_guards.collect',lambda *a:{'observations':[],'unobserved':[],'failures':[]})
    observation=runner.observe(new)
    result=runner.review(s,new,observation)
    assert result.verdict=='pass' and result.questions[0]==r.questions[0]
    assert len(seen)==1 and seen[0][0]=='review'
    schema=seen[0][2]['output_schema']
    assert schema['properties']['questions']['required']==['Q2']
    assert schema['properties']['conditions']['required']==[x.id for x in s.conditions]
    assert 'inspect_scene' in [d['function']['name'] for d in seen[0][2]['tools']]
    import json
    text='\n'.join(x['text'] for m in seen[0][1] if isinstance(m['content'],list) for x in m['content'] if x['type']=='text')
    assert '串行局部复核' in seen[0][1][0]['content']
    assert runner.scenes.current==new.spec and len(runner.math_review_receipts)==1
    check_receipts(runner.math_review_receipts,s)
    assert (directory/'math-review-receipts.json').is_file()


def test_engine_change_or_unrepaired_question_never_reuses_old_pass(sample,tmp_path,monkeypatch):
    import math_agent.math_review_scope as mod
    s,c,r,req,snap,new=fixture(sample,tmp_path)
    monkeypatch.setattr(mod,'engine_binding',lambda:'different-code')
    assert plan(snap,s,new,req,tmp_path) is None
    monkeypatch.undo()
    snap['review']['verdict']='revise'
    snap['review']['questions'][0].update(verdict='issue',evidence='第一问还存在尚未修正的推导问题')
    snap['review']['issues']=[{'stage':'math','target':'Q1','detail':'尚未修正的错误仍须重审'}]
    assert plan(snap,s,new,req,tmp_path) is None


def test_new_feature_configuration_and_cache_identity_are_explicit(settings):
    from math_agent.cache import key_for
    with pytest.raises(ValueError,match='compact'):
        replace(settings,incremental_math_review=True,compact_tools=False)
    request={'text':'same','images':[]}
    compact=replace(settings,compact_tools=True)
    assert key_for(compact,request)!=key_for(replace(compact,incremental_math_review=True),request)


def test_audit_keeps_job_elapsed_separate_from_model_request_duration(settings,job):
    from test_pipeline import provider
    _,jid,directory=job
    runner=Runner(settings,jid,provider_factory=provider([],[]),cache_factory=MemoryCache,renderer=renderer)
    runner.started-=100
    runner.audit('model',{'stage':'review','seconds':2.5})
    record=runner.records[-1]
    assert record['seconds']>=100 and record['duration_seconds']==2.5
