"""Explicit paid independent review of a saved candidate. No source/solve replay."""
import argparse,json,os,shutil,time,hashlib,signal
from dataclasses import replace
from pathlib import Path
from math_agent.config import ROOT,Settings
from math_agent.contracts import Source,Candidate
from math_agent.pipeline import Runner
from math_agent.storage import Store,write_json
ap=argparse.ArgumentParser();ap.add_argument('--origin',type=Path,required=True);ap.add_argument('--images',type=Path,required=True);ap.add_argument('--candidate',type=Path,required=True);ap.add_argument('--model',default='deepseek-flash');ap.add_argument('--thinking-off',action='store_true');ap.add_argument('--review-plan',action='store_true');ap.add_argument('--env',type=Path,default=ROOT/'.env');ap.add_argument('--native',action='store_true');ap.add_argument('--out',type=Path,required=True);args=ap.parse_args()
out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
for line in args.env.read_text().splitlines():
 if '=' in line and not line.startswith('#'):
  k,v=line.split('=',1);os.environ[k]=v
settings=replace(Settings(),review_plan=args.review_plan,model=args.model,thinking=not args.thinking_off,data_dir=out/'runtime',redis_url='',ocr_url='',effort='low',max_tokens=64000 if args.native else 32000,max_calls=10,job_timeout=240,compact_tools=args.native,review_responses=args.native,reference_mode=False,solve_draft=False,incremental_review=False,solve_max_tokens=0,review_max_tokens=0,review_reserve_seconds=0)
request=json.loads((args.origin/'request.json').read_text());source=Source.model_validate_json((args.origin/'source.json').read_text());previous=Candidate.model_validate_json(args.candidate.read_text());feedback=json.loads((args.origin/'review.json').read_text())['issues'] if (args.origin/'review.json').exists() else []
store=Store(settings.data_dir);job,directory=store.prepare();store.enqueue(job);store.claim()
for img in request['images']:
 data=(args.images/img['file']).read_bytes();assert hashlib.sha256(data).hexdigest()==img['sha256'];(directory/img['file']).write_bytes(data)
write_json(directory/'request.json',request)
runner=Runner(settings,job);from math_agent.pipeline import canonical_page
canonical_page(previous,source,runner.audit)
runner.save_ledger(source,previous);start=time.monotonic();report={'scope':'saved candidate, real render and review; not end-to-end','status':'failed','model':args.model,'thinking':not args.thinking_off,'job_id':job,'effort':settings.effort,'max_tokens':settings.max_tokens}
def deadline(*_):
 report['deadline_hit']=True
 raise TimeoutError('独立复核实验达到240秒截止，未自动重发请求')
signal.signal(signal.SIGALRM,deadline);signal.alarm(240)
try:
 candidate=previous;runner.pending_math_objections=feedback;write_json(out/'candidate.json',candidate.model_dump());report['repair_seconds']=round(time.monotonic()-start,3)
 observation=runner.observe(candidate);review=runner.review(source,candidate,observation);write_json(out/'review.json',review.model_dump());report['status']=review.verdict;report['issues']=[i.model_dump() for i in review.issues]
except Exception as exc:report['error']=str(exc)
finally:
 signal.alarm(0);runner.provider.close();report.update(seconds=round(time.monotonic()-start,3),calls=runner.provider.calls);store.finish(job,'completed' if report['status']=='pass' else 'failed',error=report.get('error'));write_json(out/'result.json',report);print(json.dumps(report,ensure_ascii=False))
