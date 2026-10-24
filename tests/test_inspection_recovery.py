import copy
import json
import os
import pytest
from math_agent.inspection_recovery import target, reconcile
from math_agent.pipeline import Runner
from test_pipeline import MemoryCache


def failure(check=None):
    check=check or {'relation':'same_y','points':['A','B'],'expected':True}
    return {'result':{'ok':False,'error':'bad basis','execution_failure':{
        'spec_sha256':'v1','targets':[target({'tab':0},check)]}}}


def success(**changes):
    check={'relation':'same_y','points':['A','B'],'expected':True,'holds':True,'matches_expected':True}
    check.update(changes)
    return {'result':{'ok':True,'spec_sha256':'v1','probes':[{'tab':0,'parameter':None,'in_domain':True,'checks':[check]}]}}


def test_only_later_same_check_resolves_execution_failure():
    assert len(reconcile([failure(),success()],'v1')['resolved'])==1
    assert reconcile([success(),failure()],'v1')['unresolved']
    assert reconcile([failure(),success(points=['A','C'])],'v1')['unresolved']
    assert reconcile([failure(),success(expected=False)],'v1')['unresolved']
    assert reconcile([failure(),success(expected=None)],'v1')['unresolved']
    assert reconcile([failure(),success(error='still failed')],'v1')['unresolved']
    assert reconcile([failure(),success()],'v2')['unresolved']
    assert reconcile([{'result':{'ok':False}},success()],'v1')['unresolved']


@pytest.mark.parametrize('field,value',[('tab',1),('parameter',.5),('in_domain',False)])
def test_other_tab_parameter_or_outside_domain_cannot_resolve(field,value):
    good=success();good['result']['probes'][0][field]=value
    assert reconcile([failure(),good],'v1')['unresolved']


def test_successful_execution_is_not_mathematical_pass():
    good=success(holds=False,matches_expected=False)
    original=copy.deepcopy(good)
    assert not reconcile([failure(),good],'v1')['unresolved']
    assert good==original and good['result']['probes'][0]['checks'][0]['matches_expected'] is False


def test_every_failed_check_must_be_redone():
    other=failure({'relation':'same_x','points':['A','B'],'expected':True})
    result=reconcile([failure(),other,success()],'v1')
    assert len(result['resolved'])==1 and len(result['unresolved'])==1


@pytest.mark.skipif(os.getenv('MATH_AGENT_BROWSER_TEST')!='1',reason='真实浏览器流程')
@pytest.mark.parametrize('error_mode',['basis','browser'])
def test_corrected_basis_reaches_diagram_and_final_review(settings,job,sample,error_mode):
    source,candidate,passed=copy.deepcopy(sample)
    source['conditions'].append({'id':'C2','text':'仅第二问条件','origin':'question_text','image_ids':[],'question_ids':['Q2']})
    passed['conditions'].append({'id':'C2','verdict':'pass','evidence':'测试夹具条件'})
    for tab in candidate['spec']['tabs']:
        tab.pop('controls',None)
        tab['board']={'bounding_box':[-1,2,3,-1],'objects':[{'id':'A','kind':'point','coords':[0,0]},
            {'id':'B','kind':'point','coords':[2,0]},{'id':'M','kind':'midpoint','parents':['A','B']}]}
    stages=[]
    class Model:
        def __init__(self,settings,audit):self.calls=0;self.audit=audit;self.reviews=0
        def close(self):pass
        def generate(self,stage,messages,tools,dispatch):
            self.calls+=1;stages.append(stage)
            if stage=='source':return source
            if stage in {'solve','diagram'}:return candidate
            if stage=='adjudicate':
                from test_objection_gate import resolution
                value=copy.deepcopy(passed);value.update(verdict='revise',issues=[{'stage':'diagram','target':'test','detail':'测试修图路由，不删除该异议'}])
                return resolution(value,candidate)
            self.reviews+=1
            def inspect(basis):
                args={'probes':[{'tab':0,'checks':[{'relation':'same_y','points':['A','B'],
                    'expected':True,'basis_ids':[basis],'rationale':'验证横坐标轴上的两个点'}]}]}
                result=dispatch('inspect_scene',args)
                self.audit('tool',{'stage':stage,'name':'inspect_scene','arguments':json.dumps(args),'result':result})
                return result
            if self.reviews==1:
                if error_mode=='basis':
                    bad=inspect('C2')
                else:
                    original=runner.scenes.dispatch
                    def temporary_failure(name,args):
                        check={**args['probes'][0]['checks'][0], 'error':'temporary browser read failure',
                            'holds':None,'matches_expected':False}
                        return {'ok':False,'assertions_pass':False,'probes':[{'tab':0,'parameter':None,'checks':[check]}]}
                    runner.scenes.dispatch=temporary_failure
                    try:bad=inspect('C1')
                    finally:runner.scenes.dispatch=original
                assert bad['ok'] is False
                good=inspect('C1');assert good['ok'] is True and good['assertions_pass']
                value=copy.deepcopy(passed);value.update(verdict='revise',issues=[{'stage':'diagram','target':'test','detail':'测试修图路由，不删除该异议'}])
                return value
            assert inspect('C1')['ok'] is True
            return passed
    runner=Runner(settings,job[1],Model,MemoryCache)
    runner.run()
    assert job[0].get(job[1])['status']=='completed'
    assert stages==['source','solve','review','adjudicate','diagram','review']
    report=json.loads((job[2]/'report.json').read_text())
    recovered=[a for a in report['audit'] if a['kind']=='inspection_recovery']
    assert len(recovered[0]['resolved'])==1 and not recovered[0]['unresolved']
    assert any(a['kind']=='repair' and a['stage']=='diagram' for a in report['audit'])


def test_dynamic_default_matches_explicit_same_position():
    check={'relation':'same_y','points':['A','B'],'expected':True}
    spec={'tabs':[{'controls':{'slider':{'default':.5}}}]}
    assert target({'tab':0},check,spec)==target({'tab':0,'parameter':.5},check)
    assert target({'tab':0,'parameter':0},check,spec)!=target({'tab':0},check,spec)


def test_impossible_arity_is_referred_not_resolved_or_silently_removed():
    from math_agent.inspection_recovery import partition_pending
    spec={'tabs':[{'board':{'objects':[{'id':i} for i in ['A','B','C']]}}]}
    bad=failure({'relation':'collinear','points':['A','B','C','B'],'expected':True})
    recovery=reconcile([bad],'v1')
    blocked, referred=partition_pending(recovery['unresolved'],spec)
    assert not blocked and len(referred)==1 and recovery['unresolved']
    assert referred[0]['required_point_count']==3
    assert partition_pending(reconcile([failure()],'v1')['unresolved'],spec)[0]
    assert partition_pending(reconcile([bad],'other')['unresolved'],spec)[0]
    unknown=failure({'relation':'collinear','points':['A','B','missing','B'],'expected':True})
    assert partition_pending(reconcile([unknown],'v1')['unresolved'],spec)[0]


@pytest.mark.parametrize('verdict',['invalid_check','real_issue','unresolved'])
@pytest.mark.parametrize('failure_kind',['arity','basis_validation','invalid_reference'])
def test_malformed_query_must_get_independent_verdict_and_keep_math_issue(settings,job,sample,verdict,failure_kind):
    from math_agent.contracts import Source,Candidate,Review
    from math_agent.pipeline import canonical_page,NeedsInput
    from math_agent.scene_tools import fingerprint
    from math_agent.rendering import strict_spec
    from test_pipeline import renderer
    src=Source.model_validate(sample[0]);candidate=canonical_page(Candidate.model_validate(sample[1]),src)
    original=copy.deepcopy(sample[2]);original.update(verdict='revise',issues=[{'stage':'math','target':'Q1','detail':'真实数学异议不能被撤销'}])
    point=next(o['id'] for o in candidate.spec['tabs'][0]['board']['objects'] if o['kind']=='point')
    q={'relation':'collinear' if failure_kind=='arity' else 'same_y','points':[point]*(4 if failure_kind=='arity' else 2),'expected':True}
    if failure_kind=='invalid_reference':q['points']=[point,'missing-point']
    stages=[]
    class Model:
        def __init__(self,settings,audit):self.audit=audit;self.calls=0
        def close(self):pass
        def generate(self,stage,messages,**kwargs):
            stages.append(stage);self.calls+=1
            if stage=='review':
                if stages.count('review')>1:return copy.deepcopy(sample[2])
                self.audit('tool',{'stage':stage,'name':'inspect_scene','result':{'ok':False,
                    'execution_failure':{'kind':failure_kind,'spec_sha256':fingerprint(strict_spec(candidate.spec)),
                                         'targets':[target({'tab':0},q,candidate.spec)]}}})
                return original
            assert stage=='deferred_review'
            context=json.loads(messages[-1]['content'][0]['text'])['context']
            obligation=context['obligations'][0]
            assert obligation['failure']['kind']=='invalid_query'
            assert obligation['failure']['referral_reason']=={'arity':'invalid_point_count','basis_validation':'invalid_basis','invalid_reference':'invalid_point_reference'}[failure_kind]
            return {'current_hash':context['current_hash'],'resolutions':[{'id':obligation['id'],
                'origin_hash':obligation['origin_hash'],'verdict':verdict,
                'scopes':[{'question_id':'Q1','object_ids':[point],'basis_ids':['C1']}],
                'reason':'四点不是合法三点共线检查；原题条件需依据相应合法数学推导独立核对，不能由这个错误查询推出几何失败。',
                'issue':{'stage':'math','target':'Q2','detail':'裁决另确认的问题'} if verdict=='real_issue' else None}]}
    runner=Runner(settings,job[1],Model,MemoryCache,renderer)
    first=runner.review(src,candidate,{})
    assert first.verdict=='revise' and first.issues[0].detail=='真实数学异议不能被撤销'
    assert stages==['review'] and len(runner.deferred_reviews.pending)==1
    changed=candidate.model_copy(deep=True)
    changed.solutions[0].result='修订后的解答，尚需独立复核'
    canonical_page(changed,src)
    if verdict=='unresolved':
        with pytest.raises(NeedsInput):runner.review(src,changed,{})
        assert runner.deferred_reviews.pending
    else:
        result=runner.review(src,changed,{})
        assert result.verdict==('revise' if verdict=='real_issue' else 'pass')
        assert len(result.issues)==(1 if verdict=='real_issue' else 0)
        assert not runner.deferred_reviews.pending
    assert stages==['review','review','deferred_review']


@pytest.mark.skipif(os.getenv('MATH_AGENT_BROWSER_TEST')!='1',reason='真实浏览器流程')
def test_native_invalid_arity_reaches_adjudicator_without_replaying_impossible_query(settings,job,sample):
    from math_agent.contracts import Source,Candidate
    from math_agent.pipeline import canonical_page
    from test_pipeline import renderer
    src=Source.model_validate(sample[0]);candidate=canonical_page(Candidate.model_validate(sample[1]),src)
    point=next(o['id'] for o in candidate.spec['tabs'][0]['board']['objects'] if o['kind']=='point')
    stages=[]
    class Model:
        def __init__(self,settings,audit):self.audit=audit;self.calls=0
        def close(self):pass
        def generate(self,stage,messages,dispatch,**kwargs):
            stages.append(stage);self.calls+=1
            args={'probes':[{'tab':0,'checks':[{'relation':'collinear' if stage=='review' else 'same_x',
                'points':[point]*(4 if stage=='review' else 2)}]}]}
            result=dispatch('inspect_scene',args)
            self.audit('tool',{'stage':stage,'name':'inspect_scene','arguments':json.dumps(args),'result':result})
            if stage=='review':
                assert result['ok'] is False and result['execution_failure']['targets']
                assert result['invalid_queries'][0]['required_point_count']==3
                assert '不能原样重做' in result['recovery_hint']
                return sample[2]
            assert stage=='adjudicate' and result['ok'] is True
            return {'decisions':[{'assertion_id':'A1','verdict':'invalid_check','basis_ids':['C1'],
                'reason':'四个重复点不构成有效的三点共线检查；只读查询已经确认该对象可被正常观察，原有题设核验仍需独立保留。','issue':None}]}
    runner=Runner(settings,job[1],Model,MemoryCache,renderer)
    assert runner.review(src,candidate,{}).verdict=='pass'
    assert stages==['review','adjudicate']
    assert (job[2]/'adjudication-01.json').exists()


def test_invalid_basis_can_be_adjudicated_but_runtime_failure_cannot():
    from math_agent.inspection_recovery import partition_pending
    spec={'tabs':[{'board':{'objects':[{'id':'A'},{'id':'B'}]}}]}
    bad=failure();bad['result']['execution_failure']['kind']='basis_validation'
    blocked,referred=partition_pending(reconcile([bad],'v1')['unresolved'],spec)
    assert not blocked and referred[0]['referral_reason']=='invalid_basis'
    bad['result']['execution_failure']['kind']='browser_execution'
    assert partition_pending(reconcile([bad],'v1')['unresolved'],spec)[0]
