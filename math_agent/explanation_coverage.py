"""Visible point references in an explanation; never infer or change geometry.

Recognizes explicit point wording, coordinate declarations and named geometric
entities. This is a bounded presentation check, not a prose proof verifier.
"""
import re
from .jsxgraph.spec import POINTS
from .rendering import RenderError
from .point_names import NAME,normalize as normalized


class CoverageError(RenderError):
    def __init__(self,issues):
        self.issues=issues
        super().__init__('讲解点名展示不完整：'+'；'.join(i['detail'] for i in issues))


def require(candidate):
    issues=[]
    for solution,tab in zip(candidate.solutions,candidate.spec['tabs']):
        issues.extend(collect(solution,tab['board']))
    if issues:raise CoverageError(issues)

COORD=re.compile(r"(?<![A-Za-z0-9_])("+NAME+r")\s*[（(][^()（）\n]{1,90}[,，][^()（）\n]{1,90}[)）]")
EXPLICIT=re.compile(r"(?:点|取点|设点|作点)\s*("+NAME+r")(?![A-Za-z0-9_])")
ENTITY=re.compile(r"(?:△|∠|线段|直线|连接|连结|边)\s*((?:"+NAME+r"){2,3})(?![A-Za-z0-9_])")


def collect(solution,board):
    objects=board.get('objects',[])
    registry={}
    for obj in objects:
        if obj.get('kind') not in POINTS:continue
        for alias in {obj.get('id',''),obj.get('label','')}:
            if re.fullmatch(NAME,alias):registry.setdefault(normalized(alias),{})[obj['id']]=obj
    text='\n'.join(s.premise+'\n'+s.rule+'\n'+s.conclusion for s in solution.steps)
    # Cases can describe alternative figures; do not force their hypothetical
    # points into the default scene. Their coverage still needs independent review.
    refs={}
    for match in EXPLICIT.finditer(text):refs.setdefault(normalized(match[1]),match.group())
    for match in ENTITY.finditer(text):
        for name in re.findall(NAME,match[1]):refs.setdefault(normalized(name),match.group())
    for match in COORD.finditer(text):
        name=normalized(match[1])
        # Bare F(x,y) may be a function. Only bind it to an already declared
        # native point; explicit "point F" above also detects a missing point.
        if name in registry:refs.setdefault(name,match.group())
    issues=[]
    for name,quote in refs.items():
        matches=list(registry.get(name,{}).values())
        if not matches:
            detail=f'讲解明确引用点{name}（{quote}），画板没有同名原生点；请核对并补正确构造，不得改写证明来删掉该点'
        elif len(matches)!=1:
            detail=f'点名{name}对应多个原生点，无法唯一找到讲解中的点；请明确标签，不能猜测绑定'
        else:
            obj=matches[0];display=normalized(obj.get('label') or obj['id'])
            shown_names={normalized(n) for n in re.findall(NAME,display)}
            if obj.get('visible',True) and name in shown_names:continue
            detail=f'讲解引用点{name}（{quote}），但对象{obj["id"]}隐藏或没有显示对应点名；请显示该点并标明{name}，保持坐标、构造和证明不变，视野须容纳该点'
        issues.append({'stage':'diagram','question_id':solution.question_id,'path':'board',
            'code':'explanation_point_coverage','point_name':name,'evidence':quote,'detail':detail})
    return issues
