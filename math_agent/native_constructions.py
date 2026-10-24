"""Check Agent-declared, source-bound native construction obligations.

No prose inference, coordinate calculation, object substitution or math approval.
The reading Agent chooses relations; independent review still checks their truth
and completeness against original pixels. This gate checks the chosen bindings.
"""
import copy
import re
from .point_names import normalize
from .jsxgraph.spec import POINTS,CURVES
from .rendering import RenderError
from .text_evidence import quote_in_text


INSTRUCTION='''额外记录native_constructions（没有适用项时为[]）。只提取原题文字明确引入的新派生点：平移像、旋转像、交点、中点、垂足、对称像。原本已给定的基本点或为建立坐标系选取的基本点，不重复列为新构造；原始函数坐标轴截距可作为已解出的基本坐标点。旋转后某顶点与原本已给定点重合时，不把原本点强行改成旋转点造成循环，只列新像点。
每项为{id:N编号,question_ids:实际Q号,point:原文新点名,kind:原生构造类型,parents:原文父对象名,condition_ids:文字条件C编号,quote:含该派生点的连续原文}。这只是读题结果，不能引入答案辅助点或自行推导数值。平移后的图像顶点以原顶点为translation父点；曲线交点以两曲线名为intersection父对象；直线可用端点名AB，已命名函数曲线用y₁/y₂等原文名字。rotation父对象顺序为原像点、中心；reflection/perpendicularpoint为原像点、直线。quote须同时出现在problem_text与引用的文字条件中，适用小问按原条件限定。必要时把该构造涉及的连续文字作为一条完整条件，不能为了引用把答案写进题干。所有原文明示的新派生点都应覆盖，不确定仍保留uncertainties，不猜坐标。
题设用两条曲线相交、垂足或中点定义的点不是自由基点，即使已画在初始图中、或准备把它选作坐标原点，也须记录intersection、perpendicularpoint或midpoint；不能因后续会解方程算出坐标而省略两曲线交点。曲线没有符号名称时，可用原文唯一角色名作parents（如“所求中心对称函数”“反比例函数”），由解题Agent按相同名称标注真实原生曲线，不在读题阶段推导解析式。若后续题明确沿用同一图形和定义，把相应构造及其依据条件的question_ids也覆盖这些后续问；若后续改变了条件或重定义同名点，不可盲目继承，须按原文重新限定。'''


def require_output(raw,enabled):
    if enabled and (not isinstance(raw,dict) or 'native_constructions' not in raw):
        raise ValueError('本轮读题须明确返回native_constructions，不能省略构造关系清单；确无适用项才[]')


def validate_source(source):
    ids=set();bindings=set();conditions={c.id:c for c in source.conditions};questions={q.id for q in source.questions}
    for item in source.native_constructions:
        if item.id in ids:raise ValueError('原生构造编号重复：'+item.id)
        ids.add(item.id)
        if len(set(item.question_ids))!=len(item.question_ids) or not set(item.question_ids)<=questions:
            raise ValueError(item.id+'构造适用小问未知或重复')
        if len(item.parents)!=(1 if item.kind=='translation' else 2):raise ValueError(item.id+'父对象数量与原生类型不符')
        if len(set(item.condition_ids))!=len(item.condition_ids) or not set(item.condition_ids)<=set(conditions):
            raise ValueError(item.id+'必须引用现有且不重复的文字条件')
        cited=[conditions[c] for c in item.condition_ids]
        if not quote_in_text(item.quote,source.problem_text) or not any(c.origin=='question_text' and quote_in_text(item.quote,c.quote or c.text) for c in cited):
            raise ValueError(item.id+'构造引文须同时出现在题干和引用的文字条件中，不得用答案或图示外观替代')
        if normalize(item.point) not in normalize(item.quote):raise ValueError(item.id+'引文没有声明此派生点名')
        for qid in item.question_ids:
            if any(c.question_ids and qid not in c.question_ids for c in cited):
                raise ValueError(item.id+'使用了不适用于'+qid+'的局部条件')
            key=(qid,normalize(item.point))
            if key in bindings:raise ValueError(item.id+'同一小问的派生点构造重复或冲突')
            bindings.add(key)


def _aliases(obj):
    return {normalize(n) for n in [obj.get('id',''),obj.get('label',''),*obj.get('source_names',[])]}-{''}


def resolve(objects,name,kinds):
    """Resolve declared names only, including a line's explicit endpoint pair."""
    wanted=normalize(name);found={}
    for obj in objects:
        if obj['kind'] not in kinds:continue
        aliases=_aliases(obj)
        if wanted in aliases or obj['kind']=='functiongraph' and any(a.startswith(wanted+'=') for a in aliases):
            found[obj['id']]=obj
    if kinds==CURVES:
        names=re.findall(r'[A-Z](?:[0-9′])*',wanted)
        if len(names)==2 and ''.join(names)==wanted:
            endpoints=[resolve(objects,n,POINTS) for n in names]
            if all(len(e)==1 for e in endpoints):
                expected={e[0]['id'] for e in endpoints}
                for obj in objects:
                    if obj['kind'] in {'line','segment'} and set(obj.get('parents',[]))==expected:
                        found[obj['id']]=obj
    return list(found.values())


def collect(source,solution,board):
    objects=board.get('objects',[]);issues=[]
    for item in source.native_constructions:
        if solution.question_id not in item.question_ids:continue
        targets=resolve(objects,item.point,POINTS)
        detail=None
        if len(targets)!=1:detail='没有唯一同名原生点'
        else:
            obj=targets[0]
            if not obj.get('visible',True) or normalize(obj.get('label') or obj['id'])!=normalize(item.point):
                detail='派生点隐藏或标签不对应原文点名'
            elif obj['kind']!=item.kind:detail=f"实际kind={obj['kind']}，须为{item.kind}，不能以固定point.coords替代派生构造"
            else:
                expected=[]
                kinds=([CURVES,CURVES] if item.kind=='intersection' else
                       [POINTS,CURVES] if item.kind in {'reflection','perpendicularpoint'} else [POINTS]*len(item.parents))
                for name,allowed in zip(item.parents,kinds):
                    matches=resolve(objects,name,allowed)
                    # A line and its visible segment may describe the same
                    # endpoints; both are legitimate native curve parents.
                    if len(matches)>1 and not (all(m['kind'] in {'line','segment'} for m in matches) and
                         len({tuple(sorted(m['parents'])) for m in matches})==1):
                        matches=[]
                    expected.append({m['id'] for m in matches})
                actual=obj.get('parents',[])
                normal=len(actual)==len(expected) and all(a in choices for a,choices in zip(actual,expected))
                reverse=(item.kind in {'intersection','midpoint'} and len(actual)==2 and
                         all(a in choices for a,choices in zip(reversed(actual),expected)))
                if not (normal or reverse):detail=f"父对象{actual}没有绑定原文父对象{item.parents}；在正确父对象的source_names数组逐字填写对应原文名称（不显示），label可保留简洁公式；不要因名称未绑定而重算坐标、换曲线或更换题意"
        if detail:
            issues.append({'stage':'diagram','question_id':solution.question_id,'path':'board','code':'native_construction',
                'requirement_id':item.id,'point_name':item.point,'evidence':item.quote,
                'detail':f'{item.id}点{item.point}：{detail}；原文依据“{item.quote}”，保持全部证明不变'})
    return issues


class ConstructionError(RenderError):
    def __init__(self,issues):
        self.issues=issues
        super().__init__('原生构造关系不符：'+'；'.join(i['detail'] for i in issues))


def require(source,candidate):
    issues=[]
    for solution,tab in zip(candidate.solutions,candidate.spec['tabs']):issues.extend(collect(source,solution,tab['board']))
    if issues:raise ConstructionError(issues)


def bind_output_schema(schema,source):
    """One question-specific contract, driven by reading Agent obligations.

    This constrains types/names, not coordinates or mathematical correctness.
    Parents are checked by collect after the model chooses actual native IDs.
    """
    for index,q in enumerate(source['questions']):
        requirements=[r for r in source.get('native_constructions',[]) if q['id'] in r['question_ids']]
        if not requirements:continue
        definitions=schema['$defs'];board=copy.deepcopy(definitions['Board'])
        objects=board['properties']['objects'];item=objects['items']
        for requirement in requirements:
            name=requirement['point'];spellings=sorted({name,normalize(name),normalize(name).replace('′',"'")})
            named={'anyOf':[{'properties':{field:{'enum':spellings}},'required':[field]} for field in ['id','label']]}
            kind={'properties':{'kind':{'const':requirement['kind']}},'required':['kind']}
            item.setdefault('allOf',[]).append({'if':named,'then':kind})
            objects.setdefault('allOf',[]).append({'contains':{'allOf':[named,kind]}})
            parent_kinds=([CURVES,CURVES] if requirement['kind']=='intersection' else
                          [POINTS,CURVES] if requirement['kind'] in {'reflection','perpendicularpoint'} else
                          [POINTS]*len(requirement['parents']))
            for parent,allowed in zip(requirement['parents'],parent_kinds):
                if allowed!=CURVES:continue
                spellings=sorted({parent,normalize(parent),normalize(parent).replace('′',"'")})
                binding={'anyOf':[
                    *[{'properties':{field:{'enum':spellings}},'required':[field]} for field in ['id','label']],
                    {'properties':{'source_names':{'contains':{'enum':spellings}}},'required':['source_names']}]}
                rule={'contains':{'allOf':[{'properties':{'kind':{'enum':sorted(CURVES)}},'required':['kind']},binding]}}
                if rule not in objects['allOf']:objects['allOf'].append(rule)
        board_name=f'NativeBoard_{index}';answer_name=f'NativeAnswer_{index}'
        definitions[board_name]=board
        answer=copy.deepcopy(definitions['CompactAnswer'])
        answer['properties']['board']={'$ref':'#/$defs/'+board_name}
        definitions[answer_name]=answer
        schema['properties'][q['id']]={'$ref':'#/$defs/'+answer_name}
    return schema
