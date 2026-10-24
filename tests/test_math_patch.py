import copy
import pytest
from math_agent.contracts import Source,Candidate,check_candidate
from math_agent.math_patch import apply,output_schema
from math_agent.pipeline import canonical_page


def test_only_submitted_question_changes_and_geometry_is_preserved(sample):
    src=Source.model_validate(sample[0]);old=canonical_page(Candidate.model_validate(sample[1]),src)
    proof={k:v for k,v in old.solutions[1].model_dump().items() if k!='question_id'}
    proof['steps'][0]['conclusion']='修订后的第二问推导'
    raw={'updates':{'Q2':{'reason':'第二问的这一处推导存在明确错误，需要修正；其余小问未受到影响。','proof':proof}}}
    new,patch=apply(raw,old,src);canonical_page(new,src);check_candidate(new,src)
    assert new.solutions[0]==old.solutions[0] and new.solutions[1]!=old.solutions[1]
    assert [t['board'] for t in new.spec['tabs']]==[t['board'] for t in old.spec['tabs']]
    assert old.solutions[1].steps[0].conclusion!='修订后的第二问推导'
    from jsonschema import validate
    validate(raw,output_schema(src.model_dump()))


@pytest.mark.parametrize('mode',['empty','unknown','diagram','full_solutions'])
def test_patch_rejects_missing_or_unscoped_and_nonmath_data(sample,mode):
    src=Source.model_validate(sample[0]);old=Candidate.model_validate(sample[1])
    proof={k:v for k,v in old.solutions[0].model_dump().items() if k!='question_id'}
    raw={'updates':{'Q1':{'reason':'这是一条具有足够详细依据的数学修订说明，用于测试严格契约。','proof':proof}}}
    if mode=='empty':raw={'updates':{}}
    elif mode=='unknown':raw['updates']['Q404']=raw['updates'].pop('Q1')
    elif mode=='diagram':raw['spec']={}
    else:raw={'solutions':sample[1]['solutions']}
    with pytest.raises(ValueError):apply(raw,old,src)


def test_disputed_feedback_may_keep_proof_for_independent_review(sample):
    src=Source.model_validate(sample[0]);old=Candidate.model_validate(sample[1])
    proof={k:v for k,v in old.solutions[0].model_dump().items() if k!='question_id'}
    new,_=apply({'updates':{'Q1':{'reason':'此处反馈本身可能不成立，原推导依题设完整保留并请求独立复核，不捏造修改。','proof':proof}}},old,src)
    assert new==old
