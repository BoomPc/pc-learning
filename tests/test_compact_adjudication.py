import copy
import pytest
from math_agent.contracts import Review,Source
from math_agent.compact_adjudication import unpack
from math_agent.objection_review import validate_resolution
from test_objection_gate import resolution


def test_compact_decisions_preserve_other_questions_and_conditions(sample):
    original=copy.deepcopy(sample[2]);original.update(verdict='revise',issues=[{'stage':'diagram','target':'Q1','detail':'疑问'}])
    data=resolution(original,sample[1],True,sample[2])
    compact={'verdict':'pass','decisions':data['decisions'],'question_updates':[]}
    result=unpack(compact,Review.model_validate(original))
    validate_resolution(result,Review.model_validate(original),Source.model_validate(sample[0]))
    assert result.reviewed==Review.model_validate(sample[2])
    assert original['issues']


def test_compact_cannot_erase_math_issue_or_unknown(sample):
    original=copy.deepcopy(sample[2]);original.update(verdict='revise',issues=[{'stage':'diagram','target':'Q1','detail':'疑问'}, {'stage':'math','target':'Q2','detail':'不能删除'}])
    data=resolution(original,sample[1],True,sample[2]);raw={'verdict':'pass','decisions':data['decisions'],'question_updates':[]}
    result=unpack(raw,Review.model_validate(original));assert result.reviewed.issues[0].stage=='math'
    with pytest.raises(ValueError):validate_resolution(result,Review.model_validate(original),Source.model_validate(sample[0]))
    original['issues']=original['issues'][:1];original['questions'][0]['verdict']='unknown';original['verdict']='needs_input'
    raw['question_updates']=[{'id':'Q1','verdict':'pass','evidence':'试图覆盖未知'}]
    result=unpack(raw,Review.model_validate(original))
    with pytest.raises(ValueError):validate_resolution(result,Review.model_validate(original),Source.model_validate(sample[0]))
