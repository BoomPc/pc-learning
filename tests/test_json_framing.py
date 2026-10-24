import json
from pathlib import Path
from dataclasses import replace
import httpx
import pytest
from math_agent.json_framing import close_completed_containers
from math_agent.provider import DeepSeek,ModelError


RAW=(Path(__file__).parent/'fixtures/review-encoding/solve-missing-root-close.txt').read_text()


def test_actual_completed_solver_only_needs_one_outer_close_and_no_data_changes():
    repaired=close_completed_containers(RAW)
    assert repaired==RAW+'}' and repaired.startswith(RAW)
    value=json.loads(repaired)
    assert set(value)=={'Q5'} and set(value['Q5'])=={'proof','board'}
    assert 'w≥-19/2' in value['Q5']['proof']['result']


@pytest.mark.parametrize('raw',['{}','[{}','{"x":','{"x":1','{"x":{} ,',
    '{"x":{} "y":{}}','{"x":"unterminated }','{"x":[1,2}',
    '{"x":{},"x":{}','{"x":{},"y":null','not json {}'])
def test_never_repair_values_strings_duplicates_or_inner_grammar(raw):
    assert close_completed_containers(raw) is None


def test_quotes_escapes_and_math_braces_do_not_change_container_balance():
    value={'outer':{'text':'x² + {a,b} and [x,y] with "quotes" and \\ literal', 'n':-1.25e-4}}
    encoded=json.dumps(value,ensure_ascii=False)
    missing=encoded[:-1]
    assert close_completed_containers(missing)==encoded
    assert json.loads(close_completed_containers(missing))==value


@pytest.mark.parametrize('native',[False,True])
def test_actual_solve_response_finishes_locally_once_and_still_validates_full_schema(settings,native):
    from math_agent.compact_output import output_schema
    schema=output_schema({'questions':[{'id':'Q5','text':'full question'}],
        'conditions':[{'id':c,'text':c} for c in ['C1','C11','C12','C13']]},require_basis=True)
    seen=[];audit=[]
    def handler(request):
        seen.append(request)
        if native:return httpx.Response(200,json={'status':'completed','output':[{'type':'message',
            'content':[{'type':'output_text','text':RAW}]}],'usage':{'input_tokens':10,'output_tokens':20}})
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'role':'assistant','content':RAW}}],
            'usage':{'prompt_tokens':10,'completion_tokens':20}})
    cfg=replace(settings,compact_tools=True,solve_responses=native)
    provider=DeepSeek(cfg,lambda k,v:audit.append((k,v)),httpx.MockTransport(handler))
    try:
        value=provider.generate('solve',[],**({'output_schema':schema} if native else {}))
        assert value==json.loads(RAW+'}') and len(seen)==provider.calls==1
        record=next(v for k,v in audit if k=='json_container_closure')
        assert record['suffix']=='}' and record['transport']==('responses' if native else 'chat')
    finally:provider.close()


@pytest.mark.parametrize('native',[False,True])
def test_truncated_transport_status_never_enters_framing_recovery(settings,native):
    audit=[];seen=[]
    def handler(request):
        seen.append(request)
        if native:return httpx.Response(200,json={'status':'incomplete','output':[{'type':'message',
            'content':[{'type':'output_text','text':RAW}]}]})
        return httpx.Response(200,json={'choices':[{'finish_reason':'length','message':{'role':'assistant','content':RAW}}]})
    provider=DeepSeek(replace(settings,compact_tools=True,solve_responses=native),lambda k,v:audit.append((k,v)),httpx.MockTransport(handler))
    try:
        with pytest.raises(ModelError):provider.generate('solve',[],**({'output_schema':{'type':'object'}} if native else {}))
        assert len(seen)==1 and not any(k=='json_container_closure' for k,_ in audit)
    finally:provider.close()
