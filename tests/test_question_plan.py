import copy
import pytest
from math_agent.contracts import Source, Solution
from math_agent.question_plan import build_plan, ready_groups, scope_payload, validate_basis, scheduling_priorities


def source():
    return Source.model_validate({'title':'依赖测试','problem_text':'条件及三问','conditions':[
        {'id':'C1','text':'公共条件','origin':'question_text','image_ids':[],'question_ids':[]},
        {'id':'C2','text':'第二问局部条件','origin':'question_text','image_ids':[],'question_ids':['Q2']}],
        'questions':[{'id':f'Q{i}','text':f'求目标{i}'} for i in range(1,4)],'reference_summary':'','uncertainties':[]})


def metadata(deps=None):
    return {'groups':[{'question_ids':[f'Q{i}'],'depends_on':(deps or {}).get(f'Q{i}',[]),
                      'dependency_status':'known'} for i in range(1,4)]}


def solutions():
    return [Solution.model_validate({'question_id':f'Q{i}','result':'结论','steps':[
        {'basis_ids':['C1'],'premise':'条件','rule':'推导','conclusion':'结论'}],
        'cases':[],'domain_and_boundaries':'边界','condition_ids':['C1']}) for i in range(1,4)]


def test_missing_plan_is_not_independence():
    p=build_plan(source());assert not p['eligible']
    assert p['groups'][0]['question_ids']==['Q1','Q2','Q3']


def test_shared_condition_does_not_imply_dependency():
    s=source();s.conditions[0].question_ids=['Q1','Q2','Q3']
    p=build_plan(s,metadata());assert p['eligible']
    assert len(ready_groups(p,[]))==3


def test_long_ready_question_is_prioritized_without_changing_source_or_plan():
    s=source();s.questions[2].text='较长的数学综合问题。'*20
    p=build_plan(s,metadata());old_source=s.model_dump();old_plan=copy.deepcopy(p)
    scores=scheduling_priorities(s,p)
    ready=sorted(ready_groups(p,[]),key=lambda g:-scores[g['id']])
    assert ready[0]['question_ids']==['Q3']
    assert s.model_dump()==old_source and p==old_plan


def test_small_prerequisite_of_long_question_is_prioritized_but_child_is_not_ready():
    s=source();s.questions[1].text='独立问题。'*10;s.questions[2].text='依赖前置证明的较长综合问题。'*20
    p=build_plan(s,metadata({'Q3':['Q1']}));scores=scheduling_priorities(s,p)
    ready=sorted(ready_groups(p,[]),key=lambda g:-scores[g['id']])
    assert [g['id'] for g in ready]==['G1','G2']
    assert 'G3' not in {g['id'] for g in ready}
    assert 'G3' in {g['id'] for g in ready_groups(p,['Q1'])}


def test_dependency_closure_and_ready_waves():
    p=build_plan(source(),metadata({'Q2':['Q1'],'Q3':['Q2']}))
    assert [g['id'] for g in ready_groups(p,[])]==['G1']
    assert [g['id'] for g in ready_groups(p,['Q1'])]==['G2']
    assert p['groups'][2]['context_question_ids']==['Q1','Q2','Q3']
    assert ready_groups(p,['Q1','Q2','Q3'])==[]


def test_reverse_question_dependency_falls_back_without_reordering_source():
    s=source();old=s.model_dump()
    p=build_plan(s,metadata({'Q1':['Q3']}))
    assert not p['eligible'] and '原题靠后' in p['reason']
    assert p['groups'][0]['question_ids']==['Q1','Q2','Q3']
    assert s.model_dump()==old


def test_prerequisite_group_cannot_leak_a_later_question_result():
    m={'groups':[{'question_ids':['Q1','Q3'],'depends_on':[],'dependency_status':'known'},
                 {'question_ids':['Q2'],'depends_on':['Q1'],'dependency_status':'known'}]}
    p=build_plan(source(),m)
    assert not p['eligible'] and len(p['groups'])==1


def test_metadata_row_order_is_not_original_question_order():
    m=metadata({'Q3':['Q1']});m['groups'].reverse()
    p=build_plan(source(),m)
    assert p['eligible']
    assert p['groups'][-1]['question_ids']==['Q3']


@pytest.mark.parametrize('change',['unknown','missing','duplicate','cycle','bad_dependency'])
def test_invalid_or_unknown_metadata_is_conservative(change):
    m=metadata()
    if change=='unknown':
        m['groups'][0]['dependency_status']='unknown'
        assert not build_plan(source(),m)['eligible'];return
    if change=='missing':m['groups'].pop()
    if change=='duplicate':m['groups'][2]['question_ids']=['Q2']
    if change=='cycle':m=metadata({'Q1':['Q2'],'Q2':['Q1']})
    if change=='bad_dependency':m['groups'][0]['depends_on']=['Q404']
    with pytest.raises(ValueError):build_plan(source(),m)


@pytest.mark.parametrize('text',['由上一问可知','在第(2)问基础上讨论','(3)中的①②分别求解','由（2）得出结论'])
def test_original_parent_and_leaf_labels_are_not_guessed(text):
    s=source();s.questions[-1].text=text
    assert not build_plan(s,metadata())['eligible']


@pytest.mark.parametrize('text',[
    '已知函数：①y=-2x和y=2x；②y=-x+3和y=3x-3；③y=x²和y=-x²，选择符合条件的序号。',
    '判断关系：①AB∥CD；②EF⊥GH。',
    '①x>0；②x≤0，选择可能的取值范围。',
])
def test_local_math_options_are_not_cross_question_references(text):
    s=source();s.questions[1].text=text
    assert build_plan(s,metadata())['eligible']


@pytest.mark.parametrize('text',[
    '已知两交点且三角形面积为4．①求参数的值；',
    '①证明两三角形相似；②求线段长。',
    '给定函数。①讨论其单调性。',
    '给定函数。②讨论其单调性。',
    '②求线段长；③证明线段相等。',
])
def test_local_task_headings_do_not_need_original_question_id_mapping(text):
    s=source();s.questions[1].text=text
    assert build_plan(s,metadata())['eligible']


@pytest.mark.parametrize('text',[
    '根据①和②继续推导', '已知：①成立；②成立', '已知：②x=1；③y=2',
    '已知：①x=1；②y=2。由①继续求解', '由上一问：①x=1；②y=2',
    '由（2）中的①x=1；②y=2继续讨论', '条件①x=1；②y=2',
])
def test_prose_references_and_uncertain_lists_still_stay_whole(text):
    s=source();s.questions[1].text=text
    assert not build_plan(s,metadata())['eligible']


def test_explicit_question_reference_requires_declared_dependency():
    s=source();s.questions[-1].text='由Q1的结论继续推导'
    with pytest.raises(ValueError,match='未声明'):build_plan(s,metadata())
    assert build_plan(s,metadata({'Q3':['Q1']}))['eligible']


def test_payload_keeps_original_ids_and_conditions_without_unfinished_results():
    s=source();p=build_plan(s,metadata({'Q3':['Q1']}));g=p['groups'][-1]
    with pytest.raises(ValueError,match='尚未完成'):scope_payload(s,g,[])
    sol=solutions();old=copy.deepcopy(s.model_dump());v=scope_payload(s,g,sol[:2])
    assert [v['question_id'] for v in v['completed_dependencies']]==['Q1']
    assert v['completed_step_ids']=={'Q1':['Q1:S1']}
    assert v['source']==old and s.model_dump()==old
    assert v['output_question_ids']==['Q3']


def test_cross_branch_reference_blocks_merge_even_when_steps_exist():
    s=source();p=build_plan(s,metadata());sol=solutions()
    sol[2].steps[0].basis_ids=['Q1:S1']
    with pytest.raises(ValueError,match='跨组'):validate_basis(s,p,sol)
    assert validate_basis(s,build_plan(s,metadata({'Q3':['Q1']})),sol)


@pytest.mark.parametrize('basis',['Q3:S1','Q1:S2','C404'])
def test_future_or_missing_basis_rejected(basis):
    sol=solutions();sol[0].steps[0].basis_ids=[basis]
    with pytest.raises(ValueError,match='尚未完成'):validate_basis(source(),build_plan(source(),metadata()),sol)


def test_local_conditions_cannot_be_shared_by_having_a_dependency():
    s=source();sol=solutions();p=build_plan(s,metadata({'Q3':['Q2']}))
    sol[2].steps[0].basis_ids=['C2']
    with pytest.raises(ValueError,match='局部条件'):validate_basis(s,p,sol)
    sol[2].steps[0].basis_ids=['Q2:S1'];sol[1].condition_ids=['C2']
    sol[1].steps[0].basis_ids=['C2'];assert validate_basis(s,p,sol)


def test_no_omission_duplicate_solution_or_empty_basis():
    s=source();p=build_plan(s,metadata());sol=solutions()
    with pytest.raises(ValueError):validate_basis(s,p,sol[:-1])
    sol[0].steps[0].basis_ids=[]
    with pytest.raises(ValueError,match='缺少依据'):validate_basis(s,p,sol)


def test_same_group_is_solved_together_not_injected_as_known():
    s=source();m={'groups':[{'question_ids':['Q1','Q2'],'depends_on':['Q1'],'dependency_status':'known'},
                          {'question_ids':['Q3'],'depends_on':['Q2'],'dependency_status':'known'}]}
    p=build_plan(s,m);assert p['groups'][0]['question_ids']==['Q1','Q2']
    assert scope_payload(s,p['groups'][0],[])['completed_dependencies']==[]
    assert scope_payload(s,p['groups'][0],[])['completed_step_ids']=={}
    sol=solutions();sol[1].steps[0].basis_ids=['Q1:S1'];sol[2].steps[0].basis_ids=['Q2:S1']
    assert validate_basis(s,p,sol)


def test_parallelism_analysis_chain_has_no_overlap_without_altering_plan():
    from math_agent.question_plan import analyze_parallelism
    p=build_plan(source(),metadata({'Q2':['Q1'],'Q3':['Q2']}));old=copy.deepcopy(p)
    assert analyze_parallelism(p)=={'max_ready_groups':1,'has_overlap':False}
    assert p==old and p['eligible']


def test_parallelism_analysis_independent_groups():
    from math_agent.question_plan import analyze_parallelism
    p=build_plan(source(),metadata())
    assert analyze_parallelism(p)=={'max_ready_groups':3,'has_overlap':True}


def test_parallelism_analysis_diamond_waits_for_both_branches():
    from math_agent.question_plan import analyze_parallelism
    p={'groups':[{'id':'G1','depends_on':[]},
                 {'id':'G2','depends_on':['G1']},
                 {'id':'G3','depends_on':['G1']},
                 {'id':'G4','depends_on':['G2','G3']}]}
    assert analyze_parallelism(p)=={'max_ready_groups':2,'has_overlap':True}


@pytest.mark.parametrize('groups',[
    [{'id':'G1','depends_on':['G2']}],
    [{'id':'G1','depends_on':['G2']},{'id':'G2','depends_on':['G1']}],
    [{'id':'G1','depends_on':[]},{'id':'G1','depends_on':[]}],
])
def test_parallelism_analysis_rejects_invalid_graph(groups):
    from math_agent.question_plan import analyze_parallelism
    with pytest.raises(ValueError):analyze_parallelism({'groups':groups})
