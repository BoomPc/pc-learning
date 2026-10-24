"""Native JSXGraph object invariants; includes browser rendering, not handwritten SVG."""
import copy,json,math,os
from pathlib import Path
import pytest
from math_agent.rendering import strict_spec,render
from math_agent.tools import geometry_check
from math_agent.config import ROOT

def scene():
    return {'format':'jsxgraph-v1','title':'JSXGraph 关系测试','problem_text':'人工测试场景，非模型解题。','tabs':[{'tab_title':'点线关系','board':{'bounding_box':[-3,6,8,-3],'axis':True,'objects':[
        {'id':'A','kind':'point','coords':[0,0]}, {'id':'B','kind':'point','coords':[4,0]},
        {'id':'P','kind':'point','coords':['t',2]}, {'id':'AB','kind':'line','parents':['A','B']},
        {'id':'M','kind':'midpoint','parents':['A','P']},
        {'id':'H','kind':'perpendicularpoint','parents':['P','AB']},
        {'id':'R','kind':'reflection','parents':['P','AB']},
        {'id':'v','kind':'perpendicular','parents':['AB','P']},
        {'id':'h','kind':'parallel','parents':['AB','P']},
        {'id':'I','kind':'intersection','parents':['v','AB'],'branch':0},
        {'id':'T','kind':'rotation','parents':['B','A'],'angle':'t'},
        {'id':'U','kind':'translation','parents':['P'],'vector':[1,'t']},
        {'id':'AP','kind':'segment','parents':['A','P']},
        {'id':'tri','kind':'polygon','parents':['A','B','P']},
        {'id':'circle','kind':'circle','parents':['P'],'radius':'sqrt(t+1)'},
    ]},'controls':{'slider':{'min':0,'max':2,'default':.5},'solution_targets':[math.sqrt(2)]},'steps':[{'head':'测试','content':'检查原生对象和依赖'}],'conclusion':'关系随参数保持'}]}

@pytest.fixture
def browser():
    if os.getenv('MATH_AGENT_BROWSER_TEST')!='1':pytest.skip('需要真实浏览器')
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b=p.chromium.launch(headless=True,executable_path=os.getenv('MATH_AGENT_CHROMIUM_EXECUTABLE') or os.getenv('GGB_CHROMIUM_EXECUTABLE'));yield b;b.close()

def load(browser,spec,tmp_path):
    file=render(spec,tmp_path/'output');page=browser.new_page();page.goto(file.as_uri());return page

def test_dependency_sort_cycle_and_wrong_types():
    s=scene();s['tabs'][0]['board']['objects'].reverse();clean=strict_spec(s)
    ids=[o['id'] for o in clean['tabs'][0]['board']['objects']];assert ids.index('A')<ids.index('M')
    s=scene();s['tabs'][0]['board']['objects'][4]['parents']=['M','P']
    with pytest.raises(ValueError,match='循环'):strict_spec(s)
    s=scene();s['tabs'][0]['board']['objects'][4]['parents']=['AB','P']
    with pytest.raises(ValueError,match='类型'):strict_spec(s)

@pytest.mark.parametrize('bad',['__import__("os")','t.__class__','foo(t)','sqrt(t,2)','z+1','1e999'])
def test_expression_rejects_code_unknown_variables_and_bad_arity(bad):
    s=scene();s['tabs'][0]['board']['objects'][2]['coords'][1]=bad
    with pytest.raises((ValueError,SyntaxError)):strict_spec(s)

@pytest.mark.parametrize('scale',[1,1e-4,1e4])
def test_relation_checks_are_invariant_under_uniform_scaling(scale):
    pts={n:[x*scale,y*scale] for n,(x,y) in {'A':(0,0),'B':(1,0),'C':(0,0),'D':(1,1)}.items()}
    result=geometry_check(pts,[{'relation':'parallel','points':['A','B','C','D']},{'relation':'perpendicular','points':['A','B','C','D']}]);assert not any(c['pass'] for c in result['checks'])

def test_native_relations_and_svg_positions(browser,tmp_path):
    page=load(browser,scene(),tmp_path)
    assert page.evaluate('mathAgent.engine')=='JSXGraph'
    assert 'DynamicMathEngine' not in page.content()
    for t in [0,.4,1.5,2]:
        page.evaluate('(t)=>mathAgent.setParameter(0,t)',t);snap=page.evaluate('mathAgent.snapshot(0)');o=snap['objects']
        expected={'M':[t/2,1],'H':[t,0],'R':[t,-2],'I':[t,0],'T':[4*math.cos(t),4*math.sin(t)],'U':[t+1,t+2]}
        for name,xy in expected.items():assert [o[name]['x'],o[name]['y']]==pytest.approx(xy,abs=1e-9)
        assert o['M']['nativeType']=='midpoint' and o['I']['nativeType']=='intersection'
        assert o['circle']['radius']==pytest.approx(math.sqrt(t+1))
        assert o['tri']['vertices'][2]==pytest.approx([t,2])
        # Read actual native SVG node coordinates, not only the library's numeric state.
        svg=page.evaluate("()=>{const p=mathAgent.states[0].objects.P;return [Number(p.rendNode.getAttribute('cx')),Number(p.rendNode.getAttribute('cy'))]}")
        assert svg==pytest.approx(o['P']['screen'],abs=.02)
    page.locator('.jump-btn').click();assert float(page.locator('input[type=range]').input_value())==pytest.approx(math.sqrt(2),abs=1e-12)
    page.set_viewport_size({'width':390,'height':844});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')

@pytest.mark.parametrize('expression,expected',[('pi',math.pi),('-(t-1)**2',-.25),('tan(t/10)',math.tan(.15)),('1e-3+t',1.501),('(-t)%2',.5)])
def test_expression_and_labels_in_native_points(browser,tmp_path,expression,expected):
    s=scene();s['tabs'][0]['board']['objects'][2].update(coords=['t',expression],label='P′')
    # Only expression point, to avoid zero-length unrelated segments during sampling.
    s['tabs'][0]['board']['objects']=s['tabs'][0]['board']['objects'][:3]
    page=load(browser,s,tmp_path);page.evaluate('mathAgent.setParameter(0,1.5)')
    assert page.evaluate('mathAgent.snapshot(0).objects.P.y')==pytest.approx(expected)
    assert page.evaluate('mathAgent.states[0].objects.P.name')=='P′'

def test_open_boundary_and_undefined_inside_domain(browser,tmp_path):
    s=scene();s['tabs'][0]['controls']['slider'].update(min_inclusive=False,max_inclusive=False)
    page=load(browser,s,tmp_path);page.evaluate('mathAgent.setParameter(0,0)')
    assert page.locator('input[type=range]').get_attribute('data-in-domain')=='false'
    assert '不包含' in page.locator('.domain-note').inner_text()
    s['tabs'][0]['controls']['solution_targets']=[0]
    with pytest.raises(ValueError,match='端点不能标为答案'):strict_spec(s)
    s=scene();s['tabs'][0]['board']['objects'][2]['coords'][1]='sqrt(t-1)'
    with pytest.raises(ValueError,match='无定义'):render(s,tmp_path/'bad')

def test_glider_and_two_circle_intersection_branches(browser,tmp_path):
    s=scene();s['tabs'][0].pop('controls');s['tabs'][0]['board']['objects']=[
      {'id':'A','kind':'point','coords':[0,0]}, {'id':'B','kind':'point','coords':[4,0]},
      {'id':'ca','kind':'circle','parents':['A'],'radius':3}, {'id':'cb','kind':'circle','parents':['B'],'radius':3},
      {'id':'I','kind':'intersection','parents':['ca','cb'],'branch':0},{'id':'J','kind':'intersection','parents':['ca','cb'],'branch':1},
      {'id':'G','kind':'glider','parents':['ca'],'coords':[3,0]}, {'id':'MG','kind':'midpoint','parents':['A','G']}]
    page=load(browser,s,tmp_path);snap=page.evaluate('mathAgent.snapshot(0).objects')
    assert snap['I']['x']==pytest.approx(2) and snap['J']['x']==pytest.approx(2)
    assert snap['I']['y']*snap['J']['y']==pytest.approx(-5)
    page.evaluate("()=>{mathAgent.states[0].objects.G.moveTo([1,4]);mathAgent.states[0].board.update();}")
    snap=page.evaluate('mathAgent.snapshot(0).objects');assert math.hypot(snap['G']['x'],snap['G']['y'])==pytest.approx(3)
    assert [snap['MG']['x'],snap['MG']['y']]==pytest.approx([snap['G']['x']/2,snap['G']['y']/2])

@pytest.mark.parametrize('box',[[-3,20,8,-3],[-20,6,20,-3]])
def test_responsive_view_contains_requested_box_without_distorting_geometry(browser,tmp_path,box):
    s=scene();s['tabs'][0]['board']['bounding_box']=box
    page=load(browser,s,tmp_path)
    for width in [1200,390]:
        page.set_viewport_size({'width':width,'height':900})
        page.evaluate('mathAgent.select(0)')
        actual=page.evaluate('()=>{const b=mathAgent.states[0].board;return {bbox:b.getBoundingBox(),ratio:b.unitX/b.unitY}}')
        assert actual['ratio']==pytest.approx(1,abs=.002)
        left,top,right,bottom=actual['bbox']
        assert left<=box[0]+.01 and top>=box[1]-.01 and right>=box[2]-.01 and bottom<=box[3]+.01

def test_clipped_point_is_not_published(browser,tmp_path):
    s=scene();s['tabs'][0]['board']['objects'][2]['coords']=[1000,1000]
    with pytest.raises(ValueError,match='裁切'):render(s,tmp_path/'bad-view')

def test_untrusted_text_remains_text_in_browser(browser,tmp_path):
    s=scene();payload='</script><script>window.injected=1</script>__JXG_JS__'
    s['problem_text']=payload;s['title']='安全文本测试'
    page=load(browser,s,tmp_path)
    assert page.locator('#problem').text_content()==payload
    assert page.evaluate('window.injected === undefined')
