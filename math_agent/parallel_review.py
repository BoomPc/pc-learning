"""Question-focused independent reviewers; one shared budget, two request lanes.

Every reviewer sees the entire source/candidate. Condition responsibilities cover
every source ID collectively; compound conditions retain every applicable owner.
Branch opinions are never publication
certificates: Runner still performs inspection recovery, adjudication, source /
math repair and deferred obligations after this conservative merge.
"""
import copy
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from .compact_review import unpack
from .contracts import check_review, exact_ids
from .deferred_review import content_binding
from .image_tools import ImageTools
from .review_partition import merge
from .scene_tools import SceneTools, fingerprint
from .storage import write_json


def review_groups(candidate,ids):
    """At most two proof-size-balanced responsibilities, never less coverage.

    This is scheduling only; full cross-question context remains available and
    no mathematical independence or proof correctness is inferred from length.
    """
    weights={s.question_id:len(json.dumps(s.model_dump(),ensure_ascii=False)) for s in candidate.solutions}
    bins=[[] for _ in range(min(2,len(ids)))];loads=[0]*len(bins)
    for qid in sorted(ids,key=lambda q:-weights[q]):
        index=min(range(len(bins)),key=lambda i:loads[i]);bins[index].append(qid);loads[index]+=weights[qid]
    return [{'id':group[0] if len(group)==1 else f'R{i+1}',
        'question_ids':[q for q in ids if q in group]} for i,group in enumerate(bins)]


def condition_plan(source,ids):
    assigned={qid:[] for qid in ids}
    for c in source.conditions:
        owners=[q for q in ids if q in c.question_ids] or ids[:1]
        for qid in owners:assigned[qid].append(c.id)
    return assigned


def group_conditions(source,all_ids,ids):
    assignment=condition_plan(source,all_ids)
    owned={c for q in ids for c in assignment[q]}
    return [c.id for c in source.conditions if c.id in owned]


def split_group(source,candidate,all_ids,group,raw):
    """Validate actual group coverage BEFORE projecting its immutable records."""
    from .review_passages import passages,normalize,decode_flat
    expected=expected_source(source,group['question_ids'],group_conditions(source,all_ids,group['question_ids']))
    literals=passages(candidate,group['question_ids'])
    raw=normalize(decode_flat(raw,expected,literals),literals)
    check_review(unpack(raw,expected),expected)
    assignment=condition_plan(source,all_ids)
    return {qid:{'verdict':raw['verdict'],
        'conditions':{c:copy.deepcopy(raw['conditions'][c]) for c in assignment[qid]},
        'questions':{qid:copy.deepcopy(raw['questions'][qid])},'issues':copy.deepcopy(raw['issues'])}
        for qid in group['question_ids']}


def expected_source(source, ids, condition_ids=None):
    known=[q.id for q in source.questions]
    if not ids or len(ids)!=len(set(ids)) or not set(ids)<=set(known):
        raise ValueError('分问复核范围缺失、重复或含未知小问')
    expected=source.model_copy(deep=True)
    expected.questions=[q for q in expected.questions if q.id in ids]
    if condition_ids is not None:expected.conditions=[c for c in expected.conditions if c.id in condition_ids]
    return expected


def merge_parts(source, ids, parts):
    expected=expected_source(source,ids)
    exact_ids(list(parts),[q.id for q in expected.questions],'复核分工覆盖')
    assignment=condition_plan(source,ids)
    plan={'groups':[{'question_id':q.id,'output_condition_ids':assignment[q.id]}
                    for q in expected.questions]}
    reviews={qid:unpack(parts[qid],expected_source(source,[qid],assignment[qid])).model_dump() for qid in parts}
    # Select the least settled condition verbatim, retain full branch records and
    # every distinct issue. Never truncate mathematical evidence to fit a field.
    value=merge(expected,plan,reviews)
    return {'verdict':value.verdict,
        'conditions':{c.id:{'verdict':c.verdict,'evidence':c.evidence} for c in value.conditions},
        'questions':{q.id:{'verdict':q.verdict,'evidence':q.evidence} for q in value.questions},
        'issues':[i.model_dump() for i in value.issues]}


def generate(runner,source,candidate,context):
    ids=[q['id'] for q in context['review_output_source']['questions']]
    expected_source(source,ids)
    if runner.shared_budget is None:raise ValueError('分问复核缺少整题共享预算')
    rounds=runner.directory/'review-agents';rounds.mkdir(exist_ok=True)
    directory=rounds/f'round-{len(list(rounds.glob("round-*")))+1:02d}'
    directory.mkdir()
    plan={'question_ids':ids,'condition_ids':[c.id for c in source.conditions],
          'condition_assignment':condition_plan(source,ids),
          'groups':review_groups(candidate,ids),
          'original_tabs':{s.question_id:i for i,s in enumerate(candidate.solutions)},
          'concurrency':2,'context':'全部原图、题设、证明和画板；仅分配questions输出责任'}
    write_json(directory/'plan.json',plan);runner.audit('parallel_review_plan',plan)
    queue=copy.deepcopy(plan['groups']);running={};parts={};group_reviews=[]
    executor=ThreadPoolExecutor(max_workers=2,thread_name_prefix='math-review')
    try:
        while queue or running:
            while queue and len(running)<2:
                runner.shared_budget.check()
                group=queue.pop(0)
                running[executor.submit(run_part,runner,source,candidate,context,group,directory)]=group
            done,_=wait(running,timeout=runner.shared_budget.remaining_seconds(),return_when=FIRST_COMPLETED)
            if not done:raise TimeoutError('分问复核超过整题共享截止时间')
            # Consume failures before admitting more paid work on the next loop.
            completed=[(running.pop(f),f.result()) for f in done]
            for group,raw in completed:
                parts.update(split_group(source,candidate,ids,group,raw))
                group_reviews.append({'group':group,'raw':raw})
                runner.audit('parallel_review_part_done',{'question_ids':group['question_ids'],'verdict':raw['verdict'],
                    'detail':'分工意见；仍须整题合并、工具恢复、独立裁决与原有验收'})
        raw=merge_parts(source,ids,parts)
        record={'binding':content_binding(source,candidate,runner.request),'source':source.model_dump(),
                'candidate':candidate.model_dump(),
                'question_ids':ids,'parts':parts,'group_reviews':group_reviews,'merged':raw}
        runner.parallel_review_rounds.append(record)
        write_json(runner.directory/'parallel-review-rounds.json',runner.parallel_review_rounds)
        write_json(directory/'merged.json',raw)
        return raw
    except BaseException:
        runner.shared_budget.cancel('一个复核分工失败或截止；不重发原请求，不切回整题付费复核')
        for f in running:f.cancel()
        raise
    finally:
        # Stop new admissions immediately, but let already-billed HTTP calls
        # return within their shared deadline so their actual usage is recorded.
        # Reporting a final bill while a live branch is still running is wrong.
        executor.shutdown(wait=True,cancel_futures=True)


def run_part(runner,source,candidate,context,group,directory):
    part_id=group['id'];qids=group['question_ids']
    child=copy.copy(runner)
    child.directory=directory/part_id;child.directory.mkdir()
    for item in runner.request['images']:
        path=(runner.directory/item['file']).resolve()
        if not path.is_relative_to(runner.directory.resolve()):raise ValueError('复核原图路径越界')
        dest=child.directory/item['file'];dest.parent.mkdir(parents=True,exist_ok=True)
        if not dest.resolve().is_relative_to(child.directory.resolve()):raise ValueError('复核原图目标路径越界')
        os.link(path,dest)
    original_tabs={s.question_id:i for i,s in enumerate(candidate.solutions)}
    for qid in qids:
        shot=runner.directory/'output'/f'tab-{original_tabs[qid]:02d}.png'
        if shot.is_file():
            (child.directory/'output').mkdir(exist_ok=True);os.link(shot,child.directory/'output'/shot.name)
    child.records=[];child.ledger=copy.deepcopy(runner.ledger)
    child.scenes=SceneTools(child.directory/'observations');child.scenes.current=copy.deepcopy(candidate.spec)
    child.image_tools=ImageTools(child.directory,runner.request['images'])
    child.review_candidate=candidate.model_copy(deep=True)
    def audit(kind,detail):
        entry={'kind':kind,**copy.deepcopy(detail),'seconds':round(time.monotonic()-runner.started,3)}
        if 'seconds' in detail:entry['duration_seconds']=detail['seconds']
        child.records.append(entry);write_json(child.directory/'audit.json',child.records)
        runner.audit(kind,{**detail,'review_part':part_id,'review_questions':qids})
    child.audit=audit
    child.provider=runner.provider_factory(runner.settings,audit)
    child.provider.shared_budget=runner.shared_budget
    if hasattr(runner.provider,'pixel_cache'):child.provider.pixel_cache=runner.provider.pixel_cache
    ids=[q['id'] for q in context['review_output_source']['questions']]
    assigned=group_conditions(source,ids,qids)
    expected=expected_source(source,qids,assigned)
    payload=copy.deepcopy(context)
    # Existing incremental review may have selected dependency context only. All
    # candidate proofs remain visible here so dependencies cannot disappear.
    from .pipeline import review_payload
    payload['candidate']=review_payload(candidate,[])[0]
    payload['review_output_source']=expected.model_dump()
    from .review_passages import passages,normalize,decode_flat
    payload['literal_passages']=passages(candidate,qids)
    payload['flat_review']=True
    payload['output_record_ids']=[c.id for c in expected.conditions]+[q.id for q in expected.questions]+[p['id'] for p in payload['literal_passages']]
    payload['parallel_review_scope']={'question_ids':qids,'condition_ids':assigned,'original_tabs':original_tabs,
        'coverage':'所有分工合计完整覆盖全部原C/Q；未分配的原条件仍在source中，不能当作已通过的模型结论'}
    def validate(raw):
        base=normalize(decode_flat(raw,expected,payload['literal_passages'],audit=child.audit),payload['literal_passages'])
        value=unpack(base,expected)
        if value.verdict=='pass' and value.issues:value.verdict='revise';raw=copy.deepcopy(raw);raw['verdict']='revise'
        check_review(value,expected)
        from .inspection_recovery import reconcile,partition_pending
        from .rendering import strict_spec
        inspections=[r for r in child.records if r['kind']=='tool' and r.get('name')=='inspect_scene']
        pending,_=partition_pending(reconcile(inspections,fingerprint(strict_spec(candidate.spec)))['unresolved'],candidate.spec)
        if pending:raise ValueError('真实图形查询仍须同图同目标有效重做：'+json.dumps(pending,ensure_ascii=False))
        return copy.deepcopy(raw)
    try:return child.validated('review',payload,validate)
    finally:child.provider.close()


def check_rounds(records,source,candidate,request,math_receipts):
    if not records:raise ValueError('分问复核缓存缺少完整分工记录，不自动付费重算')
    all_ids=[q.id for q in source.questions]
    same_source=[r for r in records if r.get('source')==source.model_dump()]
    if not same_source or same_source[0].get('question_ids')!=all_ids:
        raise ValueError('分问复核缓存缺少当前题设的首次全问覆盖')
    for record in same_source:
        from .contracts import Candidate,check_candidate
        bound_candidate=Candidate.model_validate(record['candidate'])
        check_candidate(bound_candidate,source)
        if record['binding']!=content_binding(source,bound_candidate,request):raise ValueError('复核原文候选与绑定不符')
        group_reviews=record.get('group_reviews')
        if not group_reviews:raise ValueError('分问复核缓存缺少实际分工的原始记录')
        flat={}
        for item in group_reviews:
            values=split_group(source,bound_candidate,record['question_ids'],item['group'],item['raw'])
            if set(flat)&set(values):raise ValueError('实际复核分工重复覆盖小问')
            flat.update(values)
        if flat!=record['parts']:raise ValueError('复核分工投影与原始C/Q记录不符')
        if merge_parts(source,record['question_ids'],record['parts'])!=record['merged']:
            raise ValueError('分问复核缓存合并意见与原分工不符')
    last=same_source[-1]
    if last['binding']!=content_binding(source,candidate,request):
        raise ValueError('分问复核缓存未绑定当前原图、题设、解答及画板')
    if last['question_ids']!=all_ids:
        # Existing receipt verifier must already have checked unchanged proofs,
        # dependency closure, prior pass records and every original condition.
        if not math_receipts or math_receipts[-1]['scope']['question_ids']!=last['question_ids']:
            raise ValueError('局部分工缓存缺少对应数学复核复用收据')
