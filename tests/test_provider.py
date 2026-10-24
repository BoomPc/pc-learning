import json
import httpx
import pytest
from math_agent.provider import DeepSeek, ModelError


def response(message, finish="stop"):
    return {"choices": [{"message": message, "finish_reason": finish}], "usage": {"total_tokens": 10}}


def test_thinking_tool_history_roundtrip(settings):
    requests = []
    def handler(request):
        body = json.loads(request.content); requests.append(body)
        if len(requests) == 1:
            return httpx.Response(200, json=response({"role": "assistant", "content": None, "reasoning_content": "private reasoning",
                "tool_calls": [{"id": "call1", "type": "function", "function": {"name": "calculate", "arguments": "{}"}}]}, "tool_calls"))
        assert body["messages"][-2]["reasoning_content"] == "private reasoning"
        assert body["messages"][-1]["tool_call_id"] == "call1"
        return httpx.Response(200, json=response({"role": "assistant", "content": '{"result": 2}'}))
    audit = []
    client = DeepSeek(settings, lambda *x: audit.append(x), httpx.MockTransport(handler))
    try:
        assert client.generate("solve", [{"role": "user", "content": "json"}], tools=[{"function":{"name":"calculate"}}], dispatch=lambda *args: {"ok": True}) == {"result": 2}
        assert len(requests) == 2
        assert "private reasoning" not in str(audit)
    finally: client.close()


def test_explicit_experiment_thinking_override_keeps_stage_and_budget(settings):
    requests=[]; audit=[]
    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200,json=response({'role':'assistant','content':'{}'}))
    client=DeepSeek(settings,lambda kind,data:audit.append(data),httpx.MockTransport(handler))
    try:
        client.request('reference_math',[],thinking_override=True)
        client.request('reference_math',[])
        assert requests[0]['thinking']=={'type':'enabled'}
        assert requests[1]['thinking']=={'type':'disabled'}
        assert requests[0]['max_tokens']==requests[1]['max_tokens']==settings.max_tokens
        audit=[entry for entry in audit if 'thinking' in entry]
        assert audit[0]['stage']==audit[1]['stage']=='reference_math'
        assert audit[0]['thinking'] and not audit[1]['thinking']
    finally:client.close()


@pytest.mark.parametrize("code,finish,content", [(401, "stop", "{}"), (429, "stop", "{}"), (200, "length", '{"x":'), (200, "stop", ""), (200, "stop", "not json")])
def test_invalid_response_does_not_retry_or_succeed(settings, code, finish, content):
    calls = []
    def handler(request):
        calls.append(1)
        return httpx.Response(code, json=response({"role": "assistant", "content": content}, finish))
    client = DeepSeek(settings, lambda *args: None, httpx.MockTransport(handler))
    try:
        with pytest.raises(ModelError): client.generate("source", [{"role": "user", "content": "json"}])
        assert len(calls) == 1
    finally: client.close()


def test_undeclared_tool_never_reaches_dispatch(settings):
    invoked=[]
    def handler(request):
        return httpx.Response(200,json=response({"role":"assistant","content":None,"tool_calls":[{"id":"bad","function":{"name":"shell","arguments":"{}"}}]},"tool_calls"))
    client=DeepSeek(settings,lambda *args:None,httpx.MockTransport(handler))
    try:
        with pytest.raises(ModelError,match="未授权"):
            client.generate("solve",[],tools=[{"function":{"name":"calculate"}}],dispatch=lambda *args:invoked.append(args))
        assert not invoked
    finally:client.close()


def test_last_turn_reserves_output_without_executing_more_tools(settings):
    requests, executed = [], []
    def handler(request):
        body = json.loads(request.content); requests.append(body)
        if len(requests) < 4:
            return httpx.Response(200, json=response({"role":"assistant", "content":None,
                "reasoning_content":"prior analysis "+str(len(requests)),
                "tool_calls":[{"id":str(len(requests)),"function":{"name":"calculate","arguments":"{}"}}]}, "tool_calls"))
        assert body["tools"] and body["tool_choice"]=="none"
        assert "最后一轮" in body["messages"][-1]["content"]
        assert any('failed evidence' in str(m) for m in body["messages"])
        assert [m["reasoning_content"] for m in body["messages"] if "reasoning_content" in m]==["prior analysis 1","prior analysis 2","prior analysis 3"]
        return httpx.Response(200, json=response({"role":"assistant","content":'{"unresolved":true}'}))
    client = DeepSeek(settings, lambda *args: None, httpx.MockTransport(handler))
    def dispatch(*args):
        executed.append(args)
        return {"ok":False,"error":"failed evidence"}
    try:
        assert client.generate("solve",[],tools=[{"function":{"name":"calculate"}}],dispatch=dispatch) == {"unresolved":True}
        assert len(requests) == 4 and len(executed) == 3
    finally:
        client.close()


@pytest.mark.parametrize('ignores_finalization',[False,True])
def test_job_last_call_is_output_only_even_before_stage_last_turn(settings,ignores_finalization):
    from dataclasses import replace
    requests=[];executed=[]
    def handler(request):
        body=json.loads(request.content);requests.append(body)
        assert body['tools'] and body['tool_choice']=='none'
        assert '最后一轮' in body['messages'][-1]['content']
        if ignores_finalization:
            return httpx.Response(200,json=response({'role':'assistant','content':None,
                'tool_calls':[{'id':'x','function':{'name':'calculate','arguments':'{}'}}]},'tool_calls'))
        return httpx.Response(200,json=response({'role':'assistant','content':'{"unresolved":true}'}))
    client=DeepSeek(replace(settings,max_calls=1),lambda *x:None,httpx.MockTransport(handler))
    try:
        if ignores_finalization:
            with pytest.raises(ModelError,match='最终输出轮'):
                client.generate('graph_review',[],tools=[{'function':{'name':'calculate'}}],dispatch=lambda *x:executed.append(x))
        else:
            assert client.generate('graph_review',[],tools=[{'function':{'name':'calculate'}}],dispatch=lambda *x:executed.append(x))=={'unresolved':True}
        assert len(requests)==1 and not executed
    finally:client.close()


def test_source_reread_can_reason_while_first_transcription_remains_fast(settings):
    requests=[]
    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200,json=response({'role':'assistant','content':'{}'}))
    client=DeepSeek(settings,lambda *x:None,httpx.MockTransport(handler))
    try:
        client.request('source',[]);client.request('source_review',[])
        assert requests[0]['thinking']['type']=='disabled'
        assert requests[1]['thinking']['type']=='enabled'
        assert requests[0]['max_tokens']==settings.source_max_tokens
        assert requests[1]['max_tokens']==settings.max_tokens
    finally:client.close()


def test_review_preparation_is_fast_but_final_review_retains_reasoning(settings):
    requests=[]
    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200,json=response({'role':'assistant','content':'{}'}))
    client=DeepSeek(settings,lambda *x:None,httpx.MockTransport(handler))
    try:
        client.request('review_plan',[]);client.request('review',[])
        assert [x['thinking']['type'] for x in requests]==['disabled','enabled']
    finally:client.close()


@pytest.mark.parametrize('remaining',[1,2])
def test_fast_solve_draft_cannot_escape_reasoned_verification(settings,remaining):
    from dataclasses import replace
    requests=[]
    def handler(request):
        body=json.loads(request.content);requests.append(body)
        if remaining==2 and len(requests)==1:
            assert body['thinking']['type']=='disabled'
            return httpx.Response(200,json=response({'role':'assistant','content':'{"unverified":true}'}))
        assert body['thinking']['type']=='enabled'
        if remaining==2:assert '尚未核验的快速草稿' in str(body['messages'])
        return httpx.Response(200,json=response({'role':'assistant','content':'{"verified":true}'}))
    client=DeepSeek(replace(settings,solve_draft=True,max_calls=remaining),lambda *x:None,httpx.MockTransport(handler))
    try:
        assert client.generate('solve',[])=={'verified':True}
        assert len(requests)==remaining
    finally:client.close()


def test_fast_solve_tool_plan_is_followed_by_thinking_not_returned_as_solution(settings):
    from dataclasses import replace
    requests=[];executed=[]
    def handler(request):
        body=json.loads(request.content);requests.append(body)
        if len(requests)==1:
            assert body['thinking']['type']=='disabled'
            return httpx.Response(200,json=response({'role':'assistant','content':None,
                'tool_calls':[{'id':'c','function':{'name':'calculate','arguments':'{}'}}]},'tool_calls'))
        assert body['thinking']['type']=='enabled'
        assert 'actual observation' in str(body['messages'])
        return httpx.Response(200,json=response({'role':'assistant','content':'{"verified":true}'}))
    client=DeepSeek(replace(settings,solve_draft=True,max_calls=2),lambda *x:None,httpx.MockTransport(handler))
    def dispatch(*args):executed.append(args);return {'value':'actual observation'}
    try:
        assert client.generate('solve',[],tools=[{'function':{'name':'calculate'}}],dispatch=dispatch)=={'verified':True}
        assert len(executed)==1 and len(requests)==2
    finally:client.close()


def test_invalid_json_keeps_sanitized_answer_not_reasoning_and_never_retries(settings):
    from dataclasses import replace
    configured=replace(settings,api_key='private-api-secret',access_token='private-user-token')
    calls=[];audit=[]
    def handler(request):
        calls.append(1)
        return httpx.Response(200,json=response({'role':'assistant','content':'{"bad": "\\sqrt private-api-secret private-user-token"}', 'reasoning_content':'hidden chain'}))
    client=DeepSeek(configured,lambda kind,data:audit.append((kind,data)),httpx.MockTransport(handler))
    try:
        with pytest.raises(ModelError):client.generate('reference_math',[])
        records=[v for k,v in audit if k=='model_output_error']
        assert len(calls)==len(records)==1
        assert records[0]['position'] is not None and '\\sqrt' in records[0]['content']
        assert '[REDACTED]' in records[0]['content']
        assert not any(secret in str(audit) for secret in ['private-api-secret','private-user-token','hidden chain'])
    finally:client.close()


def test_explicit_json_mode_experiment_does_not_change_tool_protocol(settings):
    requests=[]
    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200,json=response({'role':'assistant','content':'{}'}))
    client=DeepSeek(settings,lambda *args:None,httpx.MockTransport(handler))
    tools=[{'type':'function','function':{'name':'algebra_batch'}}]
    try:
        client.request('reference_math',[],tools,json_mode=False,thinking_override=False)
        client.request('reference_math',[],tools,json_mode=True,thinking_override=False)
        assert 'response_format' not in requests[0]
        assert requests[1]['response_format']=={'type':'json_object'}
        assert requests[0]['tools']==requests[1]['tools']==tools
        assert requests[0]['max_tokens']==requests[1]['max_tokens']
    finally:client.close()
