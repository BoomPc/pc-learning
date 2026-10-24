import copy
import pytest
from math_agent.contracts import Source,Candidate
from math_agent.proof_audit import proof_targets,validate_proof_review


def test_every_step_and_boundary_requires_explicit_review(sample):
    source=Source.model_validate(sample[0]);solutions=Candidate.model_validate(sample[1]).solutions
    raw=copy.deepcopy(sample[2]);raw['proof_checks']=[{'id':x,'verdict':'pass','evidence':'核对当前前提与结论'} for x in proof_targets(solutions)]
    validate_proof_review(raw,source,solutions)
    for mutation in ('missing','duplicate','hidden_issue','wrong_target'):
        bad=copy.deepcopy(raw)
        if mutation=='missing':bad['proof_checks'].pop()
        if mutation=='duplicate':bad['proof_checks'].append(bad['proof_checks'][0])
        if mutation in {'hidden_issue','wrong_target'}:
            bad['proof_checks'][0]['verdict']='issue'
        if mutation=='wrong_target':
            bad['verdict']='revise';bad['questions'][0]['verdict']='issue'
            bad['issues']=[{'stage':'math','target':'unrelated','detail':'不对应真实失败步骤'}]
        with pytest.raises(ValueError):validate_proof_review(bad,source,solutions)
    raw['verdict']='revise';raw['proof_checks'][0]['verdict']='issue';raw['questions'][0]['verdict']='issue'
    raw['issues']=[{'stage':'math','target':raw['proof_checks'][0]['id'],'detail':'此处错误等式需修正'}]
    assert validate_proof_review(raw,source,solutions).verdict=='revise'


def test_one_root_issue_can_cover_dependent_steps_without_erasing_checks(sample):
    source=Source.model_validate(sample[0]);solutions=Candidate.model_validate(sample[1]).solutions
    raw=copy.deepcopy(sample[2]);raw['proof_checks']=[{'id':x,'verdict':'pass','evidence':'核验依据'} for x in proof_targets(solutions)]
    qid=solutions[0].question_id
    for c in raw['proof_checks']:
        if c['id'].startswith(qid+':'):c.update(verdict='issue',evidence='依赖本问第一步的错误，尚不能成立')
    raw['verdict']='revise';raw['questions'][0]['verdict']='issue'
    raw['issues']=[{'stage':'math','target':qid+':S1','detail':'错误根因'}]
    result=validate_proof_review(raw,source,solutions)
    assert len(result.proof_checks)==len(raw['proof_checks'])
    assert result.proof_checks[-1].id.endswith('boundary')
