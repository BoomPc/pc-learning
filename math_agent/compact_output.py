"""Question-keyed solver output; display text derives from the authoritative proof."""
import copy
import json
import re
from pydantic import create_model
from .contracts import Strict, Solution, Candidate
from .jsxgraph.spec import Board, Controls

Proof = create_model('CompactProof', __base__=Strict, **{
    name: (field.annotation, copy.deepcopy(field))
    for name, field in Solution.model_fields.items() if name != 'question_id'})
class Answer(Strict):
    proof: Proof
    board: Board
    controls: Controls | None = None


def native_schema(schema,source=None):
    """Clear model-facing format; runtime still reads valid legacy saved data."""
    schema=copy.deepcopy(schema)
    for item in schema.get('$defs',{}).values():
        props=item.get('properties',{})
        if 'view' in props and 'bounding_box' in props:
            props.pop('bounding_box')
        if source is not None and 'condition_ids' in props:
            props['condition_ids']['items']={'type':'string','enum':[c['id'] for c in source['conditions']]}
    return schema

def output_schema(source,require_basis=False,completed_steps=None):
    item = Answer.model_json_schema()
    defs = item.pop('$defs', {})
    if require_basis:
        step=defs['Step'];step['properties']['basis_ids'].pop('default',None)
        step['properties']['basis_ids']['minItems']=1
        if 'basis_ids' not in step['required']:step['required'].append('basis_ids')
    defs['CompactAnswer'] = item
    ids = [q['id'] for q in source['questions']]
    from .native_constructions import bind_output_schema
    schema=bind_output_schema(native_schema({'type':'object', 'additionalProperties':False, 'required':ids,
        'properties':{qid:{'$ref':'#/$defs/CompactAnswer'} for qid in ids}, '$defs':defs},source),source)
    if require_basis:
        for index,qid in enumerate(ids):
            allowed=[c['id'] for c in source['conditions'] if not c.get('question_ids') or qid in c['question_ids']]
            completed=list(completed_steps or [])
            own='|'.join(re.escape(q) for q in ids[:index+1])
            references=[{'type':'string','pattern':r'^(?:'+own+r'):S(?:[1-9]|[1-3][0-9]|40)$'}]
            if allowed or completed:references.append({'type':'string','enum':list(dict.fromkeys(allowed+completed))})
            # DeepSeek rejects allOf-only/property-only overlays even though
            # they are valid JSON Schema. Specialize explicit typed $defs.
            definitions=schema['$defs']
            answer=copy.deepcopy(definitions[schema['properties'][qid]['$ref'].rsplit('/',1)[1]])
            proof=copy.deepcopy(definitions['CompactProof']);step=copy.deepcopy(definitions['Step'])
            condition_ids=proof['properties']['condition_ids']
            condition_ids['items']={'type':'string',**({'enum':allowed} if allowed else {})}
            if not allowed:condition_ids['maxItems']=0
            step['properties']['basis_ids']['items']={'anyOf':references}
            step_name=f'ScopedStep_{index}';proof_name=f'ScopedProof_{index}';answer_name=f'ScopedAnswer_{index}'
            definitions[step_name]=step
            proof['properties']['steps']['items']={'$ref':'#/$defs/'+step_name};definitions[proof_name]=proof
            answer['properties']['proof']={'$ref':'#/$defs/'+proof_name};definitions[answer_name]=answer
            schema['properties'][qid]={'$ref':'#/$defs/'+answer_name}
    return schema

def unpack(raw, source):
    ids = [q.id for q in source.questions]
    if not isinstance(raw, dict) or set(raw) != set(ids):
        raise ValueError('必须仅包含每个小问一次：' + ','.join(ids))
    solutions=[]; tabs=[]
    issues=[]
    for qid in ids:
        try:answer=Answer.model_validate(raw[qid])
        except ValueError as exc:
            for error in exc.errors():
                path='.'.join(str(v) for v in error['loc'])
                issues.append({'stage':'math' if path.startswith('proof') else 'diagram','question_id':qid,
                    'path':path or 'board','detail':error['msg'],'actual':repr(error.get('input'))[:1000]})
            continue
        solutions.append(Solution(question_id=qid, **answer.proof.model_dump()))
        tab={'tab_title':qid, 'board':answer.board.model_dump(exclude_none=True)}
        if answer.controls is not None: tab['controls']=answer.controls.model_dump(exclude_none=True)
        tabs.append(tab)
    if issues:
        from .submission import SubmissionError
        raise SubmissionError(issues)
    return Candidate(solutions=solutions, spec={'format':'jsxgraph-v1', 'title':source.title,
        'problem_text':source.problem_text, 'tabs':tabs})


def pack(candidate):
    """Retain proofs/boards for the shared submission gate; no mathematical edits."""
    return {solution.question_id:{'proof':solution.model_dump(exclude={'question_id'}),
                'board':copy.deepcopy(tab['board']),
                **({'controls':copy.deepcopy(tab['controls'])} if 'controls' in tab else {})}
            for solution,tab in zip(candidate.solutions,candidate.spec['tabs'])}

def unique_object(pairs):
    result={}
    for key,value in pairs:
        if key in result: raise ValueError('JSON对象重复键：'+key)
        result[key]=value
    return result
