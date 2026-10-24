"""Fresh outline→explanation→independent math review experiment; not a full image/page run."""
import argparse,hashlib,json,os,signal,time
from pathlib import Path
from dataclasses import replace
from math_agent.config import Settings
from math_agent.contracts import Source,Candidate,Review,check_review
from math_agent.math_outline import MathOutline,ExpandedMath,check_outline,check_expansion,OUTLINE_TASK,EXPAND_TASK
from math_agent.proof_dependencies import review_dependencies
from math_agent.provider import DeepSeek
from math_agent.pipeline import Runner
from math_agent.storage import Store,write_json
p=argparse.ArgumentParser();p.add_argument('--env',type=Path,required=True);p.add_argument('--origin',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--outline-model',choices=['deepseek-v4-pro','deepseek-flash'],default='deepseek-v4-pro');a=p.parse_args()
a.out.mkdir(parents=True,exist_ok=False)
for line in a.env.read_text().splitlines():
 if '=' in line and not line.startswith('#'):
  k,v=line.split('=',1);os.environ[k]=v
settings=replace(Settings(),data_dir=a.out/'runtime',redis_url='',ocr_url='',max_calls=12,effort='low',max_tokens=32000)
source=Source.model_validate_json((a.origin/'source.json').read_text());request=json.loads((a.origin/'request.json').read_text())
store=Store(settings.data_dir);job,directory=store.prepare();store.enqueue(job);store.claim()
for img in request['images']:
 data=(a.origin/img['file']).read_bytes();assert hashlib.sha256(data).hexdigest()==img['sha256'];(directory/img['file']).write_bytes(data)
write_json(directory/'request.json',request)
class ExperimentProvider(DeepSeek):
 def generate(self,stage,messages,tools=None,dispatch=None):
  messages=[dict(m) for m in messages]
  if stage in {'reference_math','math_repair'}:
   contract,task=(MathOutline,OUTLINE_TASK) if stage=='reference_math' else (ExpandedMath,EXPAND_TASK)
   messages[0]['content']=task+'\nJSON Schema：'+json.dumps(contract.model_json_schema(),ensure_ascii=False)
  tools=[] if stage=='math_repair' else [t for t in tools or [] if t['function']['name']!='read_evidence']
  return super().generate(stage,messages,tools,dispatch)
 def request(self,stage,history,tools=None,**kwargs):
  old=self.settings
  self.settings=replace(old,model=a.outline_model if stage=='reference_math' else 'deepseek-flash')
  kwargs.update(thinking_override=stage!='math_repair',json_mode=stage!='reference_math')
  try:return super().request(stage,history,tools,**kwargs)
  finally:self.settings=old
runner=Runner(settings,job,provider_factory=ExperimentProvider);runner.save_ledger(source)
text_request={**request,'images':[]};report={'scope':'verified saved source→compact outline→expanded math→fresh image-based math review; excludes OCR/drawing','status':'failed','outline_model':a.outline_model}
start=time.monotonic()
def deadline(*_):
 report['deadline_hit']=True
 raise TimeoutError('240秒实验截止，无自动重发')
signal.signal(signal.SIGALRM,deadline);signal.alarm(240)
try:
 outline=runner.validated('reference_math',{'source':source.model_dump()},lambda raw:check_outline(raw,source),request_override=text_request)
 write_json(a.out/'outline.json',outline.model_dump());report['outline_seconds']=round(time.monotonic()-start,3)
 if outline.uncertainties:
  report['status']='needs_input';report['uncertainties']=outline.uncertainties
 else:
  expanded=runner.validated('math_repair',{'source':source.model_dump(),'math_outline':outline.model_dump()},lambda raw:check_expansion(raw,source,outline),request_override=text_request)
  write_json(a.out/'expanded.json',expanded.model_dump());report['expanded_at_seconds']=round(time.monotonic()-start,3)
  candidate=Candidate(solutions=expanded.solutions,spec={});runner.save_ledger(source,candidate)
  def validate(raw):
   value=Review.model_validate(raw);check_review(value,source)
   if any(i.stage=='diagram' for i in value.issues):raise ValueError('数学阶段未构图，不能输出diagram异议')
   return value
  review=runner.validated('math_review',{'source':source.model_dump(),'math':{'solutions':[s.model_dump() for s in expanded.solutions]},
   'tool_evidence':[r for r in runner.records if r.get('kind')=='tool'],
   'proof_dependencies':review_dependencies(source,expanded.solutions)},validate)
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
