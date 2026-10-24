"""Real JSXGraph replay of reviewed historical scenes; zero model calls."""
import json,os,sys,time,math
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from math_agent.rendering import render
from math_agent.storage import write_json
from geometry_expectations import expected
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'evaluation/jsxgraph'

def run():
    start=time.monotonic();rows=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path=os.getenv('MATH_AGENT_CHROMIUM_EXECUTABLE') or os.getenv('GGB_CHROMIUM_EXECUTABLE'))
        for case in ('01','08','16','21','28','36','41','48','56'):
            row={'case':case,'model_calls':0,'scope':'人工迁移后的局部场景，非模型新输出、非整题证明'};now=time.monotonic();page=None
            try:
                folder=BASE/case;spec=json.loads((folder/'spec.json').read_text());file=render(spec,folder/'output')
                report=json.loads((folder/'output/export-check.json').read_text())
                page=browser.new_page(viewport={'width':1200,'height':1000});page.goto(file.as_uri())
                tab=spec['tabs'][0];samples=[]
                for record in report['samples']:
                    t=record['parameter']
                    if t is not None:page.evaluate('(t)=>mathAgent.setParameter(0,t)',t)
                    snap=page.evaluate('mathAgent.snapshot(0)');points=expected(case,t or 0)
                    for name,xy in points.items():
                        obj=snap['objects'][name]
                        assert max(abs(obj['x']-xy[0]),abs(obj['y']-xy[1]))<1e-8,(case,t,name,obj,xy)
                        # Verify native SVG point coordinates equal the board's transformed coordinates.
                        if next(o for o in tab['board']['objects'] if o['id']==name).get('visible',True):
                            actual=page.evaluate("name=>{const o=mathAgent.states[0].objects[name];return [Number(o.rendNode.getAttribute('cx')),Number(o.rendNode.getAttribute('cy'))]}",name)
                            assert max(abs(actual[i]-obj['screen'][i]) for i in (0,1))<.02,(case,t,name,'SVG')
                    # Segments and polygons must refer to the same native moving point objects.
                    for definition in tab['board']['objects']:
                        if definition['kind']=='segment':
                            values=page.evaluate("id=>{const l=mathAgent.states[0].objects[id];return [[l.point1.X(),l.point1.Y()],[l.point2.X(),l.point2.Y()]]}",definition['id'])
                            for i,ref in enumerate(definition['parents']):
                                point=snap['objects'][ref];assert max(abs(values[i][0]-point['x']),abs(values[i][1]-point['y']))<1e-9
                        if definition['kind']=='polygon':
                            values=snap['objects'][definition['id']]['vertices']
                            for i,ref in enumerate(definition['parents']):
                                point=snap['objects'][ref];assert max(abs(values[i][0]-point['x']),abs(values[i][1]-point['y']))<1e-9
                    samples.append({'parameter':t,'coordinates':{n:[snap['objects'][n]['x'],snap['objects'][n]['y']] for n in points}})
                if 'controls' in tab:
                    for index,jump in enumerate(tab['controls'].get('jump_buttons',[])):
                        page.locator('.jump-btn').nth(index).click();assert abs(float(page.locator('input[type=range]').input_value())-jump['value'])<1e-10
                    page.evaluate('(t)=>mathAgent.setParameter(0,t)',tab['controls']['slider']['default'])
                page.screenshot(path=str(folder/'output/audited-preview.png'))
                page.set_viewport_size({'width':390,'height':844});page.wait_for_function('document.documentElement.scrollWidth<=innerWidth+1')
                page.screenshot(path=str(folder/'output/mobile-preview.png'))
                row.update(status='pass',samples=samples,engine=report['engine'],version=report['version'])
            except Exception as exc:row.update(status='fail',error=str(exc))
            finally:
                if page:page.close()
            row['seconds']=round(time.monotonic()-now,3);rows.append(row)
            print(case,row['status'],row['seconds'],row.get('error',''),flush=True)
            write_json(BASE/'replay-results.json',{'cases':rows,'seconds':round(time.monotonic()-start,3)})
        browser.close()
    if any(r['status']!='pass' for r in rows):raise SystemExit(1)
if __name__=='__main__':run()
