from dataclasses import replace
import json
import httpx
import pytest
from math_agent.provider import DeepSeek, ModelError
from test_provider import response


def test_stage_caps_preserve_high_and_reserve(settings):
    now=[100.0]; seen=[]; records=[]
    configured=replace(settings,solve_max_tokens=16000,review_max_tokens=12000,review_reserve_seconds=80)
    def handler(req):
        seen.append((json.loads(req.content),req.extensions['timeout']))
        return httpx.Response(200,json=response({'role':'assistant','content':'{}'}))
    client=DeepSeek(configured,lambda k,d:records.append((k,d)),httpx.MockTransport(handler))
    client.started=__import__('time').monotonic()-100
    try:
        client.generate('solve',[],tools=[{'function':{'name':'calculate'}}])
        assert seen[0][0]['max_tokens']==16000 and seen[0][0]['reasoning_effort']=='high'
        assert seen[0][0]['tool_choice']=='none'
        assert 50 < seen[0][1]['read'] <=55
        client.generate('review',[])
        assert seen[1][0]['max_tokens']==12000 and seen[1][0]['reasoning_effort']=='high'
        assert 135 < seen[1][1]['read'] <=140
        assert any(k=='agent_finalize' and d['reason']=='stage_time' for k,d in records)
    finally:client.close()


def test_exhausted_preparation_does_not_send_or_retry(settings):
    sent=[]
    client=DeepSeek(replace(settings,review_reserve_seconds=80),lambda *a:None,
        httpx.MockTransport(lambda req:sent.append(req)))
    client.started=__import__('time').monotonic()-160
    try:
        with pytest.raises(ModelError,match='预算'):client.generate('solve',[])
        assert not sent and client.calls==0
    finally:client.close()


def test_stage_truncation_is_failure_not_continuation(settings):
    sent=[]
    def handler(req):
        sent.append(req)
        return httpx.Response(200,json=response({'role':'assistant','content':'{"Q1":'},'length'))
    client=DeepSeek(replace(settings,solve_max_tokens=16000,review_reserve_seconds=80),lambda *a:None,httpx.MockTransport(handler))
    try:
        with pytest.raises(ModelError,match='截断'):client.generate('solve',[])
        assert len(sent)==1
    finally:client.close()


def test_timeout_has_no_retry(settings):
    sent=[]
    def handler(req):
        sent.append(req);raise httpx.ReadTimeout('test',request=req)
    client=DeepSeek(replace(settings,review_reserve_seconds=80),lambda *a:None,httpx.MockTransport(handler))
    try:
        with pytest.raises(ModelError,match='时间预算'):client.generate('solve',[])
        assert len(sent)==1
    finally:client.close()
