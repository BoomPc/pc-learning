"""Bounded question subagents; full-page rendering/review remains the publish gate."""
import copy
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from .compact_output import unpack, output_schema, pack
from .contracts import Candidate
from .image_tools import ImageTools, VIEW_REGION
from .prompts import messages
from .question_plan import build_plan, ready_groups, scope_payload, validate_basis, analyze_parallelism, scheduling_priorities
from .storage import write_json
from .tools import DEFINITIONS, dispatch


SOURCE_PLAN_INSTRUCTION = '''本次启用小问依赖实验。请用外层对象替代前面的Source顶层输出：
{"source":完整原Source对象,"parallel_plan":{"groups":[{"question_ids":["Q1"],"depends_on":[],"dependency_status":"known"}]}}。
source的题设与最末叶Q号规则不变。groups须恰好覆盖所有Q编号且不重复；depends_on只写需要先取得证明/数值结果的原Q编号。
已知同一问内的依赖可放同组求解；不能把目标当已证结论。同属题设不等于互相依赖。
原文父问/①②与Q号映射不确定、隐含依赖无法确定时，标dependency_status="unknown"并保持整组；不得为并发猜测独立。
本阶段不求解。无论能否拆分都必须输出完整原题与所有条件、疑问。'''


def solve(runner, source, feedback=None):
    from .pipeline import canonical_page
    plan = build_plan(source, runner.question_plan_metadata)
    opportunity = analyze_parallelism(plan)
    chain_fallback = runner.settings.question_concurrency == 2 and not opportunity['has_overlap']
    use_branches = plan['eligible'] and not chain_fallback
    priorities=scheduling_priorities(source,plan) if use_branches else {}
    plan['execution'] = {
        **opportunity,
        'scheduling_priorities':priorities,
        'scheduling_rule':'最长文本权重依赖路径优先；仅是就绪组排队启发式，不改变依赖或证明',
        'strategy': 'question_agents' if use_branches else 'whole_question',
        'reason': ('没有独立分支可重叠，保留整题求解，避免无效小问往返'
                   if chain_fallback and plan['eligible'] else plan['reason']),
    }
    write_json(runner.directory/'question-plan.json', plan)
    runner.audit('question_plan', {'eligible':plan['eligible'], 'reason':plan['reason'],
        'groups':plan['groups'], 'concurrency':runner.settings.question_concurrency,
        'execution':plan['execution']})
    if not use_branches:
        # No speculative per-question requests, and no implicit retry on failure.
        return runner.solve(source, feedback, _whole=True)
    completed = {}
    running = {}
    admitted = set()
    rounds=runner.directory/'question-agents'
    rounds.mkdir(exist_ok=True)
    round_directory=rounds/f'round-{len(list(rounds.glob("round-*")))+1:02d}'
    round_directory.mkdir()
    executor = ThreadPoolExecutor(max_workers=runner.settings.question_concurrency,
                                  thread_name_prefix='math-question')
    success = False
    try:
        while len(completed) < len(source.questions):
            for group in sorted(ready_groups(plan, completed),key=lambda g:-priorities[g['id']]):
                if group['id'] in admitted or len(running) >= runner.settings.question_concurrency:
                    continue
                runner.shared_budget.check()
                admitted.add(group['id'])
                future = executor.submit(run_branch, runner, source, group, list(completed.values()), feedback,round_directory)
                running[future] = group
            if not running:
                raise ValueError('小问依赖调度没有可执行分组，不能发布')
            seconds = runner.shared_budget.remaining_seconds()
            done, _ = wait(running, timeout=max(0, seconds) if seconds is not None else None,
                           return_when=FIRST_COMPLETED)
            if not done:
                raise TimeoutError('小问并发超过整题共享截止时间')
            for future in done:
                group = running.pop(future)
                result = future.result()
                for solution, tab in zip(result.solutions, result.spec['tabs']):
                    if solution.question_id in completed:
                        raise ValueError('子Agent重复提交小问')
                    completed[solution.question_id] = {'solution':solution, 'tab':tab}
                runner.audit('question_group_done', {'group':group['id'],
                    'question_ids':group['question_ids'], 'detail':'仅完成候选解答；尚未通过整题复核'})
        ids = [q.id for q in source.questions]
        candidate = Candidate(solutions=[completed[q]['solution'] for q in ids], spec={
            'format':'jsxgraph-v1', 'title':source.title, 'problem_text':source.problem_text,
            'tabs':[completed[q]['tab'] for q in ids]})
        canonical_page(candidate,source,runner.audit)
        # Collect native-expression/coverage defects across all branches once.
        # A drawing-only correction cannot rewrite any branch's proof. Do not
        # let a branch's SyntaxError bypass the whole-question recovery path.
        candidate=runner.finish_compact(pack(candidate),source,feedback,require_basis=True,dependency_plan=plan)
        # Recheck the dependency closure after a scoped proof citation repair.
        validate_basis(source,plan,candidate.solutions)
        success = True
        return candidate
    except BaseException:
        runner.shared_budget.cancel('一个小问分支失败或整题截止；不自动重发')
        for future in running:future.cancel()
        raise
    finally:
        # Real transports share the parent deadline. Production Worker also owns
        # the process group; cancelling a local future never promises no API bill.
        # Stop new admissions on failure, but collect already-issued requests'
        # usage within the same job deadline before final accounting.
        executor.shutdown(wait=True, cancel_futures=True)


def run_branch(runner, source, group, completed, feedback,round_directory):
    from .pipeline import canonical_page
    directory = round_directory/group['id']
    directory.mkdir(parents=True, exist_ok=False)
    for image in runner.request['images']:
        path = (runner.directory/image['file']).resolve()
        if not path.is_relative_to(runner.directory.resolve()):raise ValueError('分支图片路径越界')
        # Private task-local names, same immutable bytes and original role IDs.
        os.link(path, directory/image['file'])
    records=[]
    started=time.monotonic()
    def audit(kind, detail):
        entry={'kind':kind, **copy.deepcopy(detail)}
        if 'seconds' in detail:entry['duration_seconds']=detail['seconds']
        entry['seconds']=round(time.monotonic()-started,3)
        records.append(entry);write_json(directory/'audit.json',records)
        runner.audit(kind,{**detail,'branch_id':group['id']})
    provider = runner.provider_factory(runner.settings,audit)
    provider.shared_budget=runner.shared_budget
    if hasattr(runner.provider,'pixel_cache'):provider.pixel_cache=runner.provider.pixel_cache
    image_tools=ImageTools(directory,runner.request['images'])
    definitions=[d for d in DEFINITIONS if d['function']['name'] in {'algebra_batch','symbolic_geometry'}]
    if runner.request['images']:definitions=definitions+[VIEW_REGION]
    values=[item['solution'] for item in completed]
    payload=scope_payload(source,group,values)
    payload['feedback']=feedback or []
    scoped=source.model_copy(deep=True)
    scoped.questions=[q for q in source.questions if q.id in group['question_ids']]
    completed_steps=[sid for ids in payload['completed_step_ids'].values() for sid in ids]
    branch_schema=output_schema(scoped.model_dump(),require_basis=True,completed_steps=completed_steps)
    def dispatch_tool(name,args):
        if name=='view_image_region':return image_tools.view(**args)
        return dispatch(name,args)
    try:
        for attempt in range(2):
            prompt=messages('solve',runner.request,directory,payload,compact=True,solve_schema=branch_schema)
            prompt[0]['content']+='\n本分支只负责output_question_ids；context中的完整source保留全部原题，不能改题设。completed_dependencies仅是上游待整题复核的推导，跨问引用须核对适用条件，不能当公理。保留原Q/C编号。仅调用当前声明的数学与局部原图工具，不调用预览或shell。最终答案的顶层键恰为本分支output_question_ids，每个值包含proof、board及可选controls；不提交其它问，不输出Schema的type/properties包装。'
            prompt[0]['content']+='\ncompleted_step_ids按各前置证明的steps顺序明确列出真实步骤编号；引用时逐一对应内容核对，只能用这些前置编号，不凭行数猜编号。'
            schema_args={'output_schema':branch_schema} if runner.settings.solve_responses else {}
            from .submission import receive
            raw=receive(provider,'solve',prompt,audit,tools=definitions,dispatch=dispatch_tool,**schema_args)
            write_json(directory/f'model-{provider.calls:02d}-solve.json',raw)
            try:
                candidate=unpack(raw,scoped)
                canonical_page(candidate,source,audit)
                # Native geometry is validated after merging, through the same
                # scoped correction gate used by a whole-question solve.
                return candidate
            except ValueError as exc:
                audit('contract_error',{'stage':'solve','attempt':attempt+1,'detail':str(exc)[:4000]})
                if attempt:raise
                payload={**payload,'structured_output_correction':{'error':str(exc)[:4000],
                    'rejected_output':raw,'instruction':'仅修正分支输出格式，保持Q/C编号、全部证明和真实未知。不得改原题、删问或删异议。'}}
    finally:
        provider.close()
