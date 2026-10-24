import copy,json,math
import pytest
from math_agent.rendering import render,strict_spec
from test_geometry_regressions import browser


def example():
    return {'format':'jsxgraph-v1','title':'方向和视野测试','problem_text':'独立工具测试，不是数学题验收。','tabs':[
        {'tab_title':'变化参数','board':{'viewport':'fit_points','objects':[
            {'id':'O','kind':'point','coords':[10,-3]},
            {'id':'P','kind':'point','coords':[12,-3]},
            {'id':'CW','kind':'rotation','parents':['P','O'],'direction':'clockwise','degrees':'t'},
            {'id':'CCW','kind':'rotation','parents':['P','O'],'direction':'counterclockwise','degrees':'t'},
            {'id':'Legacy','kind':'rotation','parents':['P','O'],'angle':'-t*pi/180'},
            {'id':'T','kind':'translation','parents':['CW'],'vector':['5*t','2*t']},
            {'id':'Hidden','kind':'point','coords':[1000000,1000000],'visible':False}
        ]},'controls':{'slider':{'min':0,'max':180,'default':60}},'steps':[{'head':'核验','content':'保留原生几何，只改变视野'}],'conclusion':'测试'}]}


@pytest.mark.parametrize('fields',[{'degrees':60},{'direction':'clockwise'},
    {'angle':1,'direction':'clockwise','degrees':60}, {'direction':'clockwise','degrees':-1},
    {'direction':'wrong','degrees':60}])
def test_rotation_rejects_ambiguous_missing_or_negative_units(fields):
    s=example();s['tabs'][0]['board']['objects'][2]={'id':'CW','kind':'rotation','parents':['P','O'],**fields}
    with pytest.raises(ValueError):strict_spec(s)


def test_manual_camera_still_requires_box_and_compilation_does_not_mutate():
    s=example();before=copy.deepcopy(s);strict_spec(s);assert s==before
    s['tabs'][0]['board']['viewport']='manual'
    with pytest.raises(ValueError,match='bounding_box'):strict_spec(s)


def test_directions_native_geometry_and_autofit_on_desktop_mobile(browser,tmp_path):
    html=render(example(),tmp_path/'view');page=browser.new_page(viewport={'width':1200,'height':1000});page.goto(html.as_uri())
    for width in [1200,390]:
        page.set_viewport_size({'width':width,'height':1000})
        if width==390:page.wait_for_function('mathAgent.states[0].board.canvasWidth<400')
        for t in [0,60,90,180]:
            page.evaluate('(v)=>mathAgent.setParameter(0,v)',t)
            snap=page.evaluate('mathAgent.snapshot(0)');o=snap['objects'];rad=t*math.pi/180
            for name,y in [('CW',-3-2*math.sin(rad)),('CCW',-3+2*math.sin(rad)),('Legacy',-3-2*math.sin(rad))]:
                assert [o[name]['x'],o[name]['y']]==pytest.approx([10+2*math.cos(rad),y],abs=1e-9)
                assert o[name]['nativeType']=='point'
            assert [o['T']['x'],o['T']['y']]==pytest.approx([o['CW']['x']+5*t,o['CW']['y']+2*t])
            w,h=page.evaluate('[mathAgent.states[0].board.canvasWidth,mathAgent.states[0].board.canvasHeight]')
            for name,p in o.items():
                if name!='Hidden':assert 5<p['screen'][0]<w-5 and 5<p['screen'][1]<h-5
            assert snap['viewport'][2]<10000  # Hidden helper does not force a useless scale.
    report=json.loads((tmp_path/'view/export-check.json').read_text())
    assert report['status']=='pass' and report['sample_count']>10
    page.close()


@pytest.mark.parametrize('bad',['negative_degrees','undefined_point'])
def test_autofit_does_not_hide_invalid_geometry(browser,tmp_path,bad):
    s=example()
    if bad=='negative_degrees':s['tabs'][0]['board']['objects'][2]['degrees']='-1'
    else:s['tabs'][0]['board']['objects'].append({'id':'Bad','kind':'point','coords':['1/(t-90)',0]})
    with pytest.raises(ValueError):render(s,tmp_path/bad)
