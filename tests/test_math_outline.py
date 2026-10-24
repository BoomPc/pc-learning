import copy
import pytest
from math_agent.contracts import Source
from math_agent.math_outline import check_outline,check_expansion


def values(sample):
    source=Source.model_validate(sample[0]);solutions=copy.deepcopy(sample[1]['solutions'])
    questions=[];coverage=[]
    for s in solutions:
        questions.append({'question_id':s['question_id'],'result':s['result'],'proof':[{'basis_ids':[source.conditions[0].id],'statement':'待核对的关键等式与推导'}],
            'cases':s['cases'],'boundaries':s['domain_and_boundaries'],'condition_ids':[source.conditions[0].id]})
        coverage.append({'outline_step':s['question_id']+':O1','solution_steps':[s['question_id']+':S1']})
    outline=check_outline({'questions':questions,'uncertainties':[]},source)
    return source,outline,{'solutions':solutions,'coverage':coverage}


def test_expansion_preserves_math_and_requires_all_proof_coverage(sample):
    source,outline,raw=values(sample)
    assert check_expansion(raw,source,outline).solutions[0].result==outline.questions[0].result
    for mutation in ['result','cases','boundary','missing','cross_question','unresolved','conditions']:
        changed=copy.deepcopy(raw);plan=outline.model_copy(deep=True)
        if mutation=='result':changed['solutions'][0]['result']='另一个答案'
        if mutation=='cases':changed['solutions'][0]['cases']=['删改分类']
        if mutation=='boundary':changed['solutions'][0]['domain_and_boundaries']='缩小定义域'
        if mutation=='missing':changed['coverage'].pop()
        if mutation=='cross_question':changed['coverage'][0]['solution_steps']=[changed['solutions'][1]['question_id']+':S1']
        if mutation=='unresolved':plan.uncertainties=['仍有未证步骤']
        if mutation=='conditions':changed['solutions'][0]['condition_ids']=[]
        with pytest.raises(ValueError):check_expansion(changed,source,plan)


def test_outline_dependencies_cannot_skip_missing_questions_or_cite_future(sample):
    source,outline,_=values(sample)
    raw=outline.model_dump();raw['questions'].pop()
    with pytest.raises(ValueError):check_outline(raw,source)
    raw=outline.model_dump();raw['questions'][0]['proof'][0]['basis_ids']=['Q1:O1']
    with pytest.raises(ValueError):check_outline(raw,source)
