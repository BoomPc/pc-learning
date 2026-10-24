"""Bind model comparisons to literal candidate passages; not a proof checker.

All normal proof/source/diagram review remains required. Every proof/result/case
and boundary has an immutable original. Reviewers echo it for comparison; only
an OMITTED copy of this known metadata may be bound locally, never a judgment,
evidence, issue or an explicitly different quotation. These records
cannot decide that a model's 'pass' is mathematically true.
"""
import copy
from .compact_review import PassageReview,FlatReview,ReviewShapeError
from .contracts import exact_ids


def passages(candidate,ids):
    result=[]
    for solution in candidate.solutions:
        qid=solution.question_id
        if qid not in ids:continue
        fields=[('result',solution.result)]+[(f'step:{i}',step.premise+'\n'+step.rule+'\n'+step.conclusion)
            for i,step in enumerate(solution.steps,1)]+[('domain',solution.domain_and_boundaries)]+[(f'case:{i}',text) for i,text in enumerate(solution.cases,1)]
        for field,text in fields:
            result.append({'id':qid+':'+field,'question_id':qid,'field':field,'text':text})
    return result


def decode_flat(raw,source,expected,audit=None):
    """One model map -> existing typed review; original model map stays on disk.

    C/Q quote metadata is retained in the raw receipt and is never a change to
    Source. Every mathematical judgment/evidence/issue survives this projection.
    """
    if not isinstance(raw,dict) or not isinstance(raw.get('records'),dict):
        raise ReviewShapeError('只返回verdict、records、issues；records用原C/Q/段落编号作键，不输出conditions/questions/passages分组')
    originals={c.id:'' for c in source.conditions};originals.update({q.id:'' for q in source.questions})
    originals.update({p['id']:p['text'] for p in expected})
    try:exact_ids(list(raw['records']),list(originals),'单表核验覆盖')
    except ValueError as exc:raise ReviewShapeError(str(exc)) from exc
    bound=copy.deepcopy(raw);copied=[]
    for key,text in originals.items():
        row=bound['records'][key]
        if isinstance(row,dict) and 'quote' not in row:row['quote']=text;copied.append(key)
    if copied and audit:audit('literal_quote_binding',{'stage':'review','record_ids':copied,
        'detail':'仅补绑已知原文/空元数据副本；原模型输出保留，verdict/evidence/issues及已有字符串不变'})
    value=FlatReview.model_validate(bound)
    simple=lambda key:{'verdict':value.records[key].verdict,'evidence':value.records[key].evidence}
    return {'verdict':value.verdict,'conditions':{c.id:simple(c.id) for c in source.conditions},
        'questions':{q.id:simple(q.id) for q in source.questions},
        'passages':{p['id']:value.records[p['id']].model_dump() for p in expected},
        'issues':[i.model_dump() for i in value.issues]}


def normalize(raw,expected,audit=None):
    if not isinstance(raw,dict) or not isinstance(raw.get('passages'),dict):
        raise ReviewShapeError('缺少passages原文对照记录；必须逐段核对绑定的候选原文，不得用正确推导替代原句')
    try:exact_ids(list(raw['passages']),[p['id'] for p in expected],'原文对照覆盖')
    except ValueError as exc:raise ReviewShapeError(str(exc)) from exc
    bound=copy.deepcopy(raw);copied=[]
    for item in expected:
        row=bound['passages'][item['id']]
        if isinstance(row,dict) and 'quote' not in row:
            row['quote']=item['text'];copied.append(item['id'])
    if copied and audit:
        audit('literal_quote_binding',{'stage':'review','passage_ids':copied,
            'detail':'仅补绑本任务已知的原文副本元数据；原模型输出保留，verdict/evidence/issues及任何已有字符串不变，不作数学判断'})
    value=PassageReview.model_validate(bound)
    base=value.model_dump(exclude={'passages'})
    for item in expected:
        record=value.passages[item['id']]
        if record.quote!=item['text']:raise ReviewShapeError('原文对照'+item['id']+'的quote与候选原文不同；不覆盖已有引文，不得默改原句后判通过')
        if record.verdict=='pass':continue
        q=base['questions'].get(item['question_id'])
        if q is None:raise ReviewShapeError('原文对照缺少对应小问核验')
        if record.verdict=='unknown':
            base['verdict']='needs_input';q.update(verdict='unknown',evidence=record.evidence)
        else:
            issue={'stage':'math','target':item['id'],'detail':record.evidence}
            if issue not in base['issues']:base['issues'].append(copy.deepcopy(issue))
            if q['verdict']!='unknown':q.update(verdict='issue',evidence=record.evidence)
            if base['verdict']!='needs_input':base['verdict']='revise'
    return base
