"""Explicit paid correction+review experiment. Not a resume or end-to-end run."""
import argparse,json,os,shutil,time,hashlib,signal
from dataclasses import replace
from pathlib import Path
from math_agent.config import ROOT,Settings
from math_agent.contracts import Source,Candidate
from math_agent.pipeline import Runner
from math_agent.provider import DeepSeek
from math_agent.storage import Store,write_json
ap=argparse.ArgumentParser();ap.add_argument('--origin',type=Path,required=True);ap.add_argument('--images',type=Path,required=True);ap.add_argument('--candidate',type=Path,required=True);ap.add_argument('--history',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);args=ap.parse_args()
out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
for line in (ROOT/'.env').read_text().splitlines():
 if '=' in line and not line.startswith('#'):
  k,v=line.split('=',1);os.environ[k]=v
settings=replace(Settings(),data_dir=out/'runtime',redis_url='',ocr_url='',effort='low',max_tokens=32000,max_calls=10)
request=json.loads((args.origin/'request.json').read_text());source=Source.model_validate_json((args.origin/'source.json').read_text());previous=Candidate.model_validate_json(args.candidate.read_text());feedback=json.loads((args.origin/'review.json').read_text())['issues']
store=Store(settings.data_dir);job,directory=store.prepare();store.enqueue(job);store.claim()
for img in request['images']:
 data=(args.images/img['file']).read_bytes();assert hashlib.sha256(data).hexdigest()==img['sha256'];(directory/img['file']).write_bytes(data)
write_json(directory/'request.json',request)
history=json.loads((args.history/'audit.json').read_text())
archived_review=json.loads(sorted(args.history.glob('model-*-review.json'))[-1].read_text())
class ReplayReview(DeepSeek):
 def generate(self,stage,messages,**kwargs):
  if stage!='review':return super().generate(stage,messages,**kwargs)
  self.audit('historical_review_replay',{'stage':stage,'detail':'原失败的复核工具记录及最终JSON原样重放；本阶段不计模型调用'})
  for item in history:
   if item.get('kind')=='tool' and item.get('stage')=='review' and item.get('name')=='inspect_scene':
    self.audit('tool',{k:v for k,v in item.items() if k not in {'kind','seconds'}})
  return archived_review
runner=Runner(settings,job,provider_factory=ReplayReview);runner.save_ledger(source,previous);start=time.monotonic();report={'scope':'historical review replay + new paid independent adjudication; not end-to-end','status':'failed'}
def deadline(*_):raise TimeoutError('独立复核实验达到240秒截止，未自动重发请求')
signal.signal(signal.SIGALRM,deadline);signal.alarm(240)
try:
 candidate=previous;runner.pending_math_objections=feedback;write_json(out/'candidate.json',candidate.model_dump());report['repair_seconds']=round(time.monotonic()-start,3)
 observation=runner.observe(candidate);review=runner.review(source,candidate,observation);write_json(out/'review.json',review.model_dump());report['status']=review.verdict
except Exception as exc:report['error']=str(exc)
finally:
 signal.alarm(0);runner.provider.close();report.update(seconds=round(time.monotonic()-start,3),calls=runner.provider.calls);write_json(out/'result.json',report);print(json.dumps(report,ensure_ascii=False))
