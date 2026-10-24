"""Package trusted JSXGraph assets, then inspect actual native objects in Chromium."""
from __future__ import annotations
import json
import math
import os
from pathlib import Path
import time
from .spec import compile_page, POINTS
from ..storage import write_json
HERE = Path(__file__).resolve().parent


def collapsed_segment(obj):
    # A zero-length native segment can be displayed as coincident endpoints.
    # It has no supporting line; derived constructions must still be inspected.
    if obj.get('kind') != 'segment' or obj.get('length') != 0:
        return False
    points=obj.get('endpoints')
    return (isinstance(points,list) and len(points)==2 and
            all(isinstance(p,list) and len(p)==2 and
                all(isinstance(v,(float,int)) and math.isfinite(v) for v in p) for p in points) and
            points[0]==points[1])


def build_html(spec):
    values = {
        '__JXG_CSS__': (HERE/'vendor/jsxgraph.css').read_text(),
        '__JXG_JS__': (HERE/'vendor/jsxgraphcore.js').read_text().replace('</script', '<\\/script'),
        '__ADAPTER__': (HERE/'adapter.js').read_text(),
        '__LESSON__': json.dumps(compile_page(spec), ensure_ascii=False).replace('&','\\u0026').replace('<','\\u003c').replace('>','\\u003e'),
    }
    # One substitution pass: user text containing a placeholder cannot inject an asset.
    import re
    return re.sub(r'__(?:JXG_CSS|JXG_JS|ADAPTER|LESSON)__', lambda m: values[m[0]], (HERE/'page.html').read_text())

def export(spec, directory):
    from playwright.sync_api import sync_playwright
    started = time.monotonic()
    result=directory/'result.html'; result.write_text(build_html(spec))
    errors=[]; samples=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True, executable_path=os.getenv('MATH_AGENT_CHROMIUM_EXECUTABLE') or os.getenv('GGB_CHROMIUM_EXECUTABLE'))
        try:
            page=browser.new_page(viewport={'width':1200,'height':1000})
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.route('**/*',lambda route: route.continue_() if route.request.url == result.as_uri() else route.abort())
            page.goto(result.as_uri(),wait_until='load')
            if errors: raise ValueError('JSXGraph 构造失败：'+'；'.join(errors)[:2000])
            page.wait_for_function("window.mathAgent && document.documentElement.dataset.ready==='true'",timeout=10000)
            for index,tab in enumerate(spec['tabs']):
                page.evaluate('(i)=>mathAgent.select(i)',index)
                slider=tab.get('controls',{}).get('slider')
                values=[None]
                if slider:
                    controls=tab['controls']; lo,hi=slider['min'],slider['max']
                    fractions=sorted(set([i/10 for i in range(11)]+[.000001,.0001,.001,.01,.99,.999,.9999,.999999]))
                    values=sorted(set([lo+(hi-lo)*f for f in fractions]+[slider['default']]+controls['solution_targets']+[b['value'] for b in controls['jump_buttons']]))
                for value in values:
                    if value is not None: page.evaluate('([i,v])=>mathAgent.setParameter(i,v)',[index,value])
                    snapshot=page.evaluate('(i)=>mathAgent.snapshot(i)',index)
                    bounds=page.evaluate('(i)=>[mathAgent.states[i].board.canvasWidth,mathAgent.states[i].board.canvasHeight]',index)
                    visible={o['id'] for o in tab['board']['objects'] if o['visible']}
                    failures=[]
                    for name,obj in snapshot['objects'].items():
                        if obj['kind'] in POINTS and any(obj.get(k) is None or not math.isfinite(obj[k]) for k in ('x','y')): failures.append(name)
                        if obj['kind']=='circle' and (obj['radius'] is None or not math.isfinite(obj['radius']) or obj['radius']<=0): failures.append(name)
                        if obj['kind'] in {'line','segment','parallel','perpendicular'}:
                            coeff=obj['coefficients']
                            if (any(v is None or not math.isfinite(v) for v in coeff) or math.hypot(coeff[1],coeff[2])<1e-12) and not collapsed_segment(obj): failures.append(name)
                    clipped=[name for name,obj in snapshot['objects'].items() if name in visible and obj['kind'] in POINTS and name not in failures and
                             any(v is None or not 5 <= v <= bounds[i]-5 for i,v in enumerate(obj['screen']))]
                    if (clipped or failures) and snapshot['inDomain']:
                        write_json(directory/'observation-failure.json', {'tab':index,'parameter':value,'snapshot':snapshot,'clipped':clipped,'undefined':failures})
                    if clipped and snapshot['inDomain']: raise ValueError('可见点被画布裁切，请调整 bounding_box：'+','.join(clipped)+f' (tab={index}, t={value})')
                    if failures and snapshot['inDomain']: raise ValueError('JSXGraph 对象在题设范围内无定义：'+','.join(failures)+f' (t={value})')
                    samples.append({'tab':index,'parameter':value,'in_domain':snapshot['inDomain'],'viewport':snapshot['viewport'],'undefined_objects':failures,'collapsed_segments':[name for name,obj in snapshot['objects'].items() if collapsed_segment(obj)],'objects':snapshot['objects']})
                if slider: page.evaluate('([i,v])=>mathAgent.setParameter(i,v)',[index,slider['default']])
                page.screenshot(path=str(directory/f'tab-{index:02d}.png'))
            if errors: raise ValueError('JSXGraph 浏览器错误：'+'；'.join(errors)[:2000])
            page.evaluate('mathAgent.select(0)'); page.screenshot(path=str(directory/'preview.png'))
            version=page.evaluate('mathAgent.version')
        finally: browser.close()
    write_json(directory/'export-check.json',{'status':'pass','engine':'JSXGraph','version':version,'seconds':round(time.monotonic()-started,3),'sample_count':len(samples),'samples':samples,'browser_errors':errors,
        'scope':'真实 JSXGraph 对象与有限参数采样；不代表整题证明或完整区间已验证'})
    return result
