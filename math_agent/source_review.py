"""Independent rereading with explicit, auditable resolution of each prior doubt."""
from typing import Literal
from pydantic import Field
from .contracts import Strict, Source, check_source, exact_ids
from .text_evidence import quote_in_text


class Citation(Strict):
    condition_id: str
    quote: str = Field(min_length=1, max_length=2000)


class Decision(Strict):
    issue_id: str
    evidence_ids: list[str] = Field(default_factory=list, max_length=20, description="推荐：引用已核对的文字条件编号，服务端检查其原文quote；无需重写引文，旧字段留空")
    verdict: Literal['resolved_by_text', 'unresolved']
    condition_ids: list[str] = Field(default_factory=list, max_length=20)
    quote: str = Field(default="", max_length=2000)
    citations: list[Citation] = Field(default_factory=list, max_length=20)
    reason: str = Field(min_length=1, max_length=3000)


class SourceReview(Strict):
    source: Source
    decisions: list[Decision] = Field(max_length=30)


def check_reread(raw, issues, images):
    value = SourceReview.model_validate(raw)
    check_source(value.source, images)
    exact_ids([d.issue_id for d in value.decisions], [i['id'] for i in issues], '读题疑问核对')
    conditions = {c.id:c for c in value.source.conditions}
    for decision in value.decisions:
        if decision.verdict == 'unresolved': continue
        if decision.evidence_ids:
            if decision.citations or decision.quote or decision.condition_ids:
                raise ValueError(f'{decision.issue_id}: evidence_ids引用模式不能混用其他引文模式')
            for cid in decision.evidence_ids:
                condition=conditions.get(cid)
                if condition is None or condition.origin!='question_text':
                    raise ValueError(f'{decision.issue_id}/{cid}: 必须引用存在的文字条件')
                quote=condition.quote or condition.text.rstrip('。；，.,;')
                if not quote_in_text(quote,value.source.problem_text):
                    raise ValueError(f'{decision.issue_id}/{cid}: 条件释义不是原文，须在该条件quote中提供题干的逐字摘录')
            continue
        if decision.citations:
            if decision.quote or decision.condition_ids:
                raise ValueError(f'{decision.issue_id}: citations与旧quote/condition_ids不能混用；每条引文单独绑定一个条件')
            for citation in decision.citations:
                condition=conditions.get(citation.condition_id)
                quote=citation.quote
                if condition is None or condition.origin!='question_text':
                    raise ValueError(f'{decision.issue_id}/{citation.condition_id}: 引文必须引用已存在的文字题设')
                if not quote_in_text(quote,value.source.problem_text) or not quote_in_text(quote,condition.quote or condition.text):
                    raise ValueError(f'{decision.issue_id}/{citation.condition_id}: 引文须同时逐字出现在题干和此条件中，不可跨条件拼接')
            continue
        quote = decision.quote
        if not decision.condition_ids or not quote_in_text(quote,value.source.problem_text):
            raise ValueError('解除疑问必须引用原题转写中的明确文字及条件编号')
        for cid in decision.condition_ids:
            condition = conditions.get(cid)
            if condition is None:
                raise ValueError('解除疑问不能引用未知条件')
        if not any(conditions[cid].origin == 'question_text' and quote_in_text(quote,conditions[cid].quote or conditions[cid].text) for cid in decision.condition_ids):
            raise ValueError('解除疑问的引用文字必须出现在所引用的题设条件中')
    return value


def apply_reread(value, issues):
    source = value.source.model_copy(deep=True)
    by_id = {i['id']:i['text'] for i in issues}
    for decision in value.decisions:
        if decision.verdict == 'unresolved' and by_id[decision.issue_id] not in source.uncertainties:
            source.uncertainties.append(by_id[decision.issue_id])
    return source
