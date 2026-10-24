import pytest
from math_agent.rendering import render
from test_geometry_regressions import browser


def test_native_autoposition_separates_coincident_point_names_without_moving_points(browser,tmp_path):
    spec={'format':'jsxgraph-v1','title':'原生标签避让','problem_text':'展示层测试','tabs':[
        {'tab_title':'重合与分离','board':{'viewport':'fit_points','axis':False,'objects':[
            {'id':'A','kind':'point','coords':[0,0],'label':'A'},
            {'id':'B','kind':'point','coords':[2,2],'label':'B'},
            {'id':'D','kind':'translation','parents':['A'],'vector':['t',0],'label':'D'}]},
         'controls':{'slider':{'min':0,'max':1,'default':0}},'steps':[{'head':'观察','content':'点的坐标不变，只调整原生标签位置'}],'conclusion':'测试'}]}
    html=render(spec,tmp_path/'page');page=browser.new_page(viewport={'width':1200,'height':1000});page.goto(html.as_uri())
    for width in [1200,390]:
        page.set_viewport_size({'width':width,'height':1000})
        if width==390:page.wait_for_function('mathAgent.states[0].board.canvasWidth<400')
        for t in [0,1,0]:
            page.evaluate('(v)=>mathAgent.setParameter(0,v)',t)
            data=page.evaluate('''() => {
                const s=mathAgent.states[0];s.board.fullUpdate();
                return ['A','D'].map(id=>{const o=s.objects[id],r=o.label.rendNode.getBoundingClientRect();
                  return {x:o.X(),y:o.Y(),box:[r.left,r.top,r.right,r.bottom],auto:o.label.evalVisProp('autoposition')};});
            }''')
            assert data[0]['x']==0 and data[0]['y']==0
            assert data[1]['x']==pytest.approx(t) and data[1]['y']==0
            assert all(d['auto'] for d in data)
            a,b=[d['box'] for d in data]
            assert a[2]<=b[0] or b[2]<=a[0] or a[3]<=b[1] or b[3]<=a[1]
    page.close()


def test_native_labels_preserve_comparators_and_never_parse_markup(browser,tmp_path):
    labels=['x>0','0<x<2','<img src=x onerror=window.labelXss=1>','</script>']
    spec={'format':'jsxgraph-v1','title':'标签文字','problem_text':'纯文字标签', 'tabs':[
        {'tab_title':'比较符号','board':{'bounding_box':[-3,3,3,-3], 'objects':[
            {'id':f'P{i}','kind':'point','coords':[i-1,0],'label':label}
            for i,label in enumerate(labels)]},
         'steps':[{'head':'展示','content':'纯文字，不执行标记'}],'conclusion':'测试'}]}
    html=render(spec,tmp_path/'text-labels')
    page=browser.new_page();page.goto(html.as_uri())
    data=page.evaluate('''() => {
        const s=mathAgent.states[0];
        return {labels:Object.values(s.objects).map(o=>({name:o.name,
            text:o.label.rendNode.textContent, tag:o.label.rendNode.tagName,
            parse:o.label.evalVisProp('parse')})),
            injected:document.querySelectorAll('img').length,
            executed:window.labelXss || 0};
    }''')
    assert [item['name'] for item in data['labels']]==labels
    assert [item['text'] for item in data['labels']]==labels
    assert all(item['tag']=='text' and not item['parse'] for item in data['labels'])
    assert data['injected']==0 and data['executed']==0
    page.close()
