import copy,json,os
from pathlib import Path
import pytest
from math_agent.contracts import Source,Candidate
from math_agent.proof_guards import collect,_alias_case
from math_agent.pipeline import Runner,NeedsInput
from math_agent.deferred_review import PendingReviews
from math_agent.evidence import build_ledger
from test_pipeline import MemoryCache,renderer


def fixture():
    x=json.loads((Path(__file__).parent/'fixtures/proof-guards/midsegment.json').read_text())
    return Source.model_validate(x['source']),Candidate.model_validate(x['candidate']),x['review']


def observed_collinear(spec,probes,directory):
    return {'ok':True,'probes':[{'tab':0,'parameter':None,'checks':[{'holds':True,'points':p['points'],
        'observed':{i:[0,0] for i in p['points']}} for p in probes[0]['checks']]}]}


def test_explicit_rule_reuse_is_scoped_to_its_own_endpoint_clause(tmp_path):
    s,c,_=fixture();before=c.model_dump();r=collect(s,c,tmp_path,observe=observed_collinear)
    assert len(r['observations'])==len(r['failures'])==1 and not r['unobserved']
    f=r['failures'][0];assert f['case_evidence']['assignment']=={'point':'D','anchor':'B'}
    assert '同一中位线' in f['case_evidence']['claim_clause']
    assert f['check']['points']==['E','B','H'] and f['basis_ids']==['Q2:S2']
    assert c.model_dump()==before


def test_correct_separate_endpoint_proof_does_not_create_false_failure(tmp_path):
    s,c,_=fixture();c.solutions[0].cases=['当D与B重合时，不能使用同一中位线证明。由DE=AB=BC，F为BE中点，DF=DE/2，故CD=2DF。']
    assert not collect(s,c,tmp_path,observe=lambda *a:pytest.fail('不应运行反例观察'))['failures']


def test_alias_never_discards_derived_definition_or_builds_cycle():
    _,c,_=fixture()
    with pytest.raises(ValueError,match='派生构造'):_alias_case(c.spec,0,'E','B')
    with pytest.raises(ValueError,match='循环'):_alias_case(c.spec,0,'D','E')


@pytest.mark.skipif(os.getenv('MATH_AGENT_BROWSER_TEST')!='1',reason='实际原生浏览器反例')
@pytest.mark.parametrize('rename',[False,True])
def test_actual_native_counterexample_independent_of_internal_object_ids(tmp_path,rename):
    s,c,_=fixture()
    if rename:
        objects=c.spec['tabs'][0]['board']['objects'];mapping={o['id']:f'node{i}' for i,o in enumerate(objects)}
        for o in objects:
            o['id']=mapping[o['id']]
            if 'parents' in o:o['parents']=[mapping[p] for p in o['parents']]
    r=collect(s,c,tmp_path);assert len(r['failures'])==1 and not r['unobserved']
    f=r['failures'][0];o=f['case_evidence']['observation']['probes'][0]
    ids=f['case_evidence']['assignment']
    assert o['points'][ids['point']]==o['points'][ids['anchor']]
    assert all(v is not None for xy in f['check']['observed'].values() for v in xy)
    assert f['check']['holds'] and not f['check']['matches_expected']


@pytest.mark.parametrize('decision',['real_issue','unresolved','invalid_check'])
def test_reviewer_pass_cannot_silently_drop_guard_counterexample(settings,job,monkeypatch,decision):
    import math_agent.proof_guards as g
    s,c,passed=fixture();real_collect=g.collect
    monkeypatch.setattr(g,'collect',lambda src,cand,path:real_collect(src,cand,path,observe=observed_collinear))
    stages=[]
    class Model:
        calls=0
        def __init__(self,*args):pass
        def close(self):pass
        def generate(self,stage,messages,**kwargs):
            self.calls+=1;stages.append(stage)
            context=json.loads(messages[-1]['content'][0]['text'])['context']
            if stage=='review':
                assert context['proof_guard_observations']['failures']
                return passed
            assert stage=='adjudicate'
            f=context['failed_assertions'][0];assert f['kind']=='proof_guard'
            return {'decisions':[{'assertion_id':f['id'],'verdict':decision,'basis_ids':['Q2:S2'],
                'reason':'测试夹具逐条独立裁决：假设端点处三角形非退化前提必须核对，不能以默认图或最终数值替代证明。',
                'issue':{'stage':'math','target':'Q2:cases','detail':'退化三角形不满足中位线定理前提，端点需要独立证明。'} if decision=='real_issue' else None}]}
    runner=Runner(settings,job[1],Model,MemoryCache,renderer)
    if decision=='unresolved':
        with pytest.raises(NeedsInput):runner.review(s,c,{})
    else:
        review=runner.review(s,c,{})
        assert review.verdict==('revise' if decision=='real_issue' else 'pass')
        assert len(review.issues)==(1 if decision=='real_issue' else 0)
        assert review.questions[0].verdict==('issue' if decision=='real_issue' else 'pass')
    assert stages==['review','adjudicate']


def test_proof_guard_defers_when_review_already_found_math_error(settings,job,monkeypatch):
    import math_agent.proof_guards as g
    s,c,r=fixture();r.update(verdict='revise',issues=[{'stage':'math','target':'Q2','detail':'应先纠正端点证明'}])
    real_collect=g.collect
    monkeypatch.setattr(g,'collect',lambda src,cand,path:real_collect(src,cand,path,observe=observed_collinear))
    stages=[]
    class Model:
        calls=0
        def __init__(self,*a):pass
        def close(self):pass
        def generate(self,stage,*a,**kw):stages.append(stage);return r
    runner=Runner(settings,job[1],Model,MemoryCache,renderer)
    assert runner.review(s,c,{}).verdict=='revise'
    assert stages==['review']
    assert runner.deferred_reviews.pending[0]['failures'][0]['kind']=='proof_guard'


def test_proof_revision_can_resolve_proof_guard_without_moving_the_diagram(tmp_path):
    s,c,r=fixture();request={'text':'','images':[]};q=PendingReviews()
    failure=collect(s,c,tmp_path,observe=observed_collinear)['failures'][0];failure['id']='A1'
    from math_agent.contracts import Review
    q.add(s,c,{},request,[failure],Review.model_validate(r))
    new=c.model_copy(deep=True);new.solutions[0].cases=['当D与B重合时，DE=AB=BC，DF=DE/2，故CD=2DF。']
    p=q.payload(s,new,request);o=p['obligations'][0]
    result={'current_hash':p['current_hash'],'resolutions':[{'id':o['id'],'origin_hash':o['origin_hash'],'verdict':'resolved_by_revision',
        'scopes':[{'question_id':'Q2','object_ids':['B','D','E','F'],'basis_ids':['C6','C8','C9']}],
        'reason':'修订已删除退化时套用中位线的断言，改用DE=AB=BC与BE中点得到DF=DE/2，图形无需移动。','issue':None}]}
    q.commit(q.validate(result,p,s,new,build_ledger(s,new)),p)
    assert not q.pending and new.spec==c.spec


@pytest.mark.parametrize('clause',['当点D与点B重合时，按同一中位线证明仍成立。','当 D＝B 时，按同一中位线证明仍成立。'])
def test_explicit_case_notation_variants(tmp_path,clause):
    s,c,_=fixture();c.solutions[0].cases=[clause]
    assert len(collect(s,c,tmp_path,observe=observed_collinear)['failures'])==1


def test_local_observation_budget_is_bounded_and_not_reported_as_complete(tmp_path):
    s,c,_=fixture();c.solutions[0].cases=['当D与B重合时，按同一中位线证明仍成立。']*10
    r=collect(s,c,tmp_path,observe=observed_collinear)
    assert len(r['observations'])==8 and len(r['unobserved'])==2


def test_unrelated_metadata_change_cannot_claim_proof_counterexample_repaired(tmp_path):
    s,c,r=fixture();request={'text':'','images':[]};q=PendingReviews()
    f=collect(s,c,tmp_path,observe=observed_collinear)['failures'][0];f['id']='A1'
    from math_agent.contracts import Review
    q.add(s,c,{},request,[f],Review.model_validate(r))
    changed=s.model_copy(deep=True);changed.title+='（仅修改标题）'
    p=q.payload(changed,c,request);o=p['obligations'][0]
    raw={'current_hash':p['current_hash'],'resolutions':[{'id':o['id'],'origin_hash':o['origin_hash'],'verdict':'resolved_by_revision',
        'scopes':[{'question_id':'Q2','object_ids':['B','D'],'basis_ids':['C6']}],
        'reason':'这是测试中的错误声称：仅修改标题就声称已有的端点反例得到解决，必须阻断。','issue':None}]}
    with pytest.raises(ValueError,match='均未改变'):q.validate(raw,p,changed,c,build_ledger(changed,c))
    assert q.pending
