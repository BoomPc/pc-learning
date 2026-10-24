"""Question-level mathematical amendments; unaffected proofs stay byte-for-byte data equal."""
from pydantic import Field
from .contracts import Strict,Solution
from .compact_output import Proof

class ProofUpdate(Strict):
    reason: str = Field(min_length=20,max_length=3000)
    proof: Proof

class MathPatch(Strict):
    updates: dict[str,ProofUpdate] = Field(min_length=1,max_length=12)


def output_schema(source):
    schema=MathPatch.model_json_schema()
    schema['properties']['updates']={'type':'object','minProperties':1,'additionalProperties':False,
        'properties':{q['id']:{'$ref':'#/$defs/ProofUpdate'} for q in source['questions']}}
    return schema


def apply(raw,previous,source):
    patch=MathPatch.model_validate(raw)
    ids={s.question_id for s in previous.solutions}
    if not set(patch.updates)<=ids:raise ValueError('数学局部修订包含不存在的小问')
    candidate=previous.model_copy(deep=True)
    for i,old in enumerate(candidate.solutions):
        if old.question_id in patch.updates:
            candidate.solutions[i]=Solution(question_id=old.question_id,**patch.updates[old.question_id].proof.model_dump())
    return candidate,patch
