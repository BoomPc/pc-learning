import copy
import json
import pytest
from PIL import Image
from math_agent.contracts import Source, Candidate, check_candidate, check_source
from math_agent.evidence import build_ledger, validate_basis, record_hypothesis
from math_agent.image_tools import ImageTools, VIEW_REGION
from math_agent.pipeline import Runner
from test_pipeline import MemoryCache, renderer


def test_evidence_scope_goals_and_hypotheses_are_not_premises(sample):
    source=Source.model_validate(sample[0]);source.conditions[0].question_ids=['Q1']
    ledger=build_ledger(source,Candidate.model_validate(sample[1]))
    validate_basis(ledger,['C1'],'Q1')
    for ids,q in [(['C1'],'Q2'),(['Q1'],'Q1'),(['Q1:S1'],'Q2')]:
        with pytest.raises(ValueError):validate_basis(ledger,ids,q)
    result=record_hypothesis(ledger,'Q1','可能有两根',['C1'],'解方程并检查定义域')
    assert result['entry']['status']=='unverified_do_not_use_as_premise'
    with pytest.raises(ValueError):validate_basis(ledger,['H1'],'Q1')


def test_step_cannot_cite_future_step_or_goal(sample):
    source=Source.model_validate(sample[0]);candidate=Candidate.model_validate(sample[1])
    for ref in ['Q1','Q1:S2','C404']:
        candidate.solutions[0].steps[0].basis_ids=[ref]
        with pytest.raises(ValueError,match='步骤依据'):check_candidate(candidate,source)
    source.conditions[0].question_ids=['Q404']
    with pytest.raises(ValueError,match='Q404.*Q1.*Q2'):check_source(source,[])


def test_crop_returns_real_pixels_and_role_without_arbitrary_file_access(tmp_path):
    Image.new('RGB',(200,100),(125,30,90)).save(tmp_path/'q.png')
    tool=ImageTools(tmp_path,[{'id':'I1','role':'answer','file':'q.png'}])
    result=tool.view('I1',[.25,0,.75,1],'核对撇号')
    assert result.metadata['role']=='answer'
    assert result.metadata['pixel_box']==(50,0,150,100)
    with Image.open(tmp_path/result.metadata['artifact']) as image:
        assert image.getpixel((10,10))==(125,30,90)
    for args in [('bad',[0,0,1,1],'未知图'),('I1',[0,0,0,1],'空框'),('I1',[0,0,float('nan'),1],'非法')]:
        with pytest.raises(ValueError):tool.view(*args)
    assert result.data_url.startswith('data:image/png;base64,')


def test_crop_pixels_reach_next_model_turn_but_not_audit(tmp_path):
    from math_agent.agent_loop import run_loop
    from math_agent.provider import ModelError
    Image.new('RGB',(100,100),'white').save(tmp_path/'q.png')
    tool=ImageTools(tmp_path,[{'id':'I1','role':'question','file':'q.png'}])
    records=[];turns=[]
    def request(history,definitions):
        turns.append(history)
        if len(turns)==1:
            return {'role':'assistant','content':None,'tool_calls':[{'id':'call1','type':'function','function':{'name':'view_image_region','arguments':json.dumps({'image_id':'I1','bbox':[0,0,1,1],'reason':'核对公式'})}}]},'tool_calls'
        assert history[-2]['role']=='tool'
        assert history[-1]['content'][1]['type']=='image_url'
        return {'role':'assistant','content':'{"read":true}'},'stop'
    result=run_loop(request,[{'role':'user','content':'原题'}],[VIEW_REGION],lambda name,args:tool.view(**args),lambda k,d:records.append((k,d)),'source',ModelError)
    assert result=={'read':True}
    assert 'base64' not in json.dumps(records)


def failure():
    return {'ok':True,'assertions_pass':False,'probes':[{'tab':0,'parameter':None,'checks':[
        {'relation':'parallel','points':['A','B','C','D'],'expected':True,'holds':False,
         'matches_expected':False,'basis_ids':['C1'],'rationale':'错误地把旋转当成平移'}]}]}


def adjudication_model(queue, stages):
    class Model:
        def __init__(self,settings,audit):self.calls=0;self.audit=audit;self.reviews=0
        def generate(self,stage,*args,**kwargs):
            stages.append(stage);self.calls+=1
            if stage=='deferred_review':
                payload=json.loads(args[0][-1]['content'][0]['text'])['context']
                o=payload['obligations'][0]
                point=next(i['id'] for i in payload['candidate']['spec']['tabs'][0]['board']['objects'] if i['kind']=='point')
                return {'current_hash':payload['current_hash'],'resolutions':[{'id':o['id'],'origin_hash':o['origin_hash'],
                    'verdict':'invalid_check','scopes':[{'question_id':'Q1','object_ids':[point],'basis_ids':['C1']}],
                    'reason':'原题并没有要求这两条边平行，已重新核对题设与变换；无效原检查不能删除已发现的数学异议。','issue':None}]}
            if stage=='review':
                self.reviews+=1
                if self.reviews==1:self.audit('tool',{'stage':stage,'name':'inspect_scene','result':failure()})
            return copy.deepcopy(queue.pop(0))
        def close(self):pass
    return Model


def decision(verdict,issue=None):
    return {'decisions':[{'assertion_id':'A1','verdict':verdict,'basis_ids':['C1'],
        'reason':'原题条件并没有给出对应边平行；必须按题设和实际变换性质判断，而不能把数值不平行直接当作构图错误。','issue':issue}]}


def test_false_expectation_goes_to_independent_adjudication_not_diagram(settings,job,sample):
    stages=[];source,candidate,review=sample
    runner=Runner(settings,job[1],adjudication_model([source,candidate,review,decision('invalid_check')],stages),MemoryCache,renderer)
    runner.run()
    assert stages==['source','solve','review','adjudicate']
    assert job[0].get(job[1])['status']=='completed'
    assert (job[2]/'adjudication-01.json').is_file()
    assert (job[2]/'evidence-ledger.json').is_file()


def test_real_math_issue_returns_to_solver(settings,job,sample):
    stages=[];source,candidate,review=sample
    d=decision('real_issue',{'stage':'math','target':'Q1','detail':'推导条件不成立，需重新解题'})
    Runner(settings,job[1],adjudication_model([source,candidate,review,d,{'solutions':candidate['solutions']},review],stages),MemoryCache,renderer).run()
    assert stages==['source','solve','review','adjudicate','math_repair','review']
    assert job[0].get(job[1])['status']=='completed'


def test_unresolved_adjudication_never_publishes(settings,job,sample):
    stages=[];source,candidate,review=sample
    Runner(settings,job[1],adjudication_model([source,candidate,review,decision('unresolved')],stages),MemoryCache,renderer).run()
    assert job[0].get(job[1])['status']=='needs_input'


def test_adjudication_cannot_omit_failed_assertions(settings,job,sample):
    stages=[];source,candidate,review=sample
    bad=decision('invalid_check');bad['decisions'][0]['assertion_id']='A404'
    Runner(settings,job[1],adjudication_model([source,candidate,review,bad,bad],stages),MemoryCache,renderer).run()
    assert job[0].get(job[1])['status']=='failed'
    assert stages[-2:]==['adjudicate','adjudicate']


def test_invalid_check_cannot_erase_separate_review_objection(settings,job,sample):
    stages=[];source,candidate,review=sample
    objection=copy.deepcopy(review)
    objection.update(verdict='revise',issues=[{'stage':'math','target':'Q1','detail':'仍有另一处遗漏条件'}])
    Runner(settings,job[1],adjudication_model([source,candidate,objection,{'solutions':candidate['solutions']},review],stages),MemoryCache,renderer).run()
    assert stages==['source','solve','review','math_repair','review','deferred_review']
    assert job[0].get(job[1])['status']=='completed'


def test_explicit_diagram_revision_keeps_math_and_skips_paid_rereading(settings,job,sample):
    from math_agent.revisions import create_diagram_revision
    from test_pipeline import provider
    stages=[]
    Runner(settings,job[1],provider(list(sample),stages),MemoryCache,renderer).run()
    new_id=create_diagram_revision(settings,job[1],[{'stage':'diagram','target':'board','detail':'补齐原生构造'}])
    assert job[0].claim()==new_id
    stages=[]
    Runner(settings,new_id,provider([sample[1],sample[2]],stages),MemoryCache,renderer).run()
    assert stages==['diagram','review']
    assert job[0].get(new_id)['status']=='completed'
    saved=json.loads((job[0].path(new_id)/'candidate.json').read_text())
    assert Candidate.model_validate(saved).solutions==Candidate.model_validate(sample[1]).solutions
    with pytest.raises(ValueError,match='只接受'):
        create_diagram_revision(settings,job[1],[{'stage':'math','target':'Q1','detail':'改变答案'}])


def test_adjudication_cannot_use_another_questions_local_evidence(settings,job,sample):
    stages=[];source,candidate,review=sample
    bad=decision('invalid_check');bad['decisions'][0]['basis_ids']=['Q2:S1']
    Runner(settings,job[1],adjudication_model([source,candidate,review,bad,bad],stages),MemoryCache,renderer).run()
    assert job[0].get(job[1])['status']=='failed'
    assert '不适用于Q1' in job[0].get(job[1])['error']


def test_assertion_index_names_only_the_current_tab_scope_not_goals_or_hypotheses(sample):
    from math_agent.evidence import assertion_basis_index
    source=Source.model_validate(sample[0]);candidate=Candidate.model_validate(sample[1])
    source.conditions[0].question_ids=['Q1']
    ledger=build_ledger(source,candidate)
    record_hypothesis(ledger,'Q1','未验证的猜想',['C1'],'查询')
    index=assertion_basis_index(ledger,candidate.solutions)
    assert index['0']['question_id']=='Q1' and 'C1' in index['0']['available_basis_ids']
    assert 'Q1:S1' in index['0']['available_basis_ids']
    assert 'Q2:S1' in index['1']['available_basis_ids']
    assert not {'Q1','Q2','H1','C1','Q1:S1'} & set(index['1']['available_basis_ids'])
    assert not {'Q1','Q2','H1','Q2:S1'} & set(index['0']['available_basis_ids'])


def test_review_context_receives_exact_current_assertion_index(settings,job,sample):
    from dataclasses import replace
    from test_compact_tools import pack
    from test_compact_review import pack_review
    queue=[sample[0],pack(sample[1]),pack_review(sample[2])];seen=[]
    class Model:
        def __init__(self,*args):self.calls=0
        def close(self):pass
        def generate(self,stage,messages,**kwargs):
            self.calls+=1
            if stage=='review':
                context=json.loads(messages[-1]['content'][0]['text'])['context'];seen.append(context)
                index=context['assertion_basis_index']
                assert index['1']['question_id']=='Q2' and 'Q2:S1' in index['1']['available_basis_ids']
                assert 'Q1:S1' not in index['1']['available_basis_ids']
            return copy.deepcopy(queue.pop(0))
    runner=Runner(replace(settings,compact_tools=True),job[1],Model,MemoryCache,renderer)
    runner.run()
    assert seen and job[0].get(job[1])['status']=='completed'


def test_invalid_basis_hint_exposes_scope_without_erasing_the_failed_target(settings,job,sample):
    from test_pipeline import provider
    source=Source.model_validate(sample[0]);candidate=Candidate.model_validate(sample[1])
    source.conditions[0].question_ids=['Q1']
    runner=Runner(settings,job[1],provider([],[]),MemoryCache,renderer)
    runner.ledger=build_ledger(source,candidate);runner.review_candidate=candidate;runner.scenes.current=candidate.spec
    point=next(o['id'] for o in candidate.spec['tabs'][1]['board']['objects'] if o['kind']=='point')
    result=runner.dispatch_stage_tool('review',runner.request,'inspect_scene',{'probes':[{'tab':1,'checks':[
        {'relation':'equal_length','points':[point]*4,'expected':True,'basis_ids':['Q1:S1'],'rationale':'离线验证错误作用域'}]}]})
    assert not result['ok'] and result['execution_failure']['kind']=='basis_validation'
    assert result['execution_failure']['targets'][0]['expected'] is True
    ids=result['available_assertion_basis']['1']['available_basis_ids']
    assert 'Q2:S1' in ids and 'Q1:S1' not in ids and 'C1' not in ids
