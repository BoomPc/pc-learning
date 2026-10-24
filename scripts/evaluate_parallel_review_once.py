"""Explicit saved-candidate parallel-review diagnosis; no OCR, solve or publication.

Re-renders all native JSXGraph scenes and runs the same independent reviewers,
inspection/adjudication/deferred gates as Runner. Not an image-to-page acceptance.
"""
import argparse
import hashlib
import json
import os
import signal
import time
from dataclasses import replace
from pathlib import Path
from math_agent.config import Settings
from math_agent.contracts import Source,Candidate,check_source,check_candidate
from math_agent.pipeline import Runner
from math_agent.storage import Store,write_json


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ['env','input-job','out']:p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--effort',choices=['low','high','max'],required=True)
    p.add_argument('--price-multiplier',type=int,choices=[1,2],required=True)
    a=p.parse_args();root=a.input_job.resolve();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    for line in a.env.read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            key,value=line.split('=',1);os.environ[key]=value
    cfg=replace(Settings(),data_dir=out/'runtime',redis_url='',ocr_url='',parallel_review=True,
        parallel_questions=False,reference_mode=False,review_plan=False,incremental_review=False,
        incremental_math_review=False,compact_tools=True,review_responses=True,thinking=True,
        effort='low',review_effort=a.effort,max_tokens=64000,solve_max_tokens=0,review_max_tokens=0,
        review_reserve_seconds=0,max_calls=12,job_timeout=180)
    source=Source.model_validate(json.loads((root/'source.json').read_text()))
    candidate=Candidate.model_validate(json.loads((root/'candidate.json').read_text()))
    request=json.loads((root/'request.json').read_text());request['force']=True;request['ocr_evidence']=[]
    check_source(source,request['images']);check_candidate(candidate,source)
    if source.uncertainties:raise ValueError('题设仍未确定，不能以复核诊断替代识题')
    store=Store(cfg.data_dir);job,directory=store.prepare()
    for item in request['images']:
        path=(root/item['file']).resolve()
        if path.parent!=root or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:
            raise ValueError('输入原图路径或字节哈希不符')
        os.link(path,directory/path.name)
    write_json(directory/'request.json',request);store.enqueue(job);store.claim()
    runner=Runner(cfg,job);started=time.monotonic()
    report={'status':'failed','end_to_end':False,'job_id':job,'review_effort':a.effort,
        'candidate_sha256':hashlib.sha256((root/'candidate.json').read_bytes()).hexdigest(),
        'scope':'已保存候选的分问并行完整复核诊断；重新渲染，不识题、不解题、不修正候选、不发布；不是端到端验收'}
    class DeadlineReached(BaseException):pass
    def deadline(*_):raise DeadlineReached('分问复核诊断180秒截止，不自动重发请求；未知usage可能计费')
    signal.signal(signal.SIGALRM,deadline);signal.alarm(180)
    print('START',job,flush=True)
    try:
        observation=runner.observe(candidate)
        review=runner.review(source,candidate,observation)
        write_json(directory/'review.json',review.model_dump())
        report.update(status='review_returned',verdict=review.verdict,issues=[i.model_dump() for i in review.issues])
    except (DeadlineReached,Exception) as exc:
        detail=str(exc)
        for secret in [cfg.api_key,cfg.access_token]:
            if secret:detail=detail.replace(secret,'[REDACTED]')
        report.update(error_type=type(exc).__name__,error=detail[:3000])
    finally:
        signal.alarm(0);runner.provider.close()
        snapshot=runner.shared_budget.snapshot();write_json(out/'shared-budget.json',snapshot)
        records=[r for r in runner.records if r['kind']=='model' and r.get('usage')]
        usage=[r['usage'] for r in records]
        hit=sum(u.get('input_tokens_details',{}).get('cached_tokens',u.get('prompt_cache_hit_tokens',0)) or 0 for u in usage)
        total=sum(u.get('input_tokens',u.get('prompt_tokens',0)) or 0 for u in usage)
        output=sum(u.get('output_tokens',u.get('completion_tokens',0)) or 0 for u in usage)
        report.update(seconds=round(time.monotonic()-started,3),calls=runner.model_calls,
            pending=len(runner.deferred_reviews.pending),usage={'cached_input':hit,'uncached_input':max(0,total-hit),'output_including_reasoning':output},
            known_usage_cost_cny_estimate=round(a.price_multiplier*(hit*.02+max(0,total-hit)+output*4)/1_000_000,6),
            incomplete_usage=not snapshot['usage']['complete'],price_multiplier=a.price_multiplier)
        write_json(out/'result.json',report)
        store.finish(job,'completed' if report['status']=='review_returned' else 'failed',error=report.get('error'),
            summary={'diagnostic_only':True,'end_to_end':False,'published':False})
    print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
