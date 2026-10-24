"""One explicit, bounded, read-only math-review diagnosis of a saved candidate.

No solve, OCR, rendering, cache, worker, publication, implicit retry or success
certificate. A returned pass is a model opinion and needs manual defect scoring.
"""
import argparse
import copy
import hashlib
import json
import os
import signal
import time
from dataclasses import replace
from pathlib import Path
from math_agent.config import Settings
from math_agent.contracts import Source,Candidate,check_source,check_candidate,check_review
from math_agent.compact_review import output_schema,unpack
from math_agent.pipeline import review_payload
from math_agent.prompts import messages
from math_agent.provider import DeepSeek
from math_agent.parallel_budget import ParallelBudget
from math_agent.submission import receive
from math_agent.tools import DEFINITIONS,dispatch
from math_agent.image_tools import ImageTools,VIEW_REGION
from math_agent.storage import write_json


def prepare_context(source,candidate,question_ids):
    known=[q.id for q in source.questions]
    if not question_ids or len(set(question_ids))!=len(question_ids) or not set(question_ids)<=set(known):
        raise ValueError('诊断须显式选取现有且不重复的小问编号')
    expected=source.model_copy(deep=True)
    expected.questions=[q for q in expected.questions if q.id in question_ids]
    data,_=review_payload(candidate,[])
    return expected,{'source':source.model_dump(),'candidate':data,
        'review_output_source':expected.model_dump(),'diagnostic_question_ids':[q.id for q in expected.questions],
        'diagnostic_scope':'仅诊断指定证明的steps/cases/domain_and_boundaries及必要题设/推导上下文；不是整题或图形验收，无发布资格'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ['env','input-job','out']:parser.add_argument('--'+key,type=Path,required=True)
    parser.add_argument('--question',action='append',required=True)
    parser.add_argument('--effort',choices=['low','high','max'],required=True)
    parser.add_argument('--price-multiplier',type=int,choices=[1,2],required=True)
    args=parser.parse_args();root=args.input_job.resolve();out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
    for line in args.env.read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            key,value=line.split('=',1);os.environ[key]=value
    cfg=replace(Settings(),data_dir=out/'runtime',redis_url='',ocr_url='',effort='low',review_effort=args.effort,
        compact_tools=True,review_responses=True,thinking=True,max_tokens=64000,max_calls=3,job_timeout=120,
        review_reserve_seconds=0,solve_max_tokens=0,review_max_tokens=0)
    source=Source.model_validate(json.loads((root/'source.json').read_text()))
    candidate=Candidate.model_validate(json.loads((root/'candidate.json').read_text()))
    request=json.loads((root/'request.json').read_text());request['ocr_evidence']=[]
    check_source(source,request['images']);check_candidate(candidate,source)
    if source.uncertainties:raise ValueError('原题仍有未决问题，不能以此诊断替代读题')
    expected,context=prepare_context(source,candidate,args.question)
    for item in request['images']:
        path=(root/item['file']).resolve()
        if path.parent!=root or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:
            raise ValueError('诊断图片路径或哈希不符')
        os.link(path,out/path.name)
    prompt=messages('review',request,out,context,compact=True)
    prompt[0]['content']+='\n本次为明确限定范围的数学复核诊断：仅对diagnostic_question_ids所列证明逐句审查，包括cases/domain_and_boundaries，questions只输出这些原编号；conditions仍检查全部，其他推导仅作待核上下文。没有声明inspect_scene，不作图形验收、不发布。未提供错误位置或标准裁决，须独立判断。'
    definitions=[t for t in DEFINITIONS if t['function']['name'] in {'algebra_batch','symbolic_geometry'}]
    image_tools=ImageTools(out,request['images'])
    if request['images']:definitions=definitions+[VIEW_REGION]
    def tool(name,values):return image_tools.view(**values) if name=='view_image_region' else dispatch(name,values)
    started=time.monotonic();records=[]
    def audit(kind,detail):
        row={'kind':kind,**copy.deepcopy(detail)}
        if 'seconds' in detail:row['duration_seconds']=detail['seconds']
        row['seconds']=round(time.monotonic()-started,3);records.append(row);write_json(out/'audit.json',records)
    provider=DeepSeek(cfg,audit);provider.shared_budget=ParallelBudget(3,timeout_seconds=120,max_concurrency=1)
    report={'status':'failed','end_to_end':False,'scope':context['diagnostic_scope'],'question_ids':context['diagnostic_question_ids'],
        'review_effort':args.effort,'max_tokens':64000,'max_calls':3,'timeout_seconds':120,
        'candidate_sha256':hashlib.sha256((root/'candidate.json').read_bytes()).hexdigest()}
    class DeadlineReached(BaseException):pass
    def deadline(*_):raise DeadlineReached('数学复核诊断120秒截止，未重发请求；未返回用量可能计费')
    signal.signal(signal.SIGALRM,deadline);signal.alarm(120)
    try:
        raw=receive(provider,'review',prompt,audit,tools=definitions,dispatch=tool,output_schema=output_schema(expected.model_dump()))
        write_json(out/'model-output.json',raw)
        review=unpack(raw,expected);check_review(review,expected)
        write_json(out/'review.json',review.model_dump())
        report.update(status='review_returned',verdict=review.verdict,issues=[x.model_dump() for x in review.issues],
            limitation='仅证明指定范围的模型复核返回，是否识别已知错误须人工核对；不得称整题通过')
    except (DeadlineReached,Exception) as exc:
        detail=str(exc)
        for secret in [cfg.api_key,cfg.access_token]:
            if secret:detail=detail.replace(secret,'[REDACTED]')
        report.update(error_type=type(exc).__name__,error=detail[:2000])
    finally:
        signal.alarm(0);provider.close();snapshot=provider.shared_budget.snapshot();write_json(out/'shared-budget.json',snapshot)
        report.update(seconds=round(time.monotonic()-started,3),calls=snapshot['calls'])
        usage=[r['usage'] for r in records if r['kind']=='model' and r.get('usage')]
        hit=sum(u.get('input_tokens_details',{}).get('cached_tokens',u.get('prompt_cache_hit_tokens',0)) or 0 for u in usage)
        total=sum(u.get('input_tokens',u.get('prompt_tokens',0)) or 0 for u in usage)
        output=sum(u.get('output_tokens',u.get('completion_tokens',0)) or 0 for u in usage)
        report.update(usage={'cached_input':hit,'uncached_input':max(0,total-hit),'output_including_reasoning':output},
            known_usage_cost_cny_estimate=round(args.price_multiplier*(hit*.02+max(0,total-hit)+output*4)/1_000_000,6),
            incomplete_usage=not snapshot['usage']['complete'],price_multiplier=args.price_multiplier)
        write_json(out/'result.json',report)
    print(json.dumps(report,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
