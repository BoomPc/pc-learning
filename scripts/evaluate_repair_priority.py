"""Explicit one-cycle paid diagnostic after replaying an archived real review.

NOT end-to-end: no OCR/source/solve HTTP replay. New paid calls start at math_repair.
"""
import argparse,copy,hashlib,json,os,signal,time
from dataclasses import replace
from pathlib import Path
import httpx
from math_agent.config import Settings
from math_agent.contracts import Source,Candidate
from math_agent.provider import DeepSeek
from math_agent.pipeline import Runner
from math_agent.flow import execute_graph
from math_agent.storage import Store,write_json

p=argparse.ArgumentParser()
for name in ('env','origin','out'):p.add_argument('--'+name,type=Path,required=True)
p.add_argument('--guard-from-pass',action='store_true');p.add_argument('--candidate',type=Path);p.add_argument('--review',type=Path)
a=p.parse_args();a.out=a.out.resolve();a.out.mkdir(parents=True,exist_ok=False)
for line in a.env.read_text().splitlines():
 if '=' in line and not line.startswith('#'):
  k,v=line.split('=',1);os.environ[k]=v
s=replace(Settings(),data_dir=a.out/'runtime',redis_url='',reference_mode=False,review_plan=False,solve_draft=False,
 compact_tools=True,review_responses=True,incremental_review=True,thinking=True,diagram_thinking=True,
 effort='low',max_tokens=64000,solve_max_tokens=0,review_max_tokens=0,review_reserve_seconds=0,
 job_timeout=240,max_calls=8 if a.guard_from_pass else 12,max_repairs=1)
store=Store(s.data_dir);job,directory=store.prepare();store.enqueue(job);store.claim()
request=json.loads((a.origin/'request.json').read_text());request['force']=True
for img in request['images']:
 data=(a.origin/img['file']).read_bytes()
 if hashlib.sha256(data).hexdigest()!=img['sha256']:raise ValueError('原图哈希不匹配')
 (directory/img['file']).write_bytes(data)
write_json(directory/'request.json',request)
source=Source.model_validate_json((a.origin/'source.json').read_text())
candidate=Candidate.model_validate_json((a.candidate or a.origin/'candidate.json').read_text())
review_file=a.review or next(a.origin.glob('model-*-review.json'))
review_raw=json.loads(review_file.read_text())
if a.guard_from_pass:
 from math_agent.contracts import Review
 prior_value=Review.model_validate(review_raw)
 if prior_value.verdict!='pass':raise ValueError('反例诊断要求真实归档pass作为待挑战前提')
 reviewed_candidate=Candidate.model_validate_json((review_file.parent/'candidate.json').read_text())
 if reviewed_candidate!=candidate:raise ValueError('归档pass不属于待检查候选，不能导入')
 review_raw={**prior_value.model_dump(),'conditions':{v.id:v.model_dump(exclude={'id'}) for v in prior_value.conditions},
  'questions':{v.id:v.model_dump(exclude={'id'}) for v in prior_value.questions}}

records=json.loads((a.origin/'audit.json').read_text())
inspections=[r for r in records if r['kind']=='tool' and r.get('stage')=='review' and r.get('name')=='inspect_scene']
class ImportedFirstReview:
 def __init__(self,settings,audit):self.real=DeepSeek(settings,audit);self.audit=audit;self.imported=False
 @property
 def calls(self):return self.real.calls
 def close(self):self.real.close()
 def generate(self,stage,*args,**kwargs):
  if not self.imported:
   if stage!='review':raise ValueError('导入仅限第一次review')
   self.imported=True
   for r in inspections:self.audit('tool',{k:v for k,v in r.items() if k not in ('kind','seconds')})
   self.audit('archived_review_import',{'origin_job':a.origin.name,'review_sha256':hashlib.sha256(review_file.read_bytes()).hexdigest(),
    'detail':'原真实复核与工具记录只做离线导入；未发出付费HTTP请求，不能计为本次模型产出'})
   return copy.deepcopy(review_raw)
  return self.real.generate(stage,*args,**kwargs)
def balance():
 try:
  r=httpx.get(s.base_url.rstrip('/')+'/user/balance',headers={'Authorization':'Bearer '+s.api_key},timeout=20)
  return r.json() if r.status_code==200 else {'status':r.status_code}
 except httpx.HTTPError as exc:return {'error':type(exc).__name__}
write_json(a.out/'balance-before.json',balance())
runner=Runner(s,job,ImportedFirstReview);started=time.monotonic()
report={'scope':'saved actual failure→math repair→new browser→independent review→deferred checks; NOT end-to-end',
 'status':'failed','job_id':job,'origin_job':a.origin.name,'effort':s.effort,'max_tokens':s.max_tokens,'calls':0,'guard_from_pass':a.guard_from_pass}
def timeout(*_):raise TimeoutError('纠错闭环诊断240秒截止；未自动重发，已发请求可能计费')
signal.signal(signal.SIGALRM,timeout);signal.alarm(s.job_timeout)
try:
 prior=runner.review(source,candidate,runner.observe(candidate) if a.guard_from_pass else json.loads((a.origin/'observation-01.json').read_text()))
 if prior.verdict!='revise' or not any(i.stage=='math' for i in prior.issues) or (not a.guard_from_pass and not runner.deferred_reviews.pending):
  raise ValueError('原真实失败没有形成预期的数学异议与暂存检查；不启动付费诊断')
 if not a.guard_from_pass:assert runner.provider.calls==0
 report['initial_verdict']=prior.model_dump()
 print('guard/referral ready; starting ONE new correction cycle',job,flush=True)
 state=execute_graph(runner,{'entry':'math_repair','source':source,'candidate':candidate,'repairs':1,
    'observation':{},'feedback':[i.model_dump() for i in prior.issues]})
 if state['review'].verdict!='pass' or runner.deferred_reviews.pending:raise ValueError('复核或暂存义务未完成')
 write_json(directory/'review.json',state['review'].model_dump())
 write_json(directory/'candidate.json',state['candidate'].model_dump())
 report['status']='pass';report['review']=state['review'].model_dump()
except Exception as exc:
 detail=str(exc)
 for secret in (s.api_key,s.access_token):
  if secret:detail=detail.replace(secret,'[REDACTED]')
 report['error']=detail[:4000]
finally:
 signal.alarm(0);runner.provider.close();report.update(seconds=round(time.monotonic()-started,3),calls=runner.provider.calls,
  pending=len(runner.deferred_reviews.pending))
 write_json(a.out/'result.json',report)
 store.finish(job,'completed' if report['status']=='pass' else 'failed',error=report.get('error'))
 write_json(a.out/'balance-after.json',balance())
 print(json.dumps(report,ensure_ascii=False),flush=True)
