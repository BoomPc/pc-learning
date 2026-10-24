"""Collect known submission defects; restrict corrections to their original scope."""
import copy
import json
from .contracts import candidate_issues


class SubmissionError(ValueError):
    def __init__(self,issues,candidate=None):
        self.issues=issues
        self.candidate=candidate
        super().__init__(json.dumps({'issues':issues,'scope':'本地契约检查，不是数学正确性复核；上游无效时后续检查可能尚未执行'},ensure_ascii=False))


def receive(provider,stage,prompt,audit,**kwargs):
    """Keep transport failure separate from complete but untrusted final JSON.

    Every caller must still parse/validate this value through its existing stage
    gate. No fields are repaired here, and no further request is made here.
    """
    from .provider import CompletedSchemaError
    try:return provider.generate(stage,prompt,**kwargs)
    except CompletedSchemaError as exc:
        audit('schema_candidate',{'stage':stage,'path':exc.path[:12],
            'detail':'完整JSON不符合模型面向Schema；按原样交本阶段严格本地契约检查及原有限次纠正，未视为通过、未重发HTTP或切换接口'})
        return copy.deepcopy(exc.value)


def decode(raw,source,audit=None,require_basis=False,dependency_plan=None):
    from .compact_output import unpack
    from .pipeline import canonical_page
    candidate=canonical_page(unpack(raw,source),source,audit)
    issues=inspect(candidate,source,require_basis=require_basis,dependency_plan=dependency_plan)
    if issues:raise SubmissionError(issues,candidate)
    return candidate


def inspect(candidate,source,require_basis=False,dependency_plan=None):
    from .rendering import strict_spec
    issues=candidate_issues(candidate,source)
    if dependency_plan is not None:
        from .question_plan import collect_basis_issues
        issues.extend(collect_basis_issues(source,dependency_plan,candidate.solutions,require_nonempty=require_basis))
    elif require_basis:issues.extend(basis_issues(candidate))
    for solution,tab in zip(candidate.solutions,candidate.spec['tabs']):
        try:strict_spec({**candidate.spec,'tabs':[tab]})
        except (ValueError,SyntaxError) as exc:
            issues.append({'stage':'diagram','question_id':solution.question_id,'path':'board',
                'detail':str(exc)[:4000],'followup':'本画板后续检查可能未执行；修正后必须重新完整校验'})
        else:
            from .explanation_coverage import collect
            issues.extend(collect(solution,tab['board']))
            from .native_constructions import collect as constructions
            issues.extend(constructions(source,solution,tab['board']))
    return issues


def basis_issues(candidate):
    return [{'stage':'math','question_id':solution.question_id,
             'path':f'proof.steps.{index}.basis_ids','code':'missing_basis',
             'detail':f'{solution.question_id}:S{index+1}缺少依据，不能确认依赖范围；补适用的原C编号或已完成前置步骤Qn:Sm，不能引用目标Q或给无关依据充数；真实未知须保留'}
            for solution in candidate.solutions for index,step in enumerate(solution.steps) if not step.basis_ids]


def require_basis(candidate):
    issues=basis_issues(candidate)
    if issues:raise SubmissionError(issues,candidate)


def allowed_fields(issues):
    result={}
    for item in issues:
        qid=item.get('question_id');field=item.get('path','').split('.')[0]
        if not qid or field not in {'proof','board','controls'}:
            raise ValueError('不能唯一绑定局部纠错范围，不能猜测修改其它小问')
        result.setdefault(qid,set()).add(field)
    return result


def basis_steps(issues,qid):
    proof=[i for i in issues if i.get('question_id')==qid and i.get('path','').startswith('proof')]
    if not proof or any(i.get('code')!='missing_basis' for i in proof):return {}
    return {f'S{int(i["path"].split(".")[2])+1}':int(i['path'].split('.')[2]) for i in proof}


def patch_schema(issues,source=None,require_basis=False):
    from .compact_output import Answer,native_schema
    item=Answer.model_json_schema();defs=item.pop('$defs',{})
    props={}
    for qid,fields in allowed_fields(issues).items():
        rows={field:item['properties'][field] for field in sorted(fields)}
        missing=basis_steps(issues,qid)
        if missing:
            rows.pop('proof')
            rows['step_basis']={'type':'object','additionalProperties':False,'required':list(missing),
                'description':'只补所列步骤的依据；数学正文、其余依据和画板均由服务器逐字保留',
                'properties':{sid:{'type':'array','minItems':1,'maxItems':30,'uniqueItems':True,
                                   'items':{'type':'string','minLength':1,'maxLength':40}} for sid in missing}}
        props[qid]={'type':'object','additionalProperties':False,'minProperties':1,
            'required':sorted(rows),'properties':rows}
    result=native_schema({'type':'object','additionalProperties':False,'required':['updates'],'$defs':defs,
        'properties':{'updates':{'type':'object','additionalProperties':False,'minProperties':1,
                                'required':list(props),'properties':props}}},source)
    if require_basis or any(i.get('code')=='missing_basis' for i in issues):
        step=result['$defs']['Step'];step['properties']['basis_ids'].pop('default',None)
        step['properties']['basis_ids']['minItems']=1
        if 'basis_ids' not in step['required']:step['required'].append('basis_ids')
    return result


def apply_patch(raw,previous,issues):
    allowed=allowed_fields(issues)
    if not isinstance(raw,dict) or set(raw)!={'updates'} or not isinstance(raw['updates'],dict) or not raw['updates']:
        raise ValueError('局部输出只能为非空updates对象')
    result=copy.deepcopy(previous)
    for qid,update in raw['updates'].items():
        missing=basis_steps(issues,qid)
        fields=(allowed.get(qid,set())-{'proof'}|{'step_basis'}) if missing else allowed.get(qid,set())
        if qid not in allowed or qid not in result or not isinstance(update,dict) or not update or not set(update)<=fields:
            raise ValueError('局部纠错不能改无关小问、题设或未授权字段')
        for field,value in update.items():
            if field=='step_basis':
                if not isinstance(value,dict) or set(value)!=set(missing):raise ValueError('只能补完整的已报告缺失步骤依据，不能改其它步骤')
                for sid,ids in value.items():
                    if not isinstance(ids,list) or not 1<=len(ids)<=30 or any(not isinstance(v,str) or not 1<=len(v)<=40 for v in ids) or len(set(ids))!=len(ids):
                        raise ValueError('步骤依据须为非空、无重复的编号数组')
                    result[qid]['proof']['steps'][missing[sid]]['basis_ids']=copy.deepcopy(ids)
            elif field=='controls' and value is None:result[qid].pop(field,None)
            else:result[qid][field]=copy.deepcopy(value)
    return result
