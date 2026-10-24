import copy
import pytest
from math_agent.contracts import Source,Candidate
from scripts.evaluate_review_once import prepare_context


def test_diagnostic_retains_all_original_context_but_only_grades_explicit_questions(sample):
    source=Source.model_validate(sample[0]);candidate=Candidate.model_validate(sample[1])
    before=(copy.deepcopy(source.model_dump()),copy.deepcopy(candidate.model_dump()))
    expected,context=prepare_context(source,candidate,['Q2'])
    assert [q.id for q in expected.questions]==['Q2'] and expected.conditions==source.conditions
    assert context['source']==before[0] and context['diagnostic_question_ids']==['Q2']
    assert [s['question_id'] for s in context['candidate']['solutions']]==['Q1','Q2']
    assert (source.model_dump(),candidate.model_dump())==before
    assert context['candidate']['solutions'][1]==candidate.solutions[1].model_dump()
    assert '不是整题' in context['diagnostic_scope']


@pytest.mark.parametrize('ids',[[],['Q9'],['Q1','Q1']])
def test_diagnostic_cannot_silently_guess_or_omit_requested_question_ids(sample,ids):
    with pytest.raises(ValueError):prepare_context(Source.model_validate(sample[0]),Candidate.model_validate(sample[1]),ids)
