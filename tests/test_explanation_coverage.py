import copy
from math_agent.contracts import Solution,Candidate
from math_agent.explanation_coverage import collect,require,CoverageError
import pytest


def solution(text):
    return Solution(question_id='Q1',result='结论',steps=[{'premise':text,'rule':'推导','conclusion':'结论','basis_ids':[]}],cases=[],domain_and_boundaries='范围',condition_ids=[])


def point(name,**kw):
    return {'id':name,'kind':'point','coords':[0,0],**kw}


def test_hidden_coordinate_helpers_are_reported_without_changes():
    board={'objects':[point('A',visible=False),point('B',visible=False)]};old=copy.deepcopy(board)
    issues=collect(solution('直线与坐标轴交于A(4,0)、B(0,4)，AB为斜边。'),board)
    assert {i['point_name'] for i in issues}=={'A','B'} and board==old
    assert all(i['stage']=='diagram' for i in issues)


def test_missing_explicit_point_and_triangle_vertices_are_reported():
    issues=collect(solution('作点H，考察△ABC。'),{'objects':[point('A'),point('B')]})
    assert {i['point_name'] for i in issues}=={'H','C'}


def test_subscript_point_names_share_native_binding_aliases_without_losing_indices():
    s=solution('点A₁与点H₁在线段上，连接A₁H₁。')
    board={'objects':[point('A1',label='A₁'),point('H1',label='H₁')]}
    assert collect(s,board)==[]
    board['objects'][1]['visible']=False
    assert {i['point_name'] for i in collect(s,board)}=={'H1'}


def test_prime_aliases_resolve_but_ambiguous_names_do_not():
    s=solution('连接AA′。')
    board={'objects':[point('A'),point('rotA',label="A'")]}
    assert collect(s,board)==[]
    board['objects'].append(point('other',label='A′'))
    assert len(collect(s,board))==1 and '多个' in collect(s,board)[0]['detail']


def test_unrelated_hidden_helpers_and_function_notation_are_not_forced_visible():
    board={'objects':[point('X',visible=False),{'id':'F','kind':'functiongraph'}]}
    s=solution('函数F(x,y)满足恒等式。采用SAS说明全等。')
    s.cases=['假设点X移动到某处，需另行讨论']
    assert collect(s,board)==[]


def test_actual_native_label_must_identify_the_point():
    assert collect(solution('点A在直线上。'),{'objects':[point('A',label='辅助点')]})
    assert not collect(solution('点A在直线上。'),{'objects':[point('A',label='辅助点A')]})


def test_coverage_gate_does_not_accept_model_or_browser_pass(sample):
    c=Candidate.model_validate(copy.deepcopy(sample[1]));c.solutions[0]=solution('直线过点H。')
    with pytest.raises(CoverageError) as e:require(c)
    assert e.value.issues[0]['point_name']=='H'


def test_agent_repairs_missing_point_and_keeps_proof(settings,job,sample):
    import json
    from dataclasses import replace
    from math_agent.pipeline import Runner
    from test_pipeline import provider,MemoryCache,renderer
    from test_compact_tools import pack
    from test_compact_review import pack_review
    source,prior,review=copy.deepcopy(sample)
    prior['solutions'][0]['steps'][0]['premise']='取点H为线段AB的中点。'
    patch={'edits':[{'tab':0,'upsert':[{'id':'H','kind':'midpoint','parents':['A','B'],'label':'H'}]}]}
    stages=[];runner=Runner(replace(settings,compact_tools=True),job[1],
        provider([source,pack(prior),patch,pack_review(review)],stages),MemoryCache,renderer)
    runner.run();report=json.loads((job[2]/'report.json').read_text())
    assert report['status']=='completed',report.get('error')
    assert stages==['source','solve','diagram','review']
    result=Candidate.model_validate(json.loads((job[2]/'candidate.json').read_text()))
    assert result.solutions==Candidate.model_validate(prior).solutions
    assert result.spec['tabs'][0]['board']['objects'][-1]['kind']=='midpoint'
