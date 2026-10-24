"""Independent decisions plus explicit question updates; preserve all unrelated checks."""
from typing import Literal
from pydantic import Field
from .contracts import Strict,Check,TextualDecision,AssertionDecision,Adjudication,exact_ids

class CompactAdjudication(Strict):
    verdict: Literal['pass','revise','needs_input']
    decisions: list[TextualDecision | AssertionDecision] = Field(min_length=1,max_length=100)
    question_updates: list[Check] = Field(default_factory=list,max_length=12)

def unpack(raw,original):
    value=CompactAdjudication.model_validate(raw)
    updated=original.model_copy(deep=True)
    exact_ids([q.id for q in value.question_updates],[q.id for q in value.question_updates],'裁决小问更新')
    indices={q.id:i for i,q in enumerate(updated.questions)}
    scoped={scope.question_id for d in value.decisions if isinstance(d,TextualDecision) for scope in d.scopes}
    scoped.update(d.question_id for d in value.decisions if isinstance(d,AssertionDecision) and d.question_id is not None)
    for question in value.question_updates:
        if question.id not in indices or question.id not in scoped:raise ValueError('裁决只能更新本次明确作用域内的小问')
        updated.questions[indices[question.id]]=question
    updated.verdict=value.verdict
    updated.issues=[i for i in original.issues if i.stage!='diagram']
    updated.issues.extend(d.issue for d in value.decisions if d.verdict=='real_issue' and d.issue is not None)
    return Adjudication(decisions=value.decisions,reviewed=updated)
