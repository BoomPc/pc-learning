import json
from dataclasses import replace
import httpx
import pytest
from math_agent.provider import DeepSeek
from math_agent.parallel_budget import ParallelBudget
from math_agent.cache import key_for


@pytest.mark.parametrize('native',[False,True])
def test_only_review_and_decision_stages_use_the_explicit_stronger_effort(settings,native):
    seen=[];audit=[]
    def handler(request):
        sent=json.loads(request.content);seen.append(sent)
        usage={'input_tokens':10,'output_tokens':20}
        if request.url.path.endswith('/responses'):
            return httpx.Response(200,json={'status':'completed','output':[{'type':'message',
                'content':[{'type':'output_text','text':'{"ok":true}'}]}],'usage':usage})
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'role':'assistant','content':'{"ok":true}'}}],
            'usage':{'prompt_tokens':10,'completion_tokens':20}})
    cfg=replace(settings,effort='low',review_effort='high',compact_tools=True,solve_responses=native,review_responses=native)
    provider=DeepSeek(cfg,lambda k,v:audit.append((k,v)),httpx.MockTransport(handler))
    try:
        for stage in ['solve','review','solve']:
            kwargs={'output_schema':{'type':'object','properties':{'ok':{'type':'boolean'}}}} if native else {}
            assert provider.generate(stage,[{'role':'user','content':'offline json protocol test'}],**kwargs)=={'ok':True}
        actual=[s['reasoning']['effort'] if native else s['reasoning_effort'] for s in seen]
        assert actual==['low','high','low']
        assert [v['reasoning_effort'] for k,v in audit if k=='model']==actual
        assert provider.effort_for_stage('source')=='low' and provider.effort_for_stage('diagram')=='low'
        assert provider.effort_for_stage('adjudicate')=='high'
        assert provider.settings.effort=='low'
    finally:provider.close()


def test_review_effort_has_distinct_cache_and_only_supported_values(settings):
    request={'text':'offline','images':[]}
    assert key_for(settings,request)!=key_for(replace(settings,review_effort='high'),request)
    with pytest.raises(ValueError):replace(settings,review_effort='medium')
    with pytest.raises(ValueError):replace(settings,api_style='glm',review_effort='high')


def test_shared_deadline_requests_final_json_even_when_stage_reservation_is_disabled(settings):
    seen=[];audit=[]
    def handler(request):
        sent=json.loads(request.content);seen.append(sent)
        assert sent['tool_choice']=='none' and sent['tools'][0]['name']=='query'
        return httpx.Response(200,json={'status':'completed','output':[{'type':'message',
            'content':[{'type':'output_text','text':'{"ok":false}'}]}],'usage':{'input_tokens':10,'output_tokens':20}})
    cfg=replace(settings,compact_tools=True,review_responses=True,max_calls=16,review_reserve_seconds=0)
    provider=DeepSeek(cfg,lambda k,v:audit.append((k,v)),httpx.MockTransport(handler));provider.shared_budget=ParallelBudget(16,timeout_seconds=40)
    try:
        value=provider.generate('review',[{'role':'user','content':'offline json'}],
            tools=[{'type':'function','function':{'name':'query','parameters':{'type':'object'}}}],
            dispatch=lambda *_:pytest.fail('deadline output-only call cannot execute tools'),
            output_schema={'type':'object','properties':{'ok':{'type':'boolean'}}})
        assert value=={'ok':False} and len(seen)==1 and any(k=='agent_finalize' for k,v in audit)
        assert provider.shared_budget.remaining_calls==15
    finally:provider.close()
