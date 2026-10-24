from types import SimpleNamespace
import pytest
from math_agent.pipeline import Runner, NeedsInput
from math_agent.outline_agent import OutlineRunner
from test_math_outline import values


def make(tmp_path):
    runner=object.__new__(OutlineRunner)
    runner.provider=SimpleNamespace(calls=2)
    runner.directory=tmp_path
    runner.request={'images':[{'id':'answer','role':'answer'}],'text':''}
    runner.records=[{'kind':'tool','result':{'ok':False,'error':'bad coordinate'}},{'kind':'model'}]
    return runner


def test_outline_repair_preserves_feedback_and_calls_final_math_validation(sample,tmp_path,monkeypatch):
    source,outline,expanded=values(sample);runner=make(tmp_path);calls=[]
    def fake(self,stage,payload,validate,request_override=None):
        calls.append((stage,payload,request_override))
        return validate(outline.model_dump() if stage=='reference_math' else expanded)
    monkeypatch.setattr(Runner,'validated',fake)
    feedback=[{'stage':'math','detail':'previous proof is invalid'}]
    checked=[]
    result=runner.validated('reference_math',{'source':source.model_dump(),'feedback':feedback},lambda raw:checked.append(raw) or raw)
    assert calls[0][1]['feedback']==feedback
    assert calls[0][2] is None  # Original question + answer pixels remain available.
    assert calls[1][2]['images']==[]
    assert checked==[result] and 'solutions' in result
    assert (tmp_path/'math-outline-2.json').exists()
    assert (tmp_path/'math-expansion-2.json').exists()


def test_unresolved_outline_stops_before_expansion(sample,tmp_path,monkeypatch):
    source,outline,_=values(sample);outline.uncertainties=['cannot justify this step']
    runner=make(tmp_path);calls=[]
    def fake(self,stage,payload,validate,request_override=None):
        calls.append(stage);return validate(outline.model_dump())
    monkeypatch.setattr(Runner,'validated',fake)
    with pytest.raises(NeedsInput):runner.validated('reference_math',{'source':source.model_dump()},lambda raw:raw)
    assert calls==['reference_math']
    assert not (tmp_path/'math-expansion-2.json').exists()


def test_review_keeps_failed_tool_evidence_and_original_payload(tmp_path,monkeypatch):
    runner=make(tmp_path)
    monkeypatch.setattr(Runner,'validated',lambda self,stage,payload,validate,request_override=None:payload)
    payload=runner.validated('math_review',{'math':{'solutions':[]},'proof_dependencies':['unresolved']},lambda raw:raw)
    assert payload['proof_dependencies']==['unresolved']
    assert payload['tool_evidence']==runner.records[:1]
