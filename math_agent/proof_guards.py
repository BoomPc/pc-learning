"""Local counterexamples to explicitly reused triangle rules in coincidence cases.

This recognizes a bounded syntax, not arbitrary mathematical prose. A hypothetical
case is not assumed admissible: disagreements go to the existing independent gate.
"""
import copy,re
from .jsxgraph.spec import POINTS
from .scene_tools import fingerprint,probe_scene
from .rendering import strict_spec

POINT=r"[A-Z](?:[0-9]|[′'])*"
COINCIDENCE=re.compile(r'当\s*(?:点\s*)?('+POINT+r')\s*[与和]\s*(?:点\s*)?('+POINT+r')\s*重合时|(?<![A-Za-z0-9′\'])(?:当\s*)?(?:点\s*)?('+POINT+r')\s*[=＝]\s*('+POINT+r')\s*时')
TRIANGLE=re.compile(r'△('+POINT+r')('+POINT+r')('+POINT+r')')
RULES={
 'midsegment':('中位线',re.compile('中位线')),
 'congruence':('全等',re.compile(r'全等|\b(?:SAS|SSS|ASA|AAS|HL)\b')),
 'similarity':('相似',re.compile('相似')),
}


def _resolve_label(name,objects):
    candidates=[o['id'] for o in objects if o['kind'] in POINTS and
        (o['id']==name or o.get('label','').replace("'",'′')==name.replace("'",'′'))]
    return candidates[0] if len(set(candidates))==1 else None


def _alias_case(spec,tab,point,anchor):
    value=copy.deepcopy(spec);objects=value['tabs'][tab]['board']['objects'];by_id={o['id']:o for o in objects}
    # Do not discard a declared rotation/intersection to manufacture a counterexample.
    if by_id[point]['kind'] not in {'point','glider'}:raise ValueError('假设替换仅支持自由点或路径动点，不覆盖已声明派生构造')
    def depends(name,visited=None):
        if name==point:return True
        seen=set() if visited is None else visited
        if name in seen:return False
        seen.add(name)
        return any(depends(n,seen) for n in by_id[name].get('parents',[]))
    if depends(anchor):raise ValueError('重合目标依赖被替换点，不能构造循环或冻结旧坐标')
    old=by_id[point]
    replacement={k:v for k,v in old.items() if k in {'id','label','color','visible','dashed'}}
    replacement.update(kind='translation',parents=[anchor],vector=[0.,0.])
    objects[objects.index(old)]=replacement
    return strict_spec(value)


def collect(source,candidate,directory,observe=probe_scene):
    result={'failures':[],'observations':[], 'unobserved':[],
        'scope':'仅检查明确声明重合情形且明确沿用三角形定理的非退化前提。变体是假设，不是默认图或原题允许性证明；没有发现反例不等于证明正确。'}
    directory=directory.resolve()
    original=fingerprint(strict_spec(candidate.spec))
    attempts=0
    for ti,solution in enumerate(candidate.solutions):
        objects=candidate.spec['tabs'][ti]['board']['objects']
        rules=[]
        for si,step in enumerate(solution.steps,1):
            text=step.premise+' '+step.conclusion
            triangles=[]
            for match in TRIANGLE.finditer(text):
                ids=[_resolve_label(n,objects) for n in match.groups()]
                if all(ids) and ids not in triangles:triangles.append(ids)
            for rule,(word,pattern) in RULES.items():
                if pattern.search(step.rule) and triangles:rules.append((f'{solution.question_id}:S{si}',rule,word,triangles))
        for ci,case in enumerate(solution.cases):
            for match in COINCIDENCE.finditer(case):
                # Scope reuse to this clause; a different endpoint's proof is separate.
                clause=re.split(r'[;；。]',case[match.start():],maxsplit=1)[0]
                reused=[]
                for item in rules:
                    word=item[2]
                    if (word in clause and re.search(r'同一|同样|上述|仍按|仍用',clause)
                        and not re.search(r'不能|不可|不再|不适用|不成立|失效',clause)):
                        reused.append(item)
                if not reused:continue
                names=match.groups()[:2] if match.group(1) else match.groups()[2:]
                point,anchor=[_resolve_label(n,objects) for n in names]
                meta={'question_id':solution.question_id,'tab':ti,'case_index':ci,'case_text':case,
                    'case_span':match.group(),'claim_clause':clause,'original_spec_sha256':original}
                if not point or not anchor or point==anchor:
                    result['unobserved'].append({**meta,'reason':'点名不能唯一绑定到当前图中不同点'});continue
                triangles=[]
                for step,rule,word,items in reused:
                    for ids in items:
                        if ids not in triangles:triangles.append(ids)
                if attempts>=8:
                    result['unobserved'].append({**meta,'reason':'本地反例观察最多8种情形；其余未观察，不能据此称为通过'});continue
                attempts+=1
                if len(triangles)>12:
                    result['unobserved'].append({**meta,'reason':'本情形超过12个三角形；超出部分未观察'})
                    triangles=triangles[:12]
                try:
                    variant=_alias_case(candidate.spec,ti,point,anchor)
                    observation=observe(variant,[{'tab':ti,'checks':[{'relation':'collinear','points':ids} for ids in triangles]}],
                        directory/f'tab-{ti:02d}-case-{ci:02d}-{match.start():03d}')
                    meta.update({'assignment':{'point':point,'anchor':anchor},
                        'case_spec_sha256':fingerprint(variant),'observation':observation})
                    result['observations'].append(meta)
                    if not observation.get('ok'):raise ValueError('假设图观察失败，不能当作退化反例')
                    row=observation['probes'][0]
                    for check in row['checks']:
                        if check.get('holds') is not True:continue
                        for step,rule,word,items in reused:
                            if check['points'] not in items:continue
                            result['failures'].append({'kind':'proof_guard','tab':ti,'parameter':row.get('parameter'),
                                'check':{'relation':'collinear','points':check['points'],'expected':False,
                                    'holds':True,'matches_expected':False,'observed':check['observed']},
                                'basis_ids':[step],'rule':rule,'case_evidence':copy.deepcopy(meta),
                                'detail':f'作者在此重合情形明确沿用{word}，但相应三角形三点共线。须核对该情形是否允许、是否另有独立证明；不能只因默认图正常或结论数值正确而放行。'})
                except (ValueError,KeyError) as exc:
                    result['unobserved'].append({**meta,'reason':str(exc)[:500]})
    return result
