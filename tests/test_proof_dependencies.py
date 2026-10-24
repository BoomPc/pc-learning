from types import SimpleNamespace as N
import pytest
from math_agent.proof_dependencies import review_dependencies

def test_transitive_local_conditions_reach_later_question_without_blanket_rejection():
    source=N(conditions=[N(id='C1',question_ids=[]),N(id='C2',question_ids=['Q1']),N(id='C3',question_ids=['Q1','Q2'])])
    solutions=[N(question_id='Q1',steps=[N(basis_ids=['C1','C2']),N(basis_ids=['Q1:S1']),N(basis_ids=['C3'])]),
               N(question_id='Q2',steps=[N(basis_ids=['Q1:S2']),N(basis_ids=['Q2:S1']),N(basis_ids=['Q1:S3'])])]
    rows=review_dependencies(source,solutions)['transfers']
    assert rows[0]=={'step':'Q2:S1','basis':'Q1:S2','source_conditions':['C1','C2'],'out_of_scope_conditions':['C2']}
    assert rows[1]['step']=='Q2:S2' and rows[1]['out_of_scope_conditions']==['C2']
    assert rows[2]['source_conditions']==['C3'] and rows[2]['out_of_scope_conditions']==[]
    assert all('verdict' not in row for row in rows)

def test_direct_foreign_condition_and_unknown_basis():
    source=N(conditions=[N(id='C1',question_ids=['Q1'])])
    result=review_dependencies(source,[N(question_id='Q2',steps=[N(basis_ids=['C1'])])])
    assert result['transfers'][0]['out_of_scope_conditions']==['C1']
    with pytest.raises(ValueError,match='尚未出现'):
        review_dependencies(source,[N(question_id='Q2',steps=[N(basis_ids=['Q2:S2'])])])
