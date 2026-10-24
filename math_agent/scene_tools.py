"""Model tools observe actual JSXGraph objects; callers cannot supply substitute coordinates."""
from __future__ import annotations
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from .tools import definition, geometry_check
from .config import ROOT
from .jsxgraph.spec import Data, Board, Controls
from pydantic import Field


class PreviewTab(Data):
    board: Board
    controls: Controls | None = None


class PreviewSpec(Data):
    tabs: list[PreviewTab] = Field(min_length=1, max_length=12)


def preview_page(spec):
    """Preview-only wrapper; geometry and final page requirements remain strict."""
    value = PreviewSpec.model_validate(spec).model_dump(exclude_none=True)
    result = {'format':'jsxgraph-v1', 'title':'构图预览（未发布）', 'problem_text':'仅检查几何对象，非题目解答',
        'tabs':[{**tab, 'tab_title':str(i+1), 'steps':[{'head':'预览','content':'不代表解题已通过核验'}],
                 'conclusion':'未发布'} for i,tab in enumerate(value['tabs'])]}
    from .parent_binding import bind_parent_roles
    return bind_parent_roles(result)[0]


def preview_parameters():
    # JSON references must resolve at the function parameter root.
    spec = PreviewSpec.model_json_schema()
    definitions = spec.pop('$defs', {})
    params = {'type':'object','additionalProperties':False,'required':['spec','probes'],
        'properties':{'spec':spec, 'probes':PROBES}, '$defs':definitions}
    return params


RELATIONS = ['same_x', 'same_y', 'collinear', 'on_segment', 'parallel', 'perpendicular', 'equal_length']
PROBES = {'type': 'array', 'minItems': 1, 'maxItems': 16, 'items': {
    'type': 'object', 'additionalProperties': False, 'required': ['tab', 'checks'], 'properties': {
        'tab': {'type': 'integer', 'minimum': 0, 'maximum': 11},
        'parameter': {'type': 'number'},
        'checks': {'type': 'array', 'maxItems': 20, 'items': {'type': 'object', 'additionalProperties': False,
            'required': ['relation', 'points'], 'properties': {
                'relation': {'type': 'string', 'enum': RELATIONS},
                'basis_ids': {'type':'array','items':{'type':'string'},'maxItems':30},
                'rationale': {'type':'string','maxLength':1500},
                'expected': {'type': 'boolean', 'description': '可选。省略表示查询关系真假；显式填写true/false表示必须满足的预期断言。'},
                'points': {'type': 'array', 'minItems': 2, 'maxItems': 4,
                           'description': '只填点ID，不能填线ID。same_x/same_y=[A,B]；collinear=[A,B,C]；on_segment=[起点A,终点B,待测点P]检查P在线段AB内；parallel/perpendicular/equal_length=[A,B,C,D]检查AB与CD。',
                           'items': {'type': 'string', 'maxLength': 40}}}}}}}}
PREVIEW = definition('preview_scene', '提交spec.tabs的board/controls与probes观察真实JSXGraph。rotation用direction=clockwise/counterclockwise及degrees非负度数；board.viewport=fit_points按原生点适配视野，可省略bounding_box。每个probe必须有tab。无需正文，不会发布网页。', {}, [])
PREVIEW['function']['parameters'] = preview_parameters()
INSPECT = definition('inspect_scene', '只读观察当前待审网页。tab从0开始，parameter可选择滑块位置；用真实点ID检查关系。不能修改待审图。',
                     {'probes': PROBES}, ['probes'])


def inspection_definition(base=None,query_only=False):
    """Model-facing relation arity and assertion evidence contract.

    Keep the legacy runtime decoder/recovery unchanged: an invalid model call
    still becomes a recorded failure, never a silently repaired observation.
    """
    from .inspection_recovery import RELATION_ARITY
    tool=copy.deepcopy(INSPECT if base is None else base)
    check=tool['function']['parameters']['properties']['probes']['items']['properties']['checks']['items']
    if query_only:check['properties'].pop('expected',None)
    check['allOf']=[{'if':{'properties':{'relation':{'const':relation}},'required':['relation']},
                    'then':{'properties':{'points':{'minItems':count,'maxItems':count}}}}
                   for relation,count in RELATION_ARITY.items()]
    if 'expected' in check['properties']:
        check['allOf'].append({'if':{'required':['expected']},'then':{'required':['basis_ids','rationale'],
            'properties':{'basis_ids':{'minItems':1},'rationale':{'minLength':1}}}})
        tool['function']['description']+=' 写expected（包括false）必须有非空basis_ids和rationale；只想查询就省略expected。'
    else:tool['function']['description']+=' 本阶段只查询，不能填写expected。'
    tool['function']['description']+=' 关系点数由参数Schema限定；perpendicular/parallel/equal_length须[A,B,C,D]。'
    return tool


def fingerprint(spec):
    return hashlib.sha256(json.dumps(spec, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def compact_observation(report, spec):
    """Send default states plus failures; full finite sampling remains in the job artifact."""
    chosen = []
    for i, tab in enumerate(spec['tabs']):
        default = (tab.get('controls') or {}).get('slider', {}).get('default')
        sample = next((s for s in report.get('samples', []) if s['tab'] == i and s['parameter'] == default), None)
        if sample:
            points = {k: {'x': v['x'], 'y': v['y'], 'kind': v['kind']} for k, v in sample['objects'].items() if 'x' in v}
            chosen.append({'tab': i, 'parameter': default, 'points': dict(list(points.items())[:40]),
                           'viewport':sample.get('viewport'), 'points_truncated': len(points) > 40})
    return {'status': report.get('status'), 'engine': report.get('engine'), 'spec_sha256': fingerprint(spec),
            'sample_count': report.get('sample_count'), 'default_states': chosen,
            'scope': '有限采样；请对照解答中声明的关系，必要时调用inspect_scene选择额外参数和断言。不是一般证明。'}


def probe_scene(spec, probes, directory):
    from playwright.sync_api import sync_playwright
    from .rendering import strict_spec
    from .jsxgraph.export import build_html
    spec = strict_spec(spec)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'probe.html'; path.write_text(build_html(spec))
    rows, errors = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=os.getenv('MATH_AGENT_CHROMIUM_EXECUTABLE') or os.getenv('GGB_CHROMIUM_EXECUTABLE'))
        try:
            page = browser.new_page(viewport={'width':1200, 'height':1000})
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.route('**/*', lambda route: route.continue_() if route.request.url == path.as_uri() else route.abort())
            page.goto(path.as_uri(), wait_until='load'); page.wait_for_function('window.mathAgent', timeout=10000)
            for probe in probes:
                i = probe['tab']
                if i >= len(spec['tabs']): raise ValueError('不存在该tab')
                tab = spec['tabs'][i]; slider = (tab.get('controls') or {}).get('slider')
                page.evaluate('(i)=>mathAgent.select(i)', i)
                if 'parameter' in probe and not slider: raise ValueError('静态图不能指定parameter')
                value = probe.get('parameter', slider['default'] if slider else None)
                if slider:
                    if not math.isfinite(value) or not slider['min'] <= value <= slider['max']: raise ValueError('参数超出观察区间')
                    page.evaluate('([i,v])=>mathAgent.setParameter(i,v)', [i, value])
                snapshot = page.evaluate('(i)=>mathAgent.snapshot(i)', i)
                coords = {k:[v['x'],v['y']] for k,v in snapshot['objects'].items() if 'x' in v}
                results = []
                for check in probe['checks']:
                    ids, relation = check['points'], check['relation']
                    try:
                        selected = {k:coords[k] for k in ids}
                        if any(x is None or not math.isfinite(x) for xy in selected.values() for x in xy):
                            raise ValueError('点在该位置无定义')
                        if relation in {'same_x', 'same_y'}:
                            if len(ids) != 2: raise ValueError('坐标相等检查需要两个点')
                            axis = 0 if relation == 'same_x' else 1
                            a,b = (coords[k][axis] for k in ids)
                            ok = abs(a-b) <= 1e-5 * max(1,abs(a),abs(b))
                            result = {**check, 'pass': ok, 'observed': selected}
                        else:
                            result = geometry_check(selected,[check],tolerance=1e-5)['checks'][0]
                            result['observed'] = selected
                    except (KeyError,ValueError) as exc:
                        result = {**check,'pass':False,'error':str(exc)[:300]}
                    result['basis_ids'] = check.get('basis_ids',[])
                    result['rationale'] = check.get('rationale','')
                    result['holds'] = None if 'error' in result else result['pass']
                    result['expected'] = check.get('expected')
                    result['matches_expected'] = (result['holds'] == check['expected'] and snapshot['inDomain']) if 'expected' in check else None
                    results.append(result)
                rows.append({'tab':i,'parameter':value,'in_domain':snapshot['inDomain'], 'checks':results,
                             'points':dict(list(coords.items())[:40]), 'points_truncated':len(coords)>40})
            page.screenshot(path=str(directory/'probe.png'))
        finally: browser.close()
    return {'ok':not errors and all('error' not in c for s in rows for c in s['checks']),
            'assertions_pass':all(c['matches_expected'] is not False for s in rows for c in s['checks']),
            'engine':'JSXGraph','spec_sha256':fingerprint(spec),'probes':rows,'browser_errors':errors,
            'numeric_tolerance':1e-5,
            'scope':'指定参数处真实浏览器对象；模型选择的断言不等于原题全部条件。'}


class SceneTools:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.count = max([int(p.name[6:]) for p in directory.glob("scene-*") if p.name[6:].isdigit()], default=0)
        self.current = None

    def dispatch(self, name, args):
        from jsonschema import validate
        from .storage import write_json
        tool = PREVIEW if name == 'preview_scene' else INSPECT
        if name=='inspect_scene':
            from .inspection_recovery import schema_failure,reference_failure
            failure=schema_failure(args,self.current)
            if failure:return failure
            failure=reference_failure(args,self.current)
            if failure:return failure
        else:
            try: validate(args, tool['function']['parameters'])
            except Exception: raise ValueError('图形工具参数不符合声明格式') from None
        self.count += 1
        if self.count > 12: raise ValueError('浏览器观察工具次数达到上限')
        spec = preview_page(args['spec']) if name == 'preview_scene' else self.current
        if spec is None: raise ValueError('尚无待审图形')
        directory = self.directory / f'scene-{self.count:02d}'; directory.mkdir(parents=True)
        write_json(directory/'request.json', {'spec':spec,'probes':args['probes']})
        try:
            process = subprocess.run([sys.executable,'-m','math_agent.scene_tools',str(directory)],
                                     capture_output=True,text=True,timeout=45,cwd=ROOT)
        except subprocess.TimeoutExpired:
            return {'ok':False,'error':'浏览器观察超过45秒'}
        if process.returncode or not (directory/'observation.json').is_file():
            return {'ok':False,'error':process.stderr[-1000:] or '浏览器观察失败'}
        return json.loads((directory/'observation.json').read_text())


if __name__ == '__main__':
    from .storage import write_json
    folder = Path(sys.argv[1]); request = json.loads((folder/'request.json').read_text())
    try: result = probe_scene(request['spec'], request['probes'], folder)
    except Exception as exc: result = {'ok':False,'error':str(exc)[:1200]}
    write_json(folder/'observation.json',result)
