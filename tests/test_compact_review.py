import copy
import pytest
from math_agent.contracts import Source,Review
from math_agent.compact_review import output_schema,unpack
from math_agent.pipeline import Runner
from test_pipeline import MemoryCache,renderer

def pack_review(raw):
    return {**raw,'conditions':{c['id']:{k:v for k,v in c.items() if k!='id'} for c in raw['conditions']},
        'questions':{q['id']:{k:v for k,v in q.items() if k!='id'} for q in raw['questions']}}

def test_review_keys_are_exact_and_restore_original_order(sample):
    source=Source.model_validate(sample[0]);raw=pack_review(sample[2])
    raw['questions']=dict(reversed(list(raw['questions'].items())))
    assert unpack(raw,source)==Review.model_validate(sample[2])
    schema=output_schema(sample[0]);assert schema['properties']['conditions']['required']==['C1']
    assert not schema['properties']['conditions']['additionalProperties']
    raw['conditions']['C13']=raw['conditions']['C1']
    with pytest.raises(ValueError):unpack(raw,source)


def test_output_correction_receives_evidence_obtained_in_failed_attempt(settings,job):
    runner=Runner(settings,job[1],cache_factory=MemoryCache,renderer=renderer)
    calls=[]
    def ask(stage,payload,request_override=None):
        calls.append(copy.deepcopy(payload))
        if len(calls)==1:
            runner.audit('tool',{'stage':'review','name':'algebra_batch','arguments':'{}',
                'result':{'ok':True,'exact':'28'}})
            return {'valid':False}
        return {'valid':True}
    def validate(raw):
        if not raw['valid']:raise ValueError('extra C13')
        return raw
    runner.ask=ask
    try:
        assert runner.validated('review',{'tool_evidence':[]},validate)['valid']
        assert calls[1]['tool_evidence'][0]['result']['exact']=='28'
        assert '不为格式纠正重复解题' in calls[1]['structured_output_correction']['instruction']
    finally:runner.provider.close()


def test_extra_review_id_correction_has_no_tool_roundtrip(settings,job,sample):
    from dataclasses import replace
    from test_compact_tools import pack
    import json
    seen=[]
    class Provider:
        def __init__(self,settings,audit):self.calls=0;self.audit=audit;self.review_calls=0
        def close(self):pass
        def generate(self,stage,messages,tools=None,dispatch=None):
            self.calls+=1
            if stage=='source':return sample[0]
            if stage=='solve':return pack(sample[1])
            self.review_calls+=1;seen.append(len(tools or []))
            raw=pack_review(sample[2])
            if self.review_calls==1:
                self.audit('tool',{'stage':'review','name':'algebra_batch','arguments':'{}','result':{'ok':True,'exact':'28'}})
                raw['conditions']['C13']=copy.deepcopy(raw['conditions']['C1'])
            else:
                assert not tools
                context=json.loads(messages[-1]['content'][0]['text'])['context']
                assert context['tool_evidence'][-1]['result']['exact']=='28'
            return raw
    runner=Runner(replace(settings,compact_tools=True),job[1],Provider,MemoryCache,renderer)
    runner.run()
    assert job[0].get(job[1])['status']=='completed'
    assert seen[0]>0 and seen[1]==0
    assert any(r['kind']=='format_only_correction' for r in runner.records)


def test_review_encoding_recovery_is_lossless_and_retains_unknowns(sample):
    import json
    from math_agent.compact_review import repair_encoding
    raw=pack_review(sample[2]);raw['conditions']['C1']['verdict']='unknown';raw['verdict']='needs_input'
    raw['issues']=[{'stage':'source','target':'原题','detail':'不得丢失的疑问和负号 −2、撇号B′、x²'}]
    encoded=json.dumps(raw,ensure_ascii=False)
    # Actual observed failure: a keyed object was emitted with member-object wrappers.
    malformed=encoded.replace('"conditions": {"C1":','"conditions": {{"C1":')
    recovered=repair_encoding(malformed)
    assert recovered==raw and recovered['issues']==raw['issues']
    assert recovered['conditions']['C1']['verdict']=='unknown'


def test_encoding_recovery_does_not_drop_duplicate_or_unknown_data(sample):
    import json
    from math_agent.compact_review import repair_encoding
    encoded=json.dumps(pack_review(sample[2]),ensure_ascii=False)
    duplicate=encoded.replace('"conditions": {','"conditions": {"C1":{"verdict":"issue","evidence":"must retain"},')
    assert repair_encoding(duplicate) is None
    assert repair_encoding(encoded[:-5]) is None
    assert repair_encoding(encoded[:-1]+',"hidden_issue":"must retain"}') is None
    assert repair_encoding(encoded.replace('"evidence":','"evidence":"first","evidence":',1)) is None


def test_observed_member_encoding_can_be_recovered_without_extra_paid_call(settings,sample):
    import json,httpx
    from dataclasses import replace
    from math_agent.provider import DeepSeek
    from test_provider import response
    from math_agent.compact_review import repair_encoding
    raw=pack_review(sample[2]);items=raw['questions']
    malformed=json.dumps(raw,ensure_ascii=False).replace('"questions": {','"questions": {{').replace('"Q2":','{"Q2":')
    # Brace wrappers alone change; literal content remains identical.
    assert repair_encoding(malformed)==raw
    sent=[];audit=[]
    def handler(req):
        sent.append(req)
        return httpx.Response(200,json=response({'role':'assistant','content':malformed}))
    client=DeepSeek(replace(settings,compact_tools=True),lambda k,d:audit.append((k,d)),httpx.MockTransport(handler))
    try:assert client.generate('review',[])==raw
    finally:client.close()
    assert len(sent)==1 and any(k=='json_encoding_repair' for k,d in audit)


def test_real_failed_review_response_keeps_every_record_and_passes_contract():
    from pathlib import Path
    from math_agent.compact_review import repair_encoding
    from math_agent.contracts import check_review
    fixture=Path(__file__).parent/'fixtures/review-encoding'
    repaired=repair_encoding((fixture/'malformed.txt').read_text())
    source=Source.model_validate_json((fixture/'source.json').read_text())
    actual=unpack(repaired,source)
    assert actual==Review.model_validate_json((fixture/'expected-review.json').read_text())
    check_review(actual,source)
