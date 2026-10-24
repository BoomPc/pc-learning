import json
from dataclasses import replace
import pytest
from math_agent.contracts import Source,Candidate,ReviewPreparation
from math_agent.pipeline import Runner,canonical_page
from math_agent.cache import key_for
from test_pipeline import MemoryCache,renderer


@pytest.mark.parametrize('tool_error',[False,True])
def test_preparation_is_evidence_not_a_verdict_and_errors_remain_blocking(settings,job,sample,tool_error):
    stages=[]
    class Model:
        def __init__(self,settings,audit):self.audit=audit;self.calls=0
        def close(self):pass
        def generate(self,stage,messages,**kwargs):
            stages.append(stage);self.calls+=1
            if stage=='review_plan':
                if tool_error:self.audit('tool',{'stage':stage,'name':'inspect_scene','result':{'ok':False,'error':'unknown browser failure'}})
                return {'covered_questions':['Q1','Q2'],'probes':[],'algebra_operations':[]}
            assert stage=='review'
            context=json.loads(messages[-1]['content'][0]['text'])['context']
            assert context['preparation']['covered_questions']==['Q1','Q2']
            if tool_error:assert any(x['name']=='inspect_scene' for x in context['tool_evidence'])
            return sample[2]
    runner=Runner(replace(settings,review_plan=True),job[1],Model,MemoryCache,renderer)
    source=Source.model_validate(sample[0]);candidate=canonical_page(Candidate.model_validate(sample[1]),source)
    if tool_error:
        with pytest.raises(ValueError,match='尚未|未有效'):runner.review(source,candidate,{})
        assert stages==['review_plan','review','review']
    else:
        assert runner.review(source,candidate,{}).verdict=='pass'
        assert stages==['review_plan','review']
    with pytest.raises(ValueError):ReviewPreparation.model_validate({'covered_questions':['Q1','Q2'],'probes':[],'algebra_operations':[],'verdict':'pass'})


def test_planning_mode_has_distinct_model_cache(settings):
    request={'text':'same question','images':[]}
    assert key_for(settings,request)!=key_for(replace(settings,review_plan=not settings.review_plan),request)


def test_plan_executes_real_commands_before_final_review(settings,job,sample):
    results=[]
    class Model:
        def __init__(self,settings,audit):self.calls=0
        def close(self):pass
        def generate(self,stage,messages,tools,**kwargs):
            self.calls+=1
            if stage=='review_plan':
                assert tools==[]
                return {'covered_questions':['Q1','Q2'],'probes':[],
                    'algebra_operations':[{'op':'simplify','expression':'2+3','variables':[]}]}
            ctx=json.loads(messages[-1]['content'][0]['text'])['context']
            evidence=next(x for x in ctx['tool_evidence'] if x['name']=='algebra_batch')
            assert evidence['result']['results'][0]['exact']=='5'
            results.append(evidence)
            return sample[2]
    runner=Runner(replace(settings,review_plan=True),job[1],Model,MemoryCache,renderer)
    source=Source.model_validate(sample[0]);candidate=canonical_page(Candidate.model_validate(sample[1]),source)
    assert runner.review(source,candidate,{}).verdict=='pass'
    assert len(results)==1
