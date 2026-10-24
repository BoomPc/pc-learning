import pytest
from test_math_outline import values
from math_agent.split_outline import append_question,question_context


def test_scoped_question_can_reference_earlier_proof_but_cannot_rewrite_it(sample):
    source,outline,_=values(sample)
    first=outline.questions[0]
    second=outline.questions[1].model_dump()
    second['proof'][0]['basis_ids']=[first.question_id+':O1']
    result=append_question({'questions':[second],'uncertainties':[]},source,[first])
    assert result.questions[0]==first
    with pytest.raises(ValueError):append_question({'questions':[first.model_dump(),second],'uncertainties':[]},source,[first])
    second['proof'][0]['basis_ids']=[second['question_id']+':O1']
    with pytest.raises(ValueError):append_question({'questions':[second],'uncertainties':[]},source,[first])


def test_scope_keeps_other_conditions_visible_without_marking_them_local(sample):
    source,outline,_=values(sample)
    source.conditions[0].question_ids=[source.questions[0].id]
    context=question_context(source,source.questions[1].id,[outline.questions[0]])
    assert source.conditions[0].id in context['condition_scope']['other_questions']
    assert source.conditions[0].id not in context['condition_scope']['local']
    assert context['source']==source.model_dump()
    assert context['previous_outlines']==[outline.questions[0].model_dump()]


def test_full_split_does_not_expand_when_later_question_is_unresolved(sample,tmp_path,monkeypatch):
    from types import SimpleNamespace
    from math_agent.pipeline import Runner,NeedsInput
    from math_agent.split_outline import SplitOutlineRunner
    source,outline,_=values(sample)
    runner=object.__new__(SplitOutlineRunner)
    runner.provider=SimpleNamespace(calls=0);runner.directory=tmp_path
    runner.records=[];runner.request={'images':[]}
    calls=[]
    def fake(self,stage,payload,validate,request_override=None):
        calls.append((stage,payload['target_question']))
        index=len(calls)-1;self.provider.calls+=1
        return validate({'questions':[outline.questions[index].model_dump()],
            'uncertainties':['unproved position'] if index==1 else []})
    monkeypatch.setattr(Runner,'validated',fake)
    with pytest.raises(NeedsInput):runner.validated('reference_math',{'source':source.model_dump()},lambda raw:raw)
    assert calls==[('reference_math',source.questions[0].id),('reference_math',source.questions[1].id)]
    assert not list(tmp_path.glob('math-expansion*'))
