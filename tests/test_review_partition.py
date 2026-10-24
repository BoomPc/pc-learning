import copy
import pytest
from math_agent.contracts import Source,Candidate
from math_agent.review_partition import partition,scope_payload,merge


def data(sample):
    s=Source.model_validate(sample[0]);c=Candidate.model_validate(sample[1])
    for sol in c.solutions:
        for st in sol.steps:st.basis_ids=['C1']
    return s,c


def results(s,p):
    return {g['question_id']:{'verdict':'pass','conditions':[{'id':i,'verdict':'pass','evidence':'离线分区夹具'} for i in g['output_condition_ids']],
        'questions':[{'id':g['question_id'],'verdict':'pass','evidence':'离线分区夹具'}],'issues':[]} for g in p['groups']}


def test_explicit_cross_question_dependencies_stay_in_context_and_tab_numbers(sample):
    s,c=data(sample);c.solutions[1].steps[0].basis_ids=['Q1:S1'];p=partition(s,c)
    assert p['eligible'] and p['groups'][1]['context_questions']==['Q1','Q2']
    assert p['groups'][0]['context_tabs']==[0]
    payload=scope_payload(s,c,p['groups'][1]);assert payload['output_scope']['question_ids']==['Q2']
    assert [t['tab'] for t in payload['candidate']['tabs']]==[0,1]


def test_missing_declared_basis_does_not_silently_assume_independence(sample):
    s,c=data(sample);c.solutions[1].steps[0].basis_ids=[];p=partition(s,c)
    assert not p['eligible'] and all(g['context_questions']==['Q1','Q2'] for g in p['groups'])


def test_out_of_scope_condition_used_by_proof_remains_visible(sample):
    s,c=data(sample);condition=s.conditions[0].model_copy(deep=True);condition.id='C2';condition.question_ids=['Q1'];s.conditions.append(condition)
    c.solutions[1].steps[0].basis_ids=['C2'];p=partition(s,c)
    assert 'C2' in p['groups'][1]['context_condition_ids'] and 'C2' not in p['groups'][1]['output_condition_ids']


@pytest.mark.parametrize('status',['issue','unknown'])
def test_global_condition_disagreement_cannot_be_majority_voted_away(sample,status):
    s,c=data(sample);p=partition(s,c);r=results(s,p)
    r['Q2']['conditions'][0].update(verdict=status,evidence='这一分支发现未决或错误，不能丢弃')
    r['Q2']['verdict']='needs_input' if status=='unknown' else 'revise'
    if status=='issue':r['Q2']['issues']=[{'stage':'source','target':'C1','detail':'与题图有冲突'}]
    v=merge(s,p,r)
    assert v.conditions[0].verdict==status and v.verdict==('needs_input' if status=='unknown' else 'revise')


@pytest.mark.parametrize('change',['missing_branch','extra_condition','duplicate_question'])
def test_incomplete_partition_cannot_be_published(sample,change):
    s,c=data(sample);p=partition(s,c);r=results(s,p)
    if change=='missing_branch':r.pop('Q2')
    elif change=='extra_condition':r['Q2']['conditions'].append({'id':'C404','verdict':'pass','evidence':'不存在的条件'})
    else:r['Q2']['questions']*=2
    with pytest.raises(ValueError):merge(s,p,r)


def test_all_accepted_checks_merge_in_original_order_without_mutation(sample):
    s,c=data(sample);p=partition(s,c);r=results(s,p);old=copy.deepcopy(r)
    v=merge(s,p,dict(reversed(list(r.items()))));assert v.verdict=='pass'
    assert [q.id for q in v.questions]==['Q1','Q2'] and r==old


def test_textual_cross_question_reference_is_not_lost_when_basis_omits_it(sample):
    s,c=data(sample);c.solutions[1].cases=['由第1问得到的结论继续讨论。'];p=partition(s,c)
    assert p['groups'][1]['context_questions']==['Q1','Q2']


def test_unknown_question_reference_blocks_independence_assumption(sample):
    s,c=data(sample);c.solutions[1].cases=['由Q404可知。'];p=partition(s,c)
    assert not p['eligible'] and p['groups'][1]['unscoped_basis']


def test_shared_source_condition_keeps_related_figure_without_duplicating_proof(sample):
    s,c=data(sample);s.conditions[0].question_ids=['Q1','Q2'];p=partition(s,c);g=p['groups'][0]
    assert g['context_questions']==['Q1','Q2'] and g['proof_questions']==['Q1']
    v=scope_payload(s,c,g)
    assert [q['question_id'] for q in v['candidate']['solutions']]==['Q1']
    assert [t['tab'] for t in v['candidate']['tabs']]==[0,1]
    assert all('steps' not in t and 'conclusion' not in t for t in v['candidate']['tabs'])
