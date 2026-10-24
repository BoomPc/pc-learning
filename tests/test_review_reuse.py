import copy
from dataclasses import replace
import pytest
from math_agent.contracts import Source,Candidate,Review
from math_agent.review_reuse import Snapshot
from math_agent.scene_tools import fingerprint
from math_agent.pipeline import Runner
from test_pipeline import MemoryCache,renderer,provider
from test_compact_tools import pack
from test_objection_gate import resolution


def prepare(sample,tmp_path):
    source=Source.model_validate(sample[0]);c=Candidate.model_validate(sample[1]);r=Review.model_validate(sample[2])
    req={'text':'test','images':[]};obs={'status':'pass','spec_sha256':fingerprint(c.spec)}
    return source,c,r,req,obs


def test_delta_rechecks_changed_controls_and_preserves_review(tmp_path,sample):
    s,c,r,req,obs=prepare(sample,tmp_path);snap=Snapshot(s,c,r,obs,req,tmp_path)
    new=c.model_copy(deep=True);new.spec['tabs'][1]['controls']['slider']['default']+=.1
    d=snap.delta(s,new,req,tmp_path);assert d['changed_questions']==['Q2']
    merged=snap.merge({'verdict':'pass','questions':[{'id':'Q2','verdict':'pass','evidence':'真实检查新滑块默认值与题意一致'}],'resolutions':[],'issues':[]},d,s)
    assert merged.conditions==r.conditions and merged.questions[0]==r.questions[0]
    assert snap.certificate in merged.questions[1].evidence

@pytest.mark.parametrize('change',['source','math','text','image','role','title','tabs'])
def test_changed_provenance_invalidates_reuse(tmp_path,sample,change):
    s,c,r,req,obs=prepare(sample,tmp_path);(tmp_path/'i.png').write_bytes(b'original')
    req['images']=[{'id':'I1','role':'question','file':'i.png'}];snap=Snapshot(s,c,r,obs,req,tmp_path)
    c.spec['tabs'][0]['board']['axis']=False
    if change=='source':s.conditions[0].text='changed'
    elif change=='math':c.solutions[0].steps[0].premise='changed'
    elif change=='text':req['text']='changed'
    elif change=='image':(tmp_path/'i.png').write_bytes(b'changed')
    elif change=='role':req['images'][0]['role']='answer'
    elif change=='title':c.spec['title']='changed'
    else:c.spec['tabs'].pop()
    assert snap.delta(s,c,req,tmp_path) is None

@pytest.mark.parametrize('change',['math','unknown','source','stale_browser'])
def test_unknown_or_objection_cannot_be_certified(tmp_path,sample,change):
    s,c,r,req,obs=prepare(sample,tmp_path)
    if change in {'source','math'}:r.verdict='revise';r.issues=[__import__('math_agent.contracts',fromlist=['Issue']).Issue(stage=change,target='Q1',detail='test')]
    elif change=='unknown':r.questions[0].verdict='unknown';r.verdict='needs_input'
    else:obs['spec_sha256']='stale'
    with pytest.raises(ValueError):Snapshot(s,c,r,obs,req,tmp_path)


def test_missing_objection_resolution_cannot_publish(tmp_path,sample):
    s,c,r,req,obs=prepare(sample,tmp_path);r.verdict='revise'
    from math_agent.contracts import Issue
    r.issues=[Issue(stage='diagram',target='Q1',detail='missing edge')]
    snap=Snapshot(s,c,r,obs,req,tmp_path);new=c.model_copy(deep=True);new.spec['tabs'][0]['board']['axis']=False
    d=snap.delta(s,new,req,tmp_path)
    raw={'verdict':'pass','questions':[{'id':'Q1','verdict':'pass','evidence':'checked'}],'resolutions':[],'issues':[]}
    with pytest.raises(ValueError):snap.merge(raw,d,s)
    raw['resolutions']=[{'id':'I1','verdict':'unknown','evidence':'cannot establish'}]
    with pytest.raises(ValueError):snap.merge(raw,d,s)


def test_classic_graph_reuses_only_after_real_review_and_patch(settings,job,sample):
    source,candidate,good=copy.deepcopy(sample)
    objection=copy.deepcopy(good);objection.update(verdict='revise',issues=[{'stage':'diagram','target':'Q1','detail':'missing edge'}])
    patch={'edits':[{'tab':0,'upsert':[{'id':'extra_edge','kind':'segment','parents':['A','B']}]}]}
    delta={'verdict':'pass','questions':[{'id':'Q1','verdict':'pass','evidence':'补线后已由浏览器检查'}],
           'resolutions':[{'id':'I1','verdict':'resolved','evidence':'缺边已补入，依赖和图文一致'}],'issues':[]}
    stages=[]
    queue=[source,pack(candidate),__import__('test_compact_review').pack_review(objection),resolution(objection,candidate),patch,delta]
    runner=Runner(replace(settings,compact_tools=True,incremental_review=True),job[1],provider(queue,stages),MemoryCache,renderer)
    runner.run()
    assert job[0].get(job[1])['status']=='completed'
    assert stages==['source','solve','review','adjudicate','diagram','diagram_review']
    assert runner.review_snapshot is not None
    assert any(r['kind']=='review_reuse' for r in runner.records)


def test_delta_new_math_objection_invalidates_next_certificate(tmp_path,sample):
    s,c,r,req,obs=prepare(sample,tmp_path);snap=Snapshot(s,c,r,obs,req,tmp_path)
    new=c.model_copy(deep=True);new.spec['tabs'][0]['board']['axis']=False
    d=snap.delta(s,new,req,tmp_path)
    merged=snap.merge({'verdict':'revise','questions':[{'id':'Q1','verdict':'issue','evidence':'新图暴露出原证明遗漏边界'}],
        'resolutions':[],'issues':[{'stage':'math','target':'Q1','detail':'须重新补证端点'}]},d,s)
    assert merged.issues[0].stage=='math'
    with pytest.raises(ValueError):Snapshot(s,new,merged,{'status':'pass','spec_sha256':fingerprint(new.spec)},req,tmp_path)


def test_diagram_review_keeps_high_and_full_allowance(settings):
    import json,httpx
    from math_agent.provider import DeepSeek
    from test_provider import response
    seen=[]
    def handler(req):
        seen.append(json.loads(req.content))
        return httpx.Response(200,json=response({'role':'assistant','content':'{}'}))
    c=DeepSeek(replace(settings,thinking=True,effort='high',max_tokens=32000),lambda *a:None,httpx.MockTransport(handler))
    try:c.generate('diagram_review',[])
    finally:c.close()
    assert seen[0]['reasoning_effort']=='high' and seen[0]['thinking']['type']=='enabled'
    assert seen[0]['max_tokens']==32000


def test_delta_query_schema_cannot_assert_or_query_unchanged_tab():
    from math_agent.review_reuse import query_tool
    from jsonschema import validate,ValidationError
    schema=query_tool({'changed_tabs':[2]})['function']['parameters']
    args={'probes':[{'tab':2,'checks':[{'relation':'same_x','points':['A','B']}]}]}
    validate(args,schema)
    args['probes'][0]['checks'][0]['expected']=True
    with pytest.raises(ValidationError):validate(args,schema)
    args['probes'][0]['checks'][0].pop('expected');args['probes'][0]['tab']=0
    with pytest.raises(ValidationError):validate(args,schema)


def test_delta_query_only_error_does_not_execute_scene(settings,job,sample):
    runner=Runner(settings,job[1],cache_factory=MemoryCache,renderer=renderer)
    candidate=Candidate.model_validate(sample[1]);runner.scenes.current=candidate.spec
    runner.review_candidate=candidate;runner.save_ledger(Source.model_validate(sample[0]),candidate)
    called=[];runner.scenes.dispatch=lambda *args:called.append(args) or {'ok':True,'probes':[]}
    args={'probes':[{'tab':0,'checks':[{'relation':'same_x','points':['A','B'],'expected':True}]}]}
    try:
        result=runner.dispatch_stage_tool('diagram_review',runner.request,'inspect_scene',args)
        assert not called and result['execution_failure']['kind']=='query_only'
        args['probes'][0]['checks'][0].pop('expected')
        assert runner.dispatch_stage_tool('diagram_review',runner.request,'inspect_scene',args)['ok']
        assert len(called)==1
    finally:runner.provider.close()


def test_delta_runtime_rejects_unchanged_tab(settings,job,sample):
    runner=Runner(settings,job[1],cache_factory=MemoryCache,renderer=renderer)
    runner.review_change_tabs=[1];called=[];runner.scenes.dispatch=lambda *args:called.append(args)
    try:
        with pytest.raises(ValueError,match='实际变化画板'):
            runner.dispatch_stage_tool('diagram_review',runner.request,'inspect_scene',{'probes':[{'tab':0,'checks':[]}]})
        assert not called
    finally:runner.provider.close()


def test_saved_certificate_chain_detects_missing_or_modified_history(tmp_path,sample):
    from math_agent.review_reuse import check_certificate_chain
    s,c,r,req,obs=prepare(sample,tmp_path);snap=Snapshot(s,c,r,obs,req,tmp_path)
    record={'sha256':snap.certificate,'binding':snap.binding,'review':r.model_dump()}
    merged=r.model_copy(deep=True);merged.questions[0].evidence='数学复核沿用证书'+snap.certificate+'；本次已复查图形'
    check_certificate_chain(s,merged,[record])
    with pytest.raises(ValueError,match='未保存'):check_certificate_chain(s,merged,[])
    changed=copy.deepcopy(record);changed['review']['questions'][0]['evidence']='tampered'
    with pytest.raises(ValueError,match='摘要'):check_certificate_chain(s,merged,[changed])


def test_cached_delta_page_keeps_underlying_review_evidence(settings,job,sample):
    import json
    from math_agent.storage import write_json
    from test_compact_review import pack_review
    source,candidate,good=copy.deepcopy(sample)
    objection=copy.deepcopy(good);objection.update(verdict='revise',issues=[{'stage':'diagram','target':'Q1','detail':'补边'}])
    patch={'edits':[{'tab':0,'upsert':[{'id':'extra_edge','kind':'segment','parents':['A','B']}]}]}
    delta={'verdict':'pass','questions':[{'id':'Q1','verdict':'pass','evidence':'新图检查通过'}],
           'resolutions':[{'id':'I1','verdict':'resolved','evidence':'补边已核对'}],'issues':[]}
    configured=replace(settings,compact_tools=True,incremental_review=True);stages=[]
    runner=Runner(configured,job[1],provider([source,pack(candidate),pack_review(objection),resolution(objection,candidate),patch,delta],stages),MemoryCache,renderer)
    runner.run();assert job[0].get(job[1])['status']=='completed'
    assert len(runner.cache.data['review_certificates'])==2
    new_id,path=job[0].prepare();write_json(path/'request.json',json.loads((job[2]/'request.json').read_text()))
    job[0].enqueue(new_id);assert job[0].claim()==new_id
    cached=Runner(configured,new_id,provider([],stages),MemoryCache,renderer);cached.cache.data=runner.cache.data
    cached.run();assert job[0].get(new_id)['status']=='completed' and cached.provider.calls==0
    assert len(json.loads((path/'review-certificates.json').read_text()))==2
