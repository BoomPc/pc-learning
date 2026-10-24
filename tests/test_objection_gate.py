import copy
import pytest
from math_agent.contracts import Adjudication, Review, Source, Candidate
from math_agent.objection_review import validate_resolution
from math_agent.pipeline import Runner
from test_pipeline import provider, renderer, MemoryCache


def resolution(original, candidate, reject=False, reviewed=None):
    q=candidate['solutions'][0]['question_id']
    obj=candidate['spec']['tabs'][0]['board']['objects'][0]['id']
    return {'decisions':[{'assertion_id':f'R{i+1}', 'verdict':'invalid_check' if reject else 'real_issue',
        'scopes':[{'question_id':q,'object_ids':[obj],'basis_ids':['C1']}],
        'reason':'独立核对题设、对应小问和真实对象观察；此处为流程夹具，验证意见必须经过逐项明确裁决。',
        'issue':None if reject else issue} for i,issue in enumerate(original['issues']) if issue['stage']=='diagram'],
        'reviewed':copy.deepcopy(reviewed or original)}


def test_explicit_false_textual_objection_does_not_trigger_repair(settings,job,sample):
    source,candidate,good=sample
    objection=copy.deepcopy(good);objection.update(verdict='revise',issues=[{'stage':'diagram','target':'tab0','detail':'向量方向反了'}])
    stages=[]
    Runner(settings,job[1],provider([source,candidate,objection,resolution(objection,candidate,True,good)],stages),MemoryCache,renderer).run()
    assert stages==['source','solve','review','adjudicate']
    assert job[0].get(job[1])['status']=='completed'
    assert (job[2]/'adjudication-01.json').is_file()


@pytest.mark.parametrize('mutation',['no_review','erase_math','unknown','unchanged_evidence'])
def test_incomplete_or_overbroad_resolution_rejected(sample,mutation):
    source,candidate,good=sample
    original=copy.deepcopy(good);original.update(verdict='revise',issues=[{'stage':'diagram','target':'tab0','detail':'需要核验'}])
    data=resolution(original,candidate,True,good)
    if mutation=='no_review':data['reviewed']=None
    if mutation=='erase_math':original['issues'].append({'stage':'math','target':'Q1','detail':'独立数学问题不能删除'})
    if mutation=='unknown':original['questions'][0]['verdict']='unknown'
    if mutation=='unchanged_evidence':original['questions'][0]['verdict']='issue'
    with pytest.raises(ValueError):validate_resolution(Adjudication.model_validate(data),Review.model_validate(original),Source.model_validate(source))


@pytest.mark.parametrize('mutation',['omit','wrong_object','wrong_scope'])
def test_scope_and_coverage_gate_blocks_before_repair(settings,job,sample,mutation):
    source,candidate,good=sample
    original=copy.deepcopy(good);original.update(verdict='revise',issues=[{'stage':'diagram','target':'tab0','detail':'方向需核验'}])
    data=resolution(original,candidate,True,good)
    if mutation=='omit':data['decisions'][0]['assertion_id']='R404'
    if mutation=='wrong_object':data['decisions'][0]['scopes'][0]['object_ids']=['not_an_object']
    if mutation=='wrong_scope':data['decisions'][0]['scopes'][0]['question_id']='Q404'
    stages=[]
    Runner(settings,job[1],provider([source,candidate,original,data,data],stages),MemoryCache,renderer).run()
    assert job[0].get(job[1])['status']=='failed'
    assert 'diagram' not in stages


@pytest.mark.parametrize('redo_same_query',[True,False])
def test_adjudication_query_only_error_requires_same_successful_query(settings,job,sample,redo_same_query):
    from math_agent.scene_tools import fingerprint
    from math_agent.rendering import strict_spec
    source,candidate,good=sample
    original=copy.deepcopy(good);original.update(verdict='revise',issues=[{'stage':'diagram','target':'tab0','detail':'位置有误'}])
    for tab in candidate['spec']['tabs']:
        tab.pop('controls',None)
        tab['board']={'bounding_box':[-1,2,3,-1],'objects':[{'id':'A','kind':'point','coords':[0,0]}, {'id':'B','kind':'point','coords':[1,0]}]}
    def generated(settings,audit):
        class Model:
            calls=0
            def close(self):pass
            def generate(self,stage,messages,tools,dispatch):
                self.calls+=1
                args={'probes':[{'tab':0,'checks':[{'relation':'same_y','points':['A','B'],'expected':True}]}]}
                failed=dispatch('inspect_scene',args)
                assert failed['execution_failure']['kind']=='query_only'
                audit('tool',{'name':'inspect_scene','result':failed})
                args['probes'][0]['checks'][0].pop('expected')
                if not redo_same_query:args['probes'][0]['checks'][0]['relation']='same_x'
                passed=dispatch('inspect_scene',args)
                audit('tool',{'name':'inspect_scene','result':passed})
                return resolution(original,candidate,True,good)
        return Model()
    runner=Runner(settings,job[1],generated,MemoryCache,renderer)
    value=Candidate.model_validate(candidate);src=Source.model_validate(source)
    runner.save_ledger(src,value);runner.review_candidate=value;runner.scenes.current=value.spec
    # Controlled browser transport; real-browser recovery integration remains in test_inspection_recovery.
    def scene(name,args):
        probes=copy.deepcopy(args['probes'])
        for p in probes:
            p.update(in_domain=True,parameter=None)
            for c in p['checks']:c.update(holds=True)
        return {'ok':True,'spec_sha256':fingerprint(strict_spec(value.spec)),'probes':probes}
    runner.scenes.dispatch=scene
    objections=[{'id':'R1','kind':'review_issue','issue':original['issues'][0]}]
    if redo_same_query:
        assert runner.adjudicate(src,value,{},objections,Review.model_validate(original)).reviewed.verdict=='pass'
    else:
        with pytest.raises(ValueError,match='尚未完成'):runner.adjudicate(src,value,{},objections,Review.model_validate(original))


def test_review_verdict_mismatch_is_corrected_by_model_not_auto_pass(settings,job,sample):
    source,candidate,good=sample
    bad=copy.deepcopy(good);bad['verdict']='revise'
    seen=[]
    def factory(settings,audit):
        class Model:
            calls=0
            def close(self):pass
            def generate(self,stage,messages,tools,dispatch):
                self.calls+=1;seen.append(messages)
                if self.calls==1:return bad
                text=str(messages)
                assert 'verdict=revise要求issues至少一项' in text
                assert '这是复核/裁决输出纠错' in text
                return good
        return Model()
    runner=Runner(settings,job[1],factory,MemoryCache,renderer)
    result=runner.review(Source.model_validate(source),Candidate.model_validate(candidate),{})
    assert result.verdict=='pass' and len(seen)==2
    assert Review.model_json_schema()['allOf'][0]['then']['properties']['issues']['minItems']==1


@pytest.mark.parametrize('cross_scope_misuse',[False,True])
def test_multi_question_objection_keeps_each_local_basis_separate(settings,job,sample,cross_scope_misuse):
    source,candidate,good=sample
    original=copy.deepcopy(good);original.update(verdict='revise',issues=[{'stage':'diagram','target':'tab0/tab1','detail':'跨小问意见'}])
    data=resolution(original,candidate,True,good)
    scopes=[]
    for i,solution in enumerate(candidate['solutions']):
        q=solution['question_id'];obj=candidate['spec']['tabs'][i]['board']['objects'][0]['id']
        scopes.append({'question_id':q,'object_ids':[obj],'basis_ids':[q+':S1']})
    if cross_scope_misuse:scopes[1]['basis_ids']=['Q1:S1']
    data['decisions'][0]['scopes']=scopes
    stages=[]
    Runner(settings,job[1],provider([source,candidate,original,data,data],stages),MemoryCache,renderer).run()
    status=job[0].get(job[1])['status']
    assert status==('failed' if cross_scope_misuse else 'completed')
    if cross_scope_misuse:assert 'R1/Q2' in job[0].get(job[1])['error']


def test_final_review_returns_pending_checks_to_model_without_dropping_them(settings,job,sample):
    from math_agent.scene_tools import fingerprint
    from math_agent.rendering import strict_spec
    source,candidate,good=sample
    for tab in candidate['spec']['tabs']:
        tab.pop('controls',None)
        tab['board']={'bounding_box':[-1,2,3,-1],'objects':[{'id':'A','kind':'point','coords':[0,0]},{'id':'B','kind':'point','coords':[1,0]}]}
    seen=[]
    def factory(settings,audit):
        class Model:
            calls=0
            def close(self):pass
            def generate(self,stage,messages,tools,dispatch):
                self.calls+=1;seen.append(messages)
                if self.calls==2:assert '待办' in str(messages) and 'same_y' in str(messages)
                args={'probes':[{'tab':0,'checks':[{'relation':'same_y','points':['A','B'],'expected':True,
                    'basis_ids':['C1'],'rationale':'核对当前图'}]}]}
                response=dispatch('inspect_scene',args)
                if self.calls==1:
                    from math_agent.inspection_recovery import target
                    response={'ok':False,'error':'browser unavailable','execution_failure':{'kind':'browser_execution',
                        'spec_sha256':fingerprint(strict_spec(candidate['spec'])),
                        'targets':[target(args['probes'][0],args['probes'][0]['checks'][0],candidate['spec'])]}}
                audit('tool',{'name':'inspect_scene','result':response})
                return good
        return Model()
    runner=Runner(settings,job[1],factory,MemoryCache,renderer)
    def scene(name,args):
        probes=copy.deepcopy(args['probes'])
        for p in probes:
            p.update(in_domain=True,parameter=None)
            for c in p['checks']:c.update(holds=True,matches_expected=True)
        return {'ok':True,'assertions_pass':True,'spec_sha256':fingerprint(strict_spec(candidate['spec'])),'probes':probes}
    runner.scenes.dispatch=scene
    assert runner.review(Source.model_validate(source),Candidate.model_validate(candidate),{}).verdict=='pass'
    assert len(seen)==2
    recovery=[r for r in runner.records if r['kind']=='inspection_recovery'][-1]
    assert len(recovery['resolved'])==1 and not recovery['unresolved']
