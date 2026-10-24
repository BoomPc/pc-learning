"""Fresh paid mathematics-only review; saved input, no prior review verdict or correction."""
import argparse, hashlib, json, os, signal, time
from dataclasses import replace
from pathlib import Path
from math_agent.config import Settings
from math_agent.contracts import Source, Candidate, Review, check_candidate, check_review
from math_agent.proof_dependencies import review_dependencies
from math_agent.pipeline import Runner
from math_agent.storage import Store, write_json

p=argparse.ArgumentParser();p.add_argument('--env',type=Path,required=True);p.add_argument('--origin',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
a.out.mkdir(parents=True,exist_ok=False)
for line in a.env.read_text().splitlines():
 if '=' in line and not line.startswith('#'):
  k,v=line.split('=',1);os.environ[k]=v
settings=replace(Settings(),data_dir=a.out/'runtime',redis_url='',ocr_url='',max_calls=8,effort='low',max_tokens=32000)
source=Source.model_validate_json((a.origin/'source.json').read_text())
candidate=Candidate.model_validate_json((a.origin/'candidate.json').read_text());check_candidate(candidate,source)
request=json.loads((a.origin/'request.json').read_text())
store=Store(settings.data_dir);job,directory=store.prepare();store.enqueue(job);store.claim()
for img in request['images']:
 data=(a.origin/img['file']).read_bytes();assert hashlib.sha256(data).hexdigest()==img['sha256'];(directory/img['file']).write_bytes(data)
write_json(directory/'request.json',request)
runner=Runner(settings,job);runner.save_ledger(source,candidate)
deps=review_dependencies(source,candidate.solutions);write_json(a.out/'dependencies.json',deps)
report={'scope':'saved candidate, independent math-only review with dependency context; no OCR/solve/draw, not end-to-end','status':'failed','candidate_sha256':hashlib.sha256((a.origin/'candidate.json').read_bytes()).hexdigest()}
start=time.monotonic()
def timeout(*_):
 report['deadline_hit']=True
 raise TimeoutError('240秒实验截止，没有自动重试')
signal.signal(signal.SIGALRM,timeout);signal.alarm(240)
def validate(raw):
 value=Review.model_validate(raw);check_review(value,source)
 if any(i.stage=='diagram' for i in value.issues):raise ValueError('数学核验未构图，不能输出diagram异议')
 return value
try:
 review=runner.validated('math_review',{'source':source.model_dump(),'math':{'solutions':[s.model_dump() for s in candidate.solutions]},'proof_dependencies':deps},validate)
 write_json(a.out/'review.json',review.model_dump());report['status']=review.verdict
except Exception as exc:
 detail=str(exc)
 for secret in (settings.api_key,settings.access_token):
  if secret:detail=detail.replace(secret,'[REDACTED]')
 report['error']=detail[:4000]
finally:
 signal.alarm(0);runner.provider.close();report.update(seconds=round(time.monotonic()-start,3),calls=runner.provider.calls)
 store.finish(job,'completed' if report['status']=='pass' else 'failed',error=report.get('error'))
 write_json(a.out/'result.json',report);print(json.dumps(report,ensure_ascii=False))
