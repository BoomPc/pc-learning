"""Explicit new patch experiment from a saved candidate; never resumes the old job."""
import argparse,json,os,signal,time,hashlib
from dataclasses import replace
from pathlib import Path
from math_agent.config import Settings
from math_agent.contracts import Source,Candidate
from math_agent.pipeline import Runner
from math_agent.storage import Store,write_json
p=argparse.ArgumentParser()
for name in ('env','origin','candidate','out'):p.add_argument('--'+name,type=Path,required=True)
a=p.parse_args();a.out.mkdir(parents=True,exist_ok=False)
for line in a.env.read_text().splitlines():
 if '=' in line and not line.startswith('#'):
  k,v=line.split('=',1);os.environ[k]=v
settings=replace(Settings(),data_dir=a.out/'runtime',compact_tools=True,redis_url='',thinking=True,diagram_thinking=True,effort='high',max_tokens=32000,solve_max_tokens=0,review_max_tokens=0,review_reserve_seconds=0,max_calls=10,job_timeout=360)
store=Store(settings.data_dir);job,directory=store.prepare();store.enqueue(job);store.claim()
request=json.loads((a.origin/'request.json').read_text())
for img in request['images']:
 data=(a.origin/img['file']).read_bytes();assert hashlib.sha256(data).hexdigest()==img['sha256'];(directory/img['file']).write_bytes(data)
write_json(directory/'request.json',request)
source=Source.model_validate_json((a.origin/'source.json').read_text())
previous=Candidate.model_validate_json(a.candidate.read_text())
feedback=json.loads((a.origin/'model-07-review.json').read_text())['issues']
runner=Runner(settings,job);runner.save_ledger(source,previous)
start=time.monotonic();report={'scope':'saved candidate→patch→browser→independent review; NOT end-to-end','status':'failed','job_id':job}
def timeout(*_):raise TimeoutError('独立修图验收超过360秒')
signal.signal(signal.SIGALRM,timeout);signal.alarm(360)
try:
 candidate=runner.solve(source,feedback,previous,stage='diagram');write_json(directory/'candidate.json',candidate.model_dump());report['patch_seconds']=round(time.monotonic()-start,3)
 observation=runner.observe(candidate);report['render_done_seconds']=round(time.monotonic()-start,3)
 review=runner.review(source,candidate,observation);write_json(directory/'review.json',review.model_dump());report['status']=review.verdict
except Exception as exc:report['error']=str(exc)
finally:
 signal.alarm(0);runner.provider.close();report['seconds']=round(time.monotonic()-start,3);report['calls']=runner.provider.calls
 write_json(a.out/'result.json',report);print(json.dumps(report,ensure_ascii=False),flush=True)
