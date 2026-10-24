"""Coincidence is a valid segment display, never a valid supporting line."""
import json, math
import pytest
from math_agent.jsxgraph.export import collapsed_segment
from math_agent.rendering import render, RenderError
from test_geometry_regressions import browser


def scene(kind='segment',dependent=False):
    objects=[{'id':'A','kind':'point','coords':[0,0]},
        {'id':'B','kind':'translation','parents':['A'],'vector':['t',0]},
        {'id':'L','kind':kind,'parents':['A','B']}]
    if dependent:
        objects += [{'id':'P','kind':'point','coords':[1,2]},
                    {'id':'H','kind':'perpendicularpoint','parents':['P','L']}]
    return {'format':'jsxgraph-v1','title':'零长度线段展示','problem_text':'合成边界测试，不代表数学证明',
        'tabs':[{'tab_title':'重合边界','board':{'viewport':'fit_points','axis':False,'objects':objects},
         'controls':{'slider':{'min':0,'max':1,'default':0}},
         'steps':[{'head':'观察','content':'两端点重合时长度为零，支撑直线没有定义。'}],'conclusion':'测试'}]}


def test_only_actual_finite_coincident_segment_is_displayable():
    good={'kind':'segment','length':0,'endpoints':[[0,0],[0,0]]}
    assert collapsed_segment(good)
    for changes in [{'kind':'line'},{'length':1},{'endpoints':[[None,0],[None,0]]},
                    {'endpoints':[[0,0],[1,0]]},{'endpoints':[[math.inf,0],[math.inf,0]]}]:
        assert not collapsed_segment({**good,**changes})


def test_actual_native_segment_can_collapse_without_changing_geometry(browser,tmp_path):
    html=render(scene(),tmp_path/'zero-segment')
    report=json.loads((html.parent/'export-check.json').read_text())
    at_zero=[s for s in report['samples'] if s['parameter']==0]
    assert at_zero and all(s['collapsed_segments']==['L'] and not s['undefined_objects'] for s in at_zero)
    assert all(s['objects']['A']['x']==s['objects']['B']['x']==0 for s in at_zero)
    page=browser.new_page();page.goto(html.as_uri())
    for t in [0,1,0]:
        page.evaluate('(t)=>mathAgent.setParameter(0,t)',t)
        data=page.evaluate('mathAgent.snapshot(0).objects.L')
        assert data['length']==pytest.approx(t)
        assert data['nativeType']=='segment'
    page.close()


@pytest.mark.parametrize('kind,dependent',[('line',False),('segment',True)])
def test_undefined_supporting_line_or_dependent_point_still_blocks(browser,tmp_path,kind,dependent):
    with pytest.raises(RenderError,match='无定义'):
        render(scene(kind,dependent),tmp_path/(kind+str(dependent)))
