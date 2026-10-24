"""Dependency and merge contracts for question-scoped review.

No model calls or concurrent execution here. The serial math revision reviewer
uses dependency planning; parallel execution is not enabled.
"""
import copy,re,json
from .contracts import Source,Review,Check,check_candidate,check_review,exact_ids


def partition(source,candidate):
    check_candidate(candidate,source)
    ids=[q.id for q in source.questions];by_id={s.question_id:s for s in candidate.solutions}
    complete=all(step.basis_ids for s in candidate.solutions for step in s.steps)
    text_dependencies={}
    for i,q in enumerate(source.questions):
        text=q.text+' '+json.dumps(by_id[q.id].model_dump(),ensure_ascii=False)
        mentioned=set(re.findall(r'(?<![A-Za-z0-9])Q[1-9][0-9]*(?![A-Za-z0-9])',text))
        for n in re.findall(r'(?:第\s*[（(]?|由\s*[（(])([1-9][0-9]*)[)）]?\s*问?',text):
            if int(n)<=len(ids):mentioned.add(ids[int(n)-1])
        if re.search('上一问|前一问|前面各问|前两问',text):mentioned.update(ids[:i])
        if mentioned-set(ids):complete=False
        text_dependencies[q.id]=mentioned&set(ids)
    groups=[]
    for qid in ids:
        closure={qid}
        if complete:
            while True:
                expanded=closure|set().union(*(text_dependencies[q] for q in closure))|{b.split(':',1)[0] for q in closure for st in by_id[q].steps for b in st.basis_ids if ':' in b}
                if expanded==closure:break
                closure=expanded
        else:closure=set(ids)
        proof_closure=set(closure)
        # Compound source conditions may mention more than one figure. Include
        # those source questions/boards without unnecessarily re-proving them.
        while True:
            expanded=closure|{q for c in source.conditions if len(c.question_ids)>1 and set(c.question_ids)&closure for q in c.question_ids}
            if expanded==closure:break
            closure=expanded
        needed={c.id for c in source.conditions if not c.question_ids or any(q in c.question_ids for q in closure)}
        for q in closure:
            needed.update(by_id[q].condition_ids)
            needed.update(b for st in by_id[q].steps for b in st.basis_ids if ':' not in b)
        own=[c.id for c in source.conditions if not c.question_ids or qid in c.question_ids]
        groups.append({'question_id':qid,'output_condition_ids':own,
            'context_questions':[q for q in ids if q in closure],'proof_questions':[q for q in ids if q in proof_closure],
            'context_condition_ids':[c.id for c in source.conditions if c.id in needed],
            'context_tabs':[i for i,q in enumerate(ids) if q in closure],
            'unscoped_basis':not complete})
    if set(c for g in groups for c in g['output_condition_ids'])!={c.id for c in source.conditions}:
        raise ValueError('按问分区未覆盖全部原条件，不可缩小复核范围')
    return {'eligible':complete and len(ids)>1 and any(len(g['proof_questions'])<len(ids) for g in groups),'groups':groups,
        'scope':'按显式basis_ids与可识别跨问文字计算依赖闭包，遗漏依据/未知问号时保留整卷上下文并不启用并行；不是证明正确性证书。'}


def scope_payload(source,candidate,group):
    questions=set(group['context_questions']);proofs=set(group['proof_questions']);conditions=set(group['context_condition_ids'])
    return {'source':{**source.model_dump(),'questions':[q.model_dump() for q in source.questions if q.id in questions],
        'conditions':[c.model_dump() for c in source.conditions if c.id in conditions]},
        'candidate':{'solutions':[s.model_dump() for s in candidate.solutions if s.question_id in proofs],
            'tabs':[{'tab':i,**{k:copy.deepcopy(v) for k,v in candidate.spec['tabs'][i].items() if k not in {'steps','conclusion'}}} for i in group['context_tabs']]},
        'output_scope':{'question_ids':[group['question_id']],'condition_ids':group['output_condition_ids']},
        'detail':'tab保留原始编号；上下文中依赖小问不是本分支待审目标，发现其错误仍须报告issues。不能将依赖目标当已知。'}


def merge(source,plan,values):
    ids=[q.id for q in source.questions];exact_ids(list(values),ids,'按问复核结果')
    reviews={};groups={g['question_id']:g for g in plan['groups']}
    for qid in ids:
        value=Review.model_validate(values[qid]);g=groups[qid]
        exact_ids([c.id for c in value.conditions],g['output_condition_ids'],'分支条件覆盖')
        exact_ids([q.id for q in value.questions],[qid],'分支小问覆盖')
        reduced=source.model_copy(deep=True)
        reduced.conditions=[c for c in source.conditions if c.id in set(g['output_condition_ids'])]
        reduced.questions=[q for q in source.questions if q.id==qid]
        check_review(value,reduced);reviews[qid]=value
    rank={'pass':0,'issue':1,'unknown':2};conditions=[]
    for c in source.conditions:
        rows=[v for q in ids for v in reviews[q].conditions if v.id==c.id]
        # Preserve the full branch records separately; select the least settled
        # check verbatim instead of concatenating/truncating mathematical evidence.
        worst=max(rows,key=lambda v:rank[v.verdict]);conditions.append(worst.model_copy(deep=True))
    questions=[reviews[q].questions[0].model_copy(deep=True) for q in ids]
    issues=[]
    for q in ids:
        for issue in reviews[q].issues:
            if issue not in issues:issues.append(issue.model_copy(deep=True))
    if any(v.verdict=='needs_input' for v in reviews.values()) or any(c.verdict=='unknown' for c in conditions+questions):verdict='needs_input'
    elif issues or any(v.verdict=='revise' for v in reviews.values()):verdict='revise'
    else:verdict='pass'
    result=Review(verdict=verdict,conditions=conditions,questions=questions,issues=issues)
    check_review(result,source)
    return result
