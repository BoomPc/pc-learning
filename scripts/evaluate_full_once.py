"""One isolated, explicitly authorized image-to-page acceptance run; never retries a job."""
import argparse, json, os, signal, time
from dataclasses import replace
from pathlib import Path
from math_agent.config import Settings
from math_agent.pipeline import Runner
from math_agent.storage import Store, write_json
from math_agent.image_input import save_image
from types import SimpleNamespace


def execute_and_read_report(runner, directory):
    # Runner.execute writes the authoritative report and returns None.
    # Keep exceptions visible; a prior report must never mask a failed execution.
    runner.execute()
    result=json.loads((directory/'report.json').read_text())
    if result.get('status') != 'completed':
        raise ValueError('Agent未保存完成报告，不能标记验收通过')
    return result


def prepare_diagnostic(runner,path):
    """Explicit saved-output diagnosis; never presented as new image acceptance."""
    from math_agent.contracts import Source,check_source,check_candidate
    from math_agent.compact_output import unpack
    from math_agent.pipeline import canonical_page
    from math_agent.submission import inspect
    raw=json.loads(path.read_text())
    source=Source.model_validate(raw['source'])
    check_source(source,runner.request['images'])
    if source.uncertainties:raise ValueError('诊断题设仍有未决问题，不启动模型')
    candidate=canonical_page(unpack(raw['solve'],source),source,runner.audit)
    check_candidate(candidate,source)
    issues=inspect(candidate,source)
    if any(i['stage']!='diagram' for i in issues):raise ValueError('此诊断入口只接受构图问题，不得绕过数学修订')
    feedback=[{'stage':'diagram','target':i['question_id'],'detail':i['detail']} for i in issues]
    write_json(runner.directory/'diagnostic-input.json',raw)
    runner.resume_state={'source':source,'candidate':candidate,'entry':'diagram' if issues else 'observe',
        'feedback':feedback,'repairs':1 if issues else 0}
    runner.audit('explicit_diagnostic',{'imported_source_and_solve':True,'paid_requests_so_far':0,
        'issues':issues,'detail':'仅复用已保存候选，修复后真实渲染及完整复核；不是新题生成成绩'})


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--env',type=Path,required=True)
    ap.add_argument('--fixtures',type=Path,required=True)
    ap.add_argument('--case',required=True)
    ap.add_argument('--price-multiplier',type=int,choices=[1,2],required=True)
    ap.add_argument('--max-calls',type=int,choices=range(1,31),default=12,
        help='整题共享调用上限；含子Agent工具往返、纠错和复核，不自动扩充')
    ap.add_argument('--max-repairs',type=int,choices=range(0,5),default=2,
        help='总修正上限；数学和图形必须分开修正，仍共享整题调用预算及截止时间')
    ap.add_argument('--review-effort',choices=['inherit','low','high','max'],default='inherit',
        help='数学/图文复核与裁决强度；inherit沿用全局，不改变识题和解题强度')
    ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--diagnostic-input',type=Path,help='显式导入已保存source/solve，只做诊断；不得当完整新题测速')
    ap.add_argument('--question-agents',choices=['off','serial','parallel'],default='off',
        help='off=原整题串行；serial/parallel=同一小问依赖调度器，分别1路/2路')
    ap.add_argument('--review-agents',choices=['off','parallel'],default='off',help='每问独立复核，最多2路，共享整题预算与截止时间')
    a=ap.parse_args()
    if not a.case.isdigit() or not 1<=int(a.case)<=60:ap.error('case须为1到60题号')
    out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    for line in a.env.read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            k,v=line.split('=',1);os.environ[k]=v
    cfg=replace(Settings(),data_dir=out/'runtime',redis_url='',reference_mode=False,review_plan=False,
        solve_draft=False,compact_tools=True,review_responses=True,incremental_review=a.review_agents=='off',parallel_review=a.review_agents=='parallel',
        incremental_math_review=True,thinking=True,diagram_thinking=True,effort='low',review_effort='' if a.review_effort=='inherit' else a.review_effort,max_tokens=64000,
        solve_max_tokens=0,review_max_tokens=0,review_reserve_seconds=0,job_timeout=240,max_calls=a.max_calls,max_repairs=a.max_repairs,
        parallel_questions=a.question_agents!='off',question_concurrency=2 if a.question_agents=='parallel' else 1)
    store=Store(cfg.data_dir);job,directory=store.prepare();store.enqueue(job);store.claim()
    paths=[('question',a.fixtures/(a.case+'.png'))]+[('answer',p) for p in sorted(a.fixtures.glob('ref-'+a.case+'-answer-*.png'))]
    if len(paths)<2:raise ValueError('缺少原题或参考答案，不启动模型请求')
    images=[]
    for i,(role,p) in enumerate(paths,1):
        name=f'I{i}.png'
        with p.open('rb') as stream:
            sha=save_image(SimpleNamespace(stream=stream),directory/name)
        images.append({'id':f'I{i}','role':role,'file':name,'sha256':sha})
    write_json(directory/'request.json',{'text':'','images':images,'force':True})
    write_json(out/'config.json',{'case':a.case,'effort':cfg.effort,'review_effort':cfg.review_effort or cfg.effort,'max_tokens':cfg.max_tokens,
        'timeout':cfg.job_timeout,'max_calls':cfg.max_calls,'max_repairs':cfg.max_repairs,'ocr_enabled':bool(cfg.ocr_url),'price_multiplier':a.price_multiplier,
        'native_constructions':cfg.native_constructions,'solve_responses':cfg.solve_responses,'overlap_ocr':cfg.overlap_ocr,
        'incremental_math_review':True,'question_agents':a.question_agents,'review_agents':a.review_agents,
        'scope':('explicit saved source/solve diagnosis; excludes OCR and solving; requires new render and full review'
                 if a.diagnostic_input else 'image input including OCR service wall time; no saved source/solve/review imported')})
    runner=Runner(cfg,job);start=time.monotonic()
    report={'status':'failed','job_id':job,'end_to_end':not bool(a.diagnostic_input),'case':a.case}
    class DeadlineReached(BaseException):pass
    def deadline(*_):
        report['deadline_hit']=True
        raise DeadlineReached('完整验收240秒截止；未自动重启或重发，未返回usage的请求可能计费')
    signal.signal(signal.SIGALRM,deadline);signal.alarm(cfg.job_timeout)
    print('START',job,flush=True)
    try:
        if a.diagnostic_input:prepare_diagnostic(runner,a.diagnostic_input)
        result=execute_and_read_report(runner,directory);report.update(status=result['status'])
    except (DeadlineReached,Exception) as exc:
        detail=str(exc)
        for secret in (cfg.api_key,cfg.access_token):
            if secret:detail=detail.replace(secret,'[REDACTED]')
        report.update(error_type=type(exc).__name__,error=detail[:4000])
    finally:
        signal.alarm(0);runner.provider.close()
        if runner.pending_ocr is not None:runner.pending_ocr.close()
        report.update(seconds=round(time.monotonic()-start,3),calls=runner.model_calls,pending=len(runner.deferred_reviews.pending))
        if runner.shared_budget is not None:write_json(out/'shared-budget.json',runner.shared_budget.snapshot())
        write_json(out/'result.json',report)
        models=[r for r in runner.records if r['kind']=='model']
        used=[r.get('usage',{}) for r in models if r.get('usage')]
        hit=miss=output=0
        for u in used:
            cached=u.get('prompt_cache_hit_tokens',u.get('input_tokens_details',{}).get('cached_tokens',u.get('prompt_tokens_details',{}).get('cached_tokens',0))) or 0
            total=u.get('input_tokens',u.get('prompt_tokens',0)) or 0
            hit+=cached;miss+=u.get('prompt_cache_miss_tokens',max(0,total-cached)) or 0
            output+=u.get('output_tokens',u.get('completion_tokens',0)) or 0
        write_json(out/'usage-summary.json',{'cache_hit_input_tokens':hit,'cache_miss_input_tokens':miss,
            'output_tokens_including_reasoning':output,'known_usage_cost_cny_estimate':round(a.price_multiplier*(hit*.02+miss+output*4)/1_000_000,6),
            'not_sent_calls':sum(bool(r.get('not_sent')) for r in models),
            'incomplete_usage':len(used)+sum(bool(r.get('not_sent')) for r in models)<runner.model_calls,
            'price_multiplier':a.price_multiplier,'pricing_scope':'2026-10-20 verified CNY base 0.02/1/4 per million times peak multiplier; not final invoice','pricing_source':'https://api-docs.deepseek.com/zh-cn/quick_start/pricing/'})
        write_json(out/'stages.json',[{k:v for k,v in r.items() if k in {'seconds','kind','stage','node','call','status','error','branch_id','duration_seconds'}}
                                     for r in runner.records if r['kind'] in {'model','graph_node','ocr','contract_error','math_review_scope'}])
        store.finish(job,'completed' if report['status']=='completed' else 'failed',error=report.get('error'))
        print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
