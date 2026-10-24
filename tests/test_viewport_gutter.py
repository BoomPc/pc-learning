import json
import pytest
from math_agent.rendering import render,RenderError
from test_geometry_regressions import browser


def scene(outside=False):
    return {'format':'jsxgraph-v1','title':'视口边缘留白','problem_text':'仅检验相机，不改数学坐标',
        'tabs':[{'tab_title':'四边界','board':{'viewport':'manual','axis':True,'bounding_box':[0,10,4.5,0],
         'objects':[{'id':'O','kind':'point','coords':[0,0]},
                    {'id':'P','kind':'point','coords':[4.5,0]},
                    {'id':'Q','kind':'point','coords':[4.5,10]},
                    {'id':'R','kind':'point','coords':[0,10]},
                    {'id':'L','kind':'point','coords':[1000,1000] if outside else [1.25,5]}]},
          'steps':[{'head':'观察','content':'边缘点应完整显示，超出给定范围的错误点仍应阻断。'}],'conclusion':'测试'}]}


def test_native_boundary_points_are_visible_on_desktop_and_mobile_without_moving_geometry(browser,tmp_path):
    html=render(scene(),tmp_path/'gutter');report=json.loads((html.parent/'export-check.json').read_text())
    assert report['status']=='pass'
    page=browser.new_page();page.goto(html.as_uri())
    for width in [1200,390]:
        page.set_viewport_size({'width':width,'height':1000});page.evaluate('mathAgent.select(0)')
        data=page.evaluate('''() => { const s=mathAgent.states[0]; return {
            snapshot:mathAgent.snapshot(0),width:s.board.canvasWidth,height:s.board.canvasHeight,
            ratio:s.board.unitX/s.board.unitY}; }''')
        expected={'O':[0,0],'P':[4.5,0],'Q':[4.5,10],'R':[0,10],'L':[1.25,5]}
        for name,(x,y) in expected.items():
            obj=data['snapshot']['objects'][name]
            assert [obj['x'],obj['y']]==pytest.approx([x,y])
            assert 5<=obj['screen'][0]<=data['width']-5 and 5<=obj['screen'][1]<=data['height']-5
        assert data['ratio']==pytest.approx(1,abs=.002)
        left,top,right,bottom=data['snapshot']['viewport']
        assert left<=0 and right>=4.5 and top>=10 and bottom<=0
    page.close()


def test_real_out_of_frame_point_is_still_rejected(browser,tmp_path):
    with pytest.raises(RenderError,match='裁切'):render(scene(True),tmp_path/'outside')
