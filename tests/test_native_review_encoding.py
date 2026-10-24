"""Actual completed Responses member-wrapper error; never a paid replay."""
import json
from dataclasses import replace
from pathlib import Path
import httpx
import pytest
from math_agent.compact_review import output_schema
from math_agent.provider import DeepSeek,ModelError


@pytest.mark.parametrize('case',['completed','incomplete','truncated','duplicate'])
def test_actual_native_review_brackets_keep_every_scalar_and_objection(settings,case):
    raw=(Path(__file__).parent/'fixtures/review-encoding/native-missing-question-close.txt').read_text()
    expected=json.loads(raw.replace('},"issues":[','}},"issues":[',1))
    schema=output_schema({name:[{'id':key,'text':key} for key in expected[name]] for name in ['conditions','questions']})
    if case=='truncated':raw=raw[:raw.index('"questions"')+20]
    if case=='duplicate':raw=raw.replace('"verdict":"revise"','"verdict":"needs_input","verdict":"revise"',1)
    seen=[];audit=[]
    def handler(request):
        seen.append(request)
        return httpx.Response(200,json={'status':'incomplete' if case=='incomplete' else 'completed',
            'output':[{'type':'message','content':[{'type':'output_text','text':raw}]}],
            'usage':{'input_tokens':10,'output_tokens':20}})
    provider=DeepSeek(replace(settings,compact_tools=True,review_responses=True),lambda k,v:audit.append((k,v)),httpx.MockTransport(handler))
    try:
        if case=='completed':
            actual=provider.generate('review',[],output_schema=schema)
            assert actual==expected and actual['verdict']=='revise'
            assert actual['issues']==expected['issues'] and 't=4时n=c' in actual['issues'][0]['detail']
            assert any(k=='json_encoding_repair' and v['transport']=='responses' for k,v in audit)
        else:
            with pytest.raises(ModelError):provider.generate('review',[],output_schema=schema)
            assert not any(k=='json_encoding_repair' for k,_ in audit)
        assert len(seen)==1 and provider.calls==1
    finally:provider.close()
