import copy,json
from pathlib import Path
import pytest
from math_agent.contracts import Source,Candidate,Review
from math_agent.pipeline import Runner,canonical_page,NeedsInput
from math_agent.deferred_review import PendingReviews
from test_pipeline import MemoryCache,renderer


def setup_pending(sample):
    src=Source.model_validate(sample[0]);candidate=canonical_page(Candidate.model_validate(sample[1]),src)
    review=Review.model_validate(sample[2]);request={'text':'test','images':[]}
    point=next(o['id'] for o in candidate.spec['tabs'][0]['board']['objects'] if o['kind']=='point')
    failure={'id':'A1','kind':'invalid_query','tab':0,'check':{'relation':'same_y','points':[point,point],'expected':True}}
    q=PendingReviews();q.add(src,candidate,{},request,[failure],review)
    payload=q.payload(src,candidate,request)
    from math_agent.evidence import build_ledger
    ledger=build_ledger(src,candidate)
    raw={'current_hash':payload['current_hash'],'resolutions':[{'id':'D1:A1','origin_hash':payload['obligations'][0]['origin_hash'],
        'verdict':'invalid_check','scopes':[{'question_id':'Q1','object_ids':[point],'basis_ids':['C1']}],
        'reason':'错误检查引用不成立的原依据，已对照相应题设与当前实际对象独立核对，此处为离线路由测试。','issue':None}]}
    return q,payload,src,candidate,ledger,raw,request


@pytest.mark.parametrize('change',['missing','duplicate','origin','current','objects','basis','same_version_revision'])
def test_pending_checks_cannot_disappear_or_claim_another_version(sample,change):
    q,p,s,c,l,r,req=setup_pending(sample)
    if change=='missing':r['resolutions']=[]
    elif change=='duplicate':r['resolutions']*=2
    elif change=='origin':r['resolutions'][0]['origin_hash']='wrong'
    elif change=='current':r['current_hash']='wrong'
    elif change=='objects':r['resolutions'][0]['scopes'][0]['object_ids']=['nonexistent']
    elif change=='basis':r['resolutions'][0]['scopes'][0]['basis_ids']=['Q1']
    else:r['resolutions'][0]['verdict']='resolved_by_revision'
    with pytest.raises(ValueError):q.validate(r,p,s,c,l)
    assert q.pending and not q.receipts


def test_unresolved_or_tampered_bundle_cannot_be_committed(sample):
    q,p,s,c,l,r,req=setup_pending(sample)
    r['resolutions'][0]['verdict']='unresolved'
    with pytest.raises(ValueError):q.commit(q.validate(r,p,s,c,l),p)
    assert q.pending
    q.pending[0]['source']['title']='changed behind hash'
    with pytest.raises(ValueError,match='哈希'):q.payload(s,c,req)


def test_real_geometric_failure_is_not_resolved_by_changing_prose(sample):
    q,p,s,c,l,r,req=setup_pending(sample)
    q.pending=[]
    q.add(s,c,{},req,[{'id':'A1','tab':0,'check':{'relation':'same_y','expected':True}}],Review.model_validate(sample[2]))
    changed=c.model_copy(deep=True);changed.solutions[0].result='proof changed';canonical_page(changed,s)
    p=q.payload(s,changed,req);r['current_hash']=p['current_hash'];r['resolutions'][0]['origin_hash']=p['obligations'][0]['origin_hash'];r['resolutions'][0]['verdict']='resolved_by_revision'
    with pytest.raises(ValueError,match='图形未改变'):q.validate(r,p,s,changed,l)


@pytest.mark.parametrize('issue_stage',['math','source'])
def test_substantive_issue_is_returned_before_diagram_adjudication(settings,job,sample,issue_stage):
    s=Source.model_validate(sample[0]);c=canonical_page(Candidate.model_validate(sample[1]),s)
    bad=copy.deepcopy(sample[2]);bad.update(verdict='revise',issues=[{'stage':issue_stage,'target':'Q1','detail':'必须先修正的实质问题'},
        {'stage':'diagram','target':'Q2','detail':'不能删除的构图异议'}])
    calls=[]
    class Model:
        calls=0
        def __init__(self,*args):pass
        def generate(self,stage,*args,**kw):calls.append(stage);return bad
        def close(self):pass
    runner=Runner(settings,job[1],Model,MemoryCache,renderer)
    value=runner.review(s,c,{})
    assert calls==['review'] and value.issues[0].stage==issue_stage and len(value.issues)==2
    assert len(runner.deferred_reviews.pending[0]['failures'])==1
    assert runner.deferred_reviews.pending[0]['review']==bad


def test_actual_low_failure_routes_through_math_repair_before_settling_query(settings,job):
    from math_agent.flow import execute_graph
    x=json.loads((Path(__file__).parent/'fixtures/repair-priority/low48.json').read_text())
    src=Source.model_validate(x['source']);candidate=Candidate.model_validate(x['candidate'])
    stages=[];holder={}
    class Model:
        def __init__(self,settings,audit):self.audit=audit;self.calls=0
        def close(self):pass
        def generate(self,stage,messages,**kwargs):
            self.calls+=1;stages.append(stage)
            if stage=='review' and stages.count('review')==1:
                for r in x['inspections']:self.audit('tool',{k:v for k,v in r.items() if k not in ('kind','seconds')})
                return x['review']
            if stage=='math_repair':
                assert holder['runner'].deferred_reviews.pending
                solutions=copy.deepcopy(x['candidate']['solutions'])
                solutions[1]['steps'][3]['conclusion']='C′(−2cos60°，−2sin60°)=(−1，−√3)。离线夹具仅验证路由。'
                return {'updates':{'Q2':{'reason':'修正复核明确指出的第二问三角函数符号错误，无需重写其余已经正确的解答。','proof':{k:v for k,v in solutions[1].items() if k!='question_id'}}}}
            if stage=='review':
                v=copy.deepcopy(x['review']);v['verdict']='pass';v['issues']=[]
                v['questions']['Q2'].update(verdict='pass',evidence='离线夹具，仅验证修复后的复核路由')
                return v
            assert stage=='deferred_review'
            p=json.loads(messages[-1]['content'][0]['text'])['context'];o=p['obligations'][0]
            assert len(p['obligations'])==1 and o['failure']['referral_reason']=='invalid_basis'
            assert 'Q2 建系' in p['deferred_bundles'][0]['review']['issues'][0]['target']
            return {'current_hash':p['current_hash'],'resolutions':[{'id':o['id'],'origin_hash':o['origin_hash'],
                'verdict':'invalid_check','scopes':[{'question_id':'Q4','object_ids':['A','D','Bp'],'basis_ids':['C8']}],
                'reason':'旧检查引用不存在的Q4:S6，当前已重新核对射线条件和D与B′重合，此处为离线路由夹具，不代表真实模型验收。','issue':None}]}
    from dataclasses import replace
    runner=Runner(replace(settings,compact_tools=True),job[1],Model,MemoryCache,renderer);holder['runner']=runner
    state=execute_graph(runner,{'entry':'review','source':src,'candidate':candidate,'observation':{},'repairs':0,'feedback':[]})
    assert stages==['review','math_repair','review','deferred_review']
    assert state['review'].verdict=='pass' and not runner.deferred_reviews.pending
    assert len(runner.deferred_reviews.receipts)==1
    data=json.loads((job[2]/'deferred-reviews.json').read_text());assert not data['pending'] and data['receipts']


def test_pending_archive_survives_new_runner_and_blocks_cached_publication(settings,job,sample):
    from test_pipeline import provider
    from math_agent.storage import write_json
    stages=[]
    first=Runner(settings,job[1],provider(list(sample),stages),MemoryCache,renderer)
    first.run();assert job[0].get(job[1])['status']=='completed'
    q,p,s,c,l,r,req=setup_pending(sample)
    new_id,new_path=job[0].prepare()
    write_json(new_path/'request.json',json.loads((job[2]/'request.json').read_text()))
    write_json(new_path/'deferred-reviews.json',q.dump())
    job[0].enqueue(new_id);job[0].claim()
    fresh=Runner(settings,new_id,provider([],stages),MemoryCache,renderer)
    fresh.cache.data=first.cache.data
    assert fresh.deferred_reviews.pending
    fresh.run()
    assert job[0].get(new_id)['status']=='failed'
    assert '缓存' in job[0].get(new_id)['error']
    assert stages==['source','solve','review'] and fresh.deferred_reviews.pending


def test_receipt_is_committed_once_and_a_new_version_requires_new_receipt(sample):
    q,p,s,c,l,r,req=setup_pending(sample)
    result=q.validate(r,p,s,c,l);q.commit(result,p)
    assert not q.pending and len(q.receipts)==1
    with pytest.raises(ValueError,match='集合已变化'):q.commit(result,p)
    loaded=PendingReviews();loaded.load(q.dump());assert loaded.dump()==q.dump()
    changed=c.model_copy(deep=True);changed.solutions[0].result='another proof version'
    q.add(s,changed,{},req,[{'id':'A1','kind':'invalid_query','tab':0}],Review.model_validate(sample[2]))
    new=q.payload(s,changed,req)
    with pytest.raises(ValueError,match='版本'):q.validate(r,new,s,changed,l)
