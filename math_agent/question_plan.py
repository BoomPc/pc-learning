"""Conservative solve scheduling. Plans describe dependencies, never prove independence.

Source remains unchanged. Optional metadata is separate from its mathematical
contract; absent/unknown dependencies retain one whole-question solve.
"""
from __future__ import annotations
import copy
import re
from .contracts import Solution, exact_ids


def _serial(source, reason):
    ids = [q.id for q in source.questions]
    return {'eligible': False, 'reason': reason, 'groups': [{
        'id': 'G1', 'question_ids': ids, 'depends_on': [],
        'context_question_ids': ids, 'condition_ids': [c.id for c in source.conditions]}]}


def _ambiguous_circled_labels(text):
    """Allow only clearly declared local mathematical options, never map leaf IDs.

    A complete ascending list separated by colons/semicolons with a relation in
    every item is local content. Repeated labels, prose references and partial
    lists remain ambiguous. This is a routing guard, not a mathematical proof.
    """
    labels = '①②③④⑤⑥⑦⑧⑨⑩'
    matches = list(re.finditer('['+labels+']', text))
    if not matches:
        return False
    # A local task heading (e.g. a circled label after the given conditions)
    # declares what this group must solve; it does not reference another proof.
    # Keep its text and IDs unchanged, rather than guessing an original Q ID.
    local_tasks = True
    for i, marker in enumerate(matches):
        prefix = text[:marker.start()].rstrip()
        end = matches[i+1].start() if i+1 < len(matches) else len(text)
        body = text[marker.end():end].lstrip()
        if (prefix and prefix[-1] not in ':：;；.．。\n') or not re.match(r'(?:求|证明|判断|说明|讨论|计算|解答|画出|作出|写出)', body):
            local_tasks = False
    positions = [labels.index(m.group()) for m in matches]
    if local_tasks and positions == list(range(positions[0], positions[0]+len(matches))):
        return False
    if ''.join(m.group() for m in matches) != labels[:len(matches)]:
        return True
    if len(matches) < 2:
        return True
    for i, marker in enumerate(matches):
        prefix = text[:marker.start()].rstrip()
        if prefix and prefix[-1] not in (':：' if i == 0 else ';；'):
            return True
        end = matches[i+1].start() if i+1 < len(matches) else len(text)
        if not re.search(r'[=<>≤≥∥⊥]', text[marker.end():end]):
            return True
    return False


def build_plan(source, metadata=None):
    """Validate an explicit complete DAG, or conservatively retain the full solve.

    metadata={"groups":[{"question_ids":["Q1"], "depends_on":[],
                         "dependency_status":"known"}, ...]}.
    depends_on contains original question IDs (not generated group IDs).
    Numeric/nested source labels are deliberately never guessed from Q numbering.
    """
    ids = [q.id for q in source.questions]
    exact_ids(ids, ids, '原题小问')
    if metadata is None:
        return _serial(source, '没有显式依赖计划，不能把未声明依赖当作独立')
    if not isinstance(metadata, dict) or set(metadata) != {'groups'}:
        raise ValueError('依赖计划必须只含groups')
    rows = metadata['groups']
    if not isinstance(rows, list) or not rows:
        raise ValueError('依赖计划groups不能为空')
    unknown = False
    covered = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'question_ids', 'depends_on', 'dependency_status'}:
            raise ValueError('依赖组字段必须为question_ids/depends_on/dependency_status')
        for key in ('question_ids', 'depends_on'):
            if not isinstance(row[key], list) or any(not isinstance(v, str) for v in row[key]):
                raise ValueError(f'{key}必须是原题编号列表')
            if len(row[key]) != len(set(row[key])):
                raise ValueError(f'{key}出现重复编号')
        if not row['question_ids'] or not set(row['depends_on']) <= set(ids):
            raise ValueError('依赖组为空或引用未知小问')
        if row['dependency_status'] not in ('known', 'unknown'):
            raise ValueError('dependency_status必须为known或unknown')
        unknown |= row['dependency_status'] == 'unknown'
        covered.extend(row['question_ids'])
    exact_ids(covered, ids, '依赖计划小问覆盖')
    owner = {q: i for i, row in enumerate(rows) for q in row['question_ids']}
    edges = {i: {owner[q] for q in row['depends_on']} for i, row in enumerate(rows)}
    # Internal dependencies are solved together, without treating their answers
    # as already known. They are not inter-group scheduling edges.
    edges = {i: deps - {i} for i, deps in edges.items()}
    pending = set(edges)
    ordered = []
    while pending:
        ready = [i for i in range(len(rows)) if i in pending and not edges[i] & pending]
        if not ready:
            raise ValueError('依赖计划存在跨组循环')
        ordered.extend(ready)
        pending.difference_update(ready)
    closures = {}
    for i in ordered:
        closures[i] = set(edges[i])
        for j in edges[i]:
            closures[i].update(closures[j])
    positions = {qid: index for index, qid in enumerate(ids)}
    for i, ancestors in closures.items():
        earliest_output = min(positions[q] for q in rows[i]['question_ids'])
        prerequisite_questions = {q for j in ancestors for q in rows[j]['question_ids']}
        if any(positions[q] > earliest_output for q in prerequisite_questions):
            return _serial(source, '前置依赖包含原题靠后小问，与最终步骤原序约束冲突，保留整组求解')
    # Any wording that references a source ordinal/leaf is ambiguous because
    # Source flattens subquestions. Never map '(2)' to Q2 by position.
    ambiguous = re.compile(r'上一问|前一问|前面各问|前两问|第\s*[（(]?\s*[一二三四五六七八九十\d]+\s*[)）]?\s*问|由\s*[（(]\s*\d+\s*[)）]')
    for q in source.questions:
        if ambiguous.search(q.text) or _ambiguous_circled_labels(q.text):
            unknown = True
        mentions = set(re.findall(r'(?<![A-Za-z0-9])Q[1-9][0-9]*(?![A-Za-z0-9])', q.text)) - {q.id}
        allowed = {qid for j in closures[owner[q.id]] | {owner[q.id]} for qid in rows[j]['question_ids']}
        if not mentions <= set(ids):
            unknown = True
        elif not mentions <= allowed:
            raise ValueError(f'{q.id}文字引用未声明的跨组依赖{sorted(mentions-allowed)}')
    if unknown:
        return _serial(source, '依赖未知或原题父问/叶编号无法安全映射，保留整组求解')
    groups = []
    for i in ordered:
        own = set(rows[i]['question_ids'])
        context = own | {q for j in closures[i] for q in rows[j]['question_ids']}
        groups.append({'id': f'G{i+1}', 'question_ids': [q for q in ids if q in own],
                       'depends_on': [f'G{j+1}' for j in sorted(edges[i])],
                       'context_question_ids': [q for q in ids if q in context],
                       'condition_ids': [c.id for c in source.conditions if not c.question_ids or set(c.question_ids) & context]})
    return {'eligible': len(groups) > 1, 'reason': '显式依赖DAG；仍须检查依据与整题数学复核', 'groups': groups}


def ready_groups(plan, completed_question_ids):
    """Only schedule groups whose complete transitive prerequisites exist."""
    done = set(completed_question_ids)
    return [g for g in plan['groups'] if not set(g['question_ids']) <= done
            and not set(g['question_ids']) & done
            and set(g['context_question_ids']) - set(g['question_ids']) <= done]


def scheduling_priorities(source,plan):
    """Longest remaining text-weighted DAG path, a scheduling heuristic only.

    It changes admission order among already-ready groups, never dependencies,
    condition scopes, proof order, model strength or the shared deadline.
    """
    questions={q.id:q.text for q in source.questions}
    conditions={c.id:c.text for c in source.conditions}
    weights={g['id']:sum(len(questions[q]) for q in g['question_ids'])+
             sum(len(conditions[c]) for c in g['condition_ids']) for g in plan['groups']}
    children={g['id']:[] for g in plan['groups']}
    for group in plan['groups']:
        for parent in group['depends_on']:children[parent].append(group['id'])
    scores={}
    def score(gid):
        if gid not in scores:scores[gid]=weights[gid]+max((score(c) for c in children[gid]),default=0)
        return scores[gid]
    return {gid:score(gid) for gid in children}


def scope_payload(source, group, completed_solutions):
    """Keep original IDs/scopes; never include unfinished prerequisite results."""
    values = [Solution.model_validate(v) if isinstance(v, dict) else v for v in completed_solutions]
    by_id = {s.question_id: s for s in values}
    if len(by_id) != len(values):
        raise ValueError('已完成解答编号重复')
    prerequisites = set(group['context_question_ids']) - set(group['question_ids'])
    if not prerequisites <= set(by_id):
        raise ValueError('依赖小问尚未完成，禁止把待求结论当已知传入')
    # The full Source retains condition scopes and nested source numbering;
    # output scope, not rewriting Source, limits this branch's responsibility.
    return {'source': copy.deepcopy(source.model_dump()),
            'output_question_ids': list(group['question_ids']),
            'context_condition_ids': list(group['condition_ids']),
            'completed_step_ids':{q:[f'{q}:S{i+1}' for i in range(len(by_id[q].steps))]
                                  for q in group['context_question_ids'] if q in prerequisites},
            'completed_dependencies': [by_id[q].model_dump() for q in group['context_question_ids'] if q in prerequisites]}


def collect_basis_issues(source, plan, solutions,require_nonempty=True):
    """Reject undeclared branch transfer; no mathematical truth is certified.

    Same-group earlier steps may be cited. Cross-group steps must be in the
    declared dependency closure and completed, including during final merging.
    """
    values = [Solution.model_validate(v) if isinstance(v, dict) else v for v in solutions]
    exact_ids([s.question_id for s in values], [q.id for q in source.questions], '合并解答')
    by_id = {s.question_id: s for s in values}
    conditions = {c.id: c for c in source.conditions}
    available = set(conditions)
    issues=[]
    def add(qid,path,detail,code='invalid_dependency'):
        issues.append({'stage':'math','question_id':qid,'path':path,'code':code,'detail':detail+
            '；请从该问适用条件重新检查并证明，不得只删依据来掩盖无效推导；题设、依赖计划和其它小问保持不变'})
    for group in plan['groups']:
        allowed = set(group['context_question_ids'])
        for qid in group['question_ids']:
            solution = by_id[qid]
            for cid in solution.condition_ids:
                if cid not in conditions:
                    add(qid,'proof.condition_ids',f'{qid}引用未知条件{cid}');continue
                scope = set(conditions[cid].question_ids)
                if scope and qid not in scope:
                    add(qid,'proof.condition_ids',f'{qid}直接采用其它小问局部条件{cid}；须显式证明迁移')
            for index, step in enumerate(solution.steps, 1):
                if require_nonempty and not step.basis_ids:
                    add(qid,f'proof.steps.{index-1}.basis_ids',f'{qid}:S{index}缺少依据，不能确认依赖范围','missing_basis')
                for basis in step.basis_ids:
                    if basis not in available:
                        add(qid,f'proof.steps.{index-1}.basis_ids',f'{qid}:S{index}未知或尚未完成的依据{basis}');continue
                    if basis in conditions:
                        scope = set(conditions[basis].question_ids)
                        if scope and qid not in scope:
                            add(qid,f'proof.steps.{index-1}.basis_ids',f'{qid}:S{index}越界使用局部条件{basis}')
                    elif basis.split(':', 1)[0] not in allowed:
                        add(qid,f'proof.steps.{index-1}.basis_ids',f'{qid}:S{index}引用未声明跨组依赖{basis}')
                available.add(f'{qid}:S{index}')
    return issues


def validate_basis(source,plan,solutions,require_nonempty=True):
    issues=collect_basis_issues(source,plan,solutions,require_nonempty)
    if issues:raise ValueError('；'.join(i['detail'] for i in issues))
    return True


def analyze_parallelism(plan):
    """Report structural overlap potential; never alter the solve plan.

    A wave assumes every ready group completes before the next wave. Its peak
    is an opportunity in the DAG, not a promise about actual runtime overlap.
    """
    groups = plan['groups']
    by_id = {g['id']: g for g in groups}
    if len(by_id) != len(groups):
        raise ValueError('分析计划组编号重复')
    dependencies = {g['id']: set(g['depends_on']) for g in groups}
    if any(not deps <= set(by_id) for deps in dependencies.values()):
        raise ValueError('分析计划引用未知依赖组')
    pending = set(by_id)
    completed = set()
    peak = 0
    while pending:
        ready = {gid for gid in pending if dependencies[gid] <= completed}
        if not ready:
            raise ValueError('分析计划存在依赖循环')
        peak = max(peak, len(ready))
        pending.difference_update(ready)
        completed.update(ready)
    return {'max_ready_groups': peak, 'has_overlap': peak > 1}
