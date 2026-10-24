"""Reviewer-selected, read-only native rotation counterexamples.

This is a tool, not an automatic case classifier. It never declares that a
hypothetical angle is allowed by the problem or edits the candidate drawing.
"""
import copy
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from .config import ROOT
from .tools import definition
from .rendering import strict_spec
from .scene_tools import fingerprint
from .proof_guards import TRIANGLE, RULES, _resolve_label
from .storage import write_json

TOOL=definition('probe_rotation_rule',
    '只读检查静态旋转示意图中某一步三角形定理的退化前提。选择同中心、同方向、同角度的完整原生rotation组、待查绝对角度（度）及该步明确引用的三角形点ID。工具只建立独立假设副本，不修改原图或证明，不判断该角度是否符合原题；若共线必须核对适用范围/独立边界证明。动态滑块图请用inspect_scene。没有反例不是证明。',
    {'tab':{'type':'integer','minimum':0,'maximum':11},
     'step_id':{'type':'string','pattern':r'^Q[1-9][0-9]*:S[1-9][0-9]*$'},
     'rotation_ids':{'type':'array','minItems':1,'maxItems':12,'uniqueItems':True,'items':{'type':'string','maxLength':40}},
     'angles':{'type':'array','minItems':1,'maxItems':4,'uniqueItems':True,'items':{'type':'number','minimum':0,'maximum':360}},
     'triangles':{'type':'array','minItems':1,'maxItems':6,'uniqueItems':True,'items':{'type':'array','minItems':3,'maxItems':3,'uniqueItems':True,'items':{'type':'string','maxLength':40}}},
     'rationale':{'type':'string','minLength':10,'maxLength':1500}},
    ['tab','step_id','rotation_ids','angles','triangles','rationale'])


def prepare(candidate,args):
    from jsonschema import validate,ValidationError
    try:validate(args,TOOL['function']['parameters'])
    except ValidationError as exc:raise ValueError('旋转取证参数不符合声明：'+exc.message[:300]) from None
    ti=args['tab']
    if ti>=len(candidate.solutions):raise ValueError('旋转取证小问不存在')
    solution=candidate.solutions[ti]
    prefix,number=args['step_id'].split(':S')
    if prefix!=solution.question_id or not 1<=int(number)<=len(solution.steps):raise ValueError('证明步骤不属于当前小问')
    step=solution.steps[int(number)-1]
    rules=[k for k,(_,pattern) in RULES.items() if pattern.search(step.rule)]
    if not rules:raise ValueError('该步骤未明确使用受检的中位线/全等/相似三角形规则')
    spec=strict_spec(candidate.spec);tab=spec['tabs'][ti];objects=tab['board']['objects'];by_id={o['id']:o for o in objects}
    if tab.get('controls',{}).get('slider'):raise ValueError('动态图请用inspect_scene选择原滑块参数，不替换其参数关系')
    declared=[]
    for match in TRIANGLE.finditer(step.premise+' '+step.conclusion):
        ids=[_resolve_label(n,objects) for n in match.groups()]
        if all(ids):declared.append(set(ids))
    if any(set(ids) not in declared for ids in args['triangles']):raise ValueError('仅可查询该步骤文字明确引用且能绑定原图的三角形')
    selected=[by_id.get(k) for k in args['rotation_ids']]
    if any(o is None or o['kind']!='rotation' for o in selected):raise ValueError('只可选择原生rotation点，不覆盖独立点或其他构造')
    def group(o):
        return (o['parents'][1],o.get('direction','counterclockwise'),o.get('angle'),o.get('degrees'))
    key=group(selected[0])
    family={o['id'] for o in objects if o['kind']=='rotation' and group(o)==key}
    if set(args['rotation_ids'])!=family:raise ValueError('必须选择原图同中心/同方向/同角度的完整旋转组，不能只移动一个对应顶点')
    variants=[]
    for angle in args['angles']:
        value=copy.deepcopy(spec)
        for o in value['tabs'][ti]['board']['objects']:
            if o['id'] in family:
                o.pop('angle',None);o['degrees']=angle
        variants.append((angle,strict_spec(value)))
    return spec,solution,step,rules,variants


def native_observe(spec,probes,directory,timeout):
    directory.mkdir(parents=True,exist_ok=True)
    write_json(directory/'request.json',{'spec':spec,'probes':probes})
    with subprocess.Popen([sys.executable,'-m','math_agent.scene_tools',str(directory)],cwd=ROOT,
                          stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True) as process:
        try:process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            # Kill only this new process group, including the Playwright browser.
            # No detached browser should survive a timed-out hypothesis query.
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            process.wait()
            return {'ok':False,'error':'旋转假设图观察超过本工具总时限，未作数学判断'}
        except BaseException:
            # Propagate cancellation, but first reap this hypothesis's children.
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            process.wait()
            raise
    path=directory/'observation.json'
    if process.returncode or not path.is_file():return {'ok':False,'error':'旋转假设图观察失败，未作数学判断'}
    return json.loads(path.read_text())


def evaluate(candidate,args,directory,observe=native_observe):
    spec,solution,step,rules,variants=prepare(candidate,args)
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=True)
    original=fingerprint(spec);start=time.monotonic()
    result={'ok':True,'kind':'hypothetical_rotation_rule','original_spec_sha256':original,
            'question_id':solution.question_id,'step_id':args['step_id'],'rule':rules[0],'request':copy.deepcopy(args),
            'observations':[],'counterexamples':[],'unobserved':[],
            'scope':'Agent选择的假设角度；不证明题设允许，也不替代对原证明及独立边界证明的判断。原候选不变。未见反例不等于证明正确。'}
    for i,(angle,variant) in enumerate(variants):
        remaining=15-(time.monotonic()-start)
        if remaining<=0:
            result['unobserved'].append({'angle':angle,'reason':'总15秒取证时限已用完'});continue
        observation=observe(variant,[{'tab':args['tab'],'checks':[{'relation':'collinear','points':ids} for ids in args['triangles']]}],directory/f'case-{i:02d}',remaining)
        meta={'question_id':solution.question_id,'tab':args['tab'],'step_id':args['step_id'],
              'angle_degrees':angle,'rotation_ids':args['rotation_ids'],'rationale':args['rationale'],
              'claim_clause':step.premise+'；'+step.rule+'；'+step.conclusion,
              'original_spec_sha256':original,'case_spec_sha256':fingerprint(variant),'observation':observation}
        result['observations'].append(meta)
        if not observation.get('ok'):
            result['unobserved'].append({'angle':angle,'reason':'原生观察没有成功，不能当作共线或数学通过'});continue
        for row in observation['probes']:
            for check in row['checks']:
                if check.get('holds') is not True:continue
                result['counterexamples'].append({'kind':'proof_guard','tab':args['tab'],'parameter':None,
                    'check':{'relation':'collinear','points':check['points'],'expected':False,'holds':True,
                             'matches_expected':False,'observed':check['observed']},
                    'basis_ids':[args['step_id']],'rule':rules[0],'case_evidence':copy.deepcopy(meta),
                    'detail':'Agent指定的同中心旋转假设中，该步骤所用三角形共线。须独立核对原题是否允许这一角度、该定理是否需要非退化及作者是否另证；不能直接要求修改默认图，不能仅因目标等式成立就解除异议。'})
    result['ok']=not result['unobserved']
    result['seconds']=round(time.monotonic()-start,3)
    write_json(directory/'result.json',result)
    return result
