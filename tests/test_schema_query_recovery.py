import copy,json
import pytest
from math_agent.inspection_recovery import schema_failure,reconcile,partition_pending
from math_agent.scene_tools import SceneTools,fingerprint
from math_agent.rendering import strict_spec
from math_agent.contracts import Source,Candidate
from math_agent.pipeline import Runner,canonical_page
from test_pipeline import MemoryCache,renderer


def inputs(sample):
    src=Source.model_validate(sample[0]);c=Candidate.model_validate(sample[1])
    for tab in c.spec['tabs']:
        tab.pop('controls',None)
        tab['board']={'bounding_box':[-1,2,3,-1],'objects':[{'id':'A','kind':'point','coords':[0,0]},{'id':'B','kind':'point','coords':[2,0]}]}
    canonical_page(c,src)
    args={'probes':[{'tab':0,'checks':[{'relation':'same_y','points':['A','B'],'expected':True,'basis_ids':['C1'],'rationale':'由题设确认两个点均在横轴上'}]}]}
    return src,c,args


def observed(c,args,holds=True):
    t=args['probes'][0];check=t['checks'][0]
    return {'result':{'ok':True,'spec_sha256':fingerprint(strict_spec(c.spec)),
        'probes':[{'tab':t['tab'],'parameter':t.get('parameter'),'in_domain':True,'checks':[
            {**check,'holds':holds,'matches_expected':holds==check.get('expected')}]}]}}


@pytest.mark.parametrize('where',['root','probe','check'])
def test_invalid_metadata_is_not_executed_or_autocorrected_but_exact_redo_can_resolve(sample,tmp_path,where):
    s,c,args=inputs(sample);bad=copy.deepcopy(args)
    (bad if where=='root' else bad['probes'][0] if where=='probe' else bad['probes'][0]['checks'][0])['basiss']=[]
    old=copy.deepcopy(bad);scenes=SceneTools(tmp_path);scenes.current=c.spec
    result=scenes.dispatch('inspect_scene',bad)
    assert not result['ok'] and scenes.count==0 and bad==old
    assert 'basiss' in result['schema_error']['message'] and len(result['execution_failure']['targets'])==1
    recovery=reconcile([{'result':result},observed(c,args)],fingerprint(strict_spec(c.spec)))
    assert len(recovery['resolved'])==1 and not recovery['unresolved']


@pytest.mark.parametrize('change',['different_points','different_expected','drop_expected','different_graph','different_tab','different_parameter'])
def test_schema_fault_cannot_be_cleared_by_changed_target_or_assertion(sample,change):
    s,c,args=inputs(sample);bad=copy.deepcopy(args);bad['probes'][0]['checks'][0]['basiss']=[]
    failure={'result':schema_failure(bad,c.spec)};good=observed(c,args)
    check=good['result']['probes'][0]['checks'][0]
    if change=='different_points':check['points']=['B','A']
    elif change=='different_expected':check['expected']=False
    elif change=='drop_expected':check.pop('expected')
    elif change=='different_graph':good['result']['spec_sha256']='another'
    elif change=='different_tab':good['result']['probes'][0]['tab']=1
    else:good['result']['probes'][0]['parameter']=0.5
    assert reconcile([failure,good],fingerprint(strict_spec(c.spec)))['unresolved']


@pytest.mark.parametrize('bad_expected',['true',1,None])
def test_ambiguous_assertion_type_remains_unbound_without_guessing(sample,bad_expected):
    s,c,args=inputs(sample);args['probes'][0]['checks'][0]['expected']=bad_expected
    result=schema_failure(args,c.spec)
    assert result['execution_failure']['targets']==[]
    assert partition_pending(reconcile([{'result':result}],fingerprint(strict_spec(c.spec)))['unresolved'],c.spec)[0]


def test_successful_redo_with_false_math_result_is_not_a_pass(sample):
    s,c,args=inputs(sample);bad=copy.deepcopy(args);bad['extra']=True
    failure={'result':schema_failure(bad,c.spec)};good=observed(c,args,False)
    assert not reconcile([failure,good],fingerprint(strict_spec(c.spec)))['unresolved']
    assert good['result']['probes'][0]['checks'][0]['matches_expected'] is False


@pytest.mark.parametrize('stage',['review','review_plan','adjudicate','graph_review','diagram_review','deferred_review'])
def test_every_readonly_pipeline_returns_bound_schema_error_before_basis_or_execution(settings,job,sample,stage):
    s,c,args=inputs(sample);args['probes'][0]['checks'][0]['basiss']=[]
    runner=Runner(settings,job[1],cache_factory=MemoryCache,renderer=renderer)
    runner.review_candidate=c;runner.scenes.current=c.spec;runner.save_ledger(s,c)
    result=runner.dispatch_stage_tool(stage,runner.request,'inspect_scene',args)
    assert result['execution_failure']['kind']=='schema_validation' and result['execution_failure']['targets']
    assert runner.scenes.count==0
    runner.provider.close()


def test_whole_rejected_batch_must_be_redone_not_only_one_valid_part(sample):
    s,c,args=inputs(sample);args['probes'][0]['checks'].append({'relation':'same_x','points':['A','B']})
    args['probes'][0]['checks'][0]['basiss']=[]
    error=schema_failure(args,c.spec)
    assert len(error['execution_failure']['targets'])==2
    assert len(reconcile([{'result':error},observed(c,args)],fingerprint(strict_spec(c.spec)))['unresolved'])==1


def test_bad_relation_type_never_crashes_or_invents_a_target(sample):
    s,c,args=inputs(sample);args['probes'][0]['checks'][0]['relation']=['same_y']
    assert schema_failure(args,c.spec)['execution_failure']['targets']==[]


@pytest.mark.skipif(__import__('os').getenv('MATH_AGENT_BROWSER_TEST')!='1',reason='实际浏览器恢复链')
def test_model_typo_then_exact_native_query_completes_review_without_extra_format_round(settings,job,sample,monkeypatch):
    s,c,args=inputs(sample);stages=[]
    monkeypatch.setattr('math_agent.proof_guards.collect',lambda *a:{'failures':[],'observations':[],'unobserved':[]})
    class Model:
        calls=0
        def __init__(self,settings,audit):self.audit=audit
        def generate(self,stage,messages,**kw):
            stages.append(stage);self.calls+=1
            assert stage=='review'
            bad=copy.deepcopy(args);bad['probes'][0]['checks'][0]['basiss']=[]
            for value in (bad,args):
                result=kw['dispatch']('inspect_scene',value)
                self.audit('tool',{'stage':stage,'name':'inspect_scene','arguments':json.dumps(value),'result':result})
            assert result['ok'] and result['assertions_pass']
            return sample[2]
    runner=Runner(settings,job[1],provider_factory=Model,cache_factory=MemoryCache,renderer=renderer)
    value=runner.review(s,c,{})
    assert value.verdict=='pass' and stages==['review']
    rec=[r for r in runner.records if r['kind']=='inspection_recovery'][-1]
    assert len(rec['resolved'])==1 and not rec['unresolved']
    assert not any(r['kind']=='contract_error' for r in runner.records)
