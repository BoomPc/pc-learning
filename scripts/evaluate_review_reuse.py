"""Explicit saved-review experiment with a controlled drawing mutation; no queue resume."""
import argparse,copy,hashlib,json,os,signal,time
from dataclasses import replace
from pathlib import Path
from math_agent.config import Settings
from math_agent.contracts import Source,Candidate,Review
from math_agent.pipeline import Runner
from math_agent.review_reuse import Snapshot
from math_agent.storage import Store,write_json
p=argparse.ArgumentParser()
for name in ('env','origin','out'):p.add_argument('--'+name,type=Path,required=True)
p.add_argument('--scenario',choices=['rotation_fault','harmless_edge'],required=True);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=False)
for line in a.env.read_text().splitlines():
 if '=' in line and not line.startswith('#'):
  k,v=line.split('=',1);os.environ[k]=v
settings=replace(Settings(),data_dir=a.out/'runtime',compact_tools=True,incremental_review=True,
 redis_url='',thinking=True,diagram_thinking=True,effort='high',max_tokens=32000,solve_max_tokens=0,review_max_tokens=0,review_reserve_seconds=0,max_calls=10,job_timeout=240)
store=Store(settings.data_dir);job,directory=store.prepare();store.enqueue(job);store.claim()
request=json.loads((a.origin/'request.json').read_text())
for img in request['images']:
 data=(a.origin/img['file']).read_bytes();assert hashlib.sha256(data).hexdigest()==img['sha256'];(directory/img['file']).write_bytes(data)
write_json(directory/'request.json',request)
source=Source.model_validate_json((a.origin/'source.json').read_text());previous=Candidate.model_validate_json((a.origin/'candidate.json').read_text());prior_review=Review.model_validate_json((a.origin/'review.json').read_text())
if prior_review.verdict!='pass':raise ValueError('只使用有完整pass的真实归档任务')
runner=Runner(settings,job);runner.save_ledger(source,previous);start=time.monotonic()
report={'scope':'saved genuine full review→controlled mutation→new browser→delta review, NOT end-to-end',
 'scenario':a.scenario,'status':'failed','job_id':job,'origin_job':a.origin.name}
def timeout(*_):raise TimeoutError('复用核验实验超过240秒')
signal.signal(signal.SIGALRM,timeout);signal.alarm(240)
try:
 old_observation=runner.observe(previous)
 runner.review_snapshot=Snapshot(source,previous,prior_review,old_observation,request,directory)
 runner.review_certificates=[{'sha256':runner.review_snapshot.certificate,'binding':runner.review_snapshot.binding,'review':prior_review.model_dump()}]
 runner.audit('explicit_reuse_experiment',{'origin_job':a.origin.name,'source_review_sha256':hashlib.sha256((a.origin/'review.json').read_bytes()).hexdigest(),
  'detail':'显式导入归档真实pass作为测试前提，非生产恢复入口；本实验不计为整题验收'})
 candidate=previous.model_copy(deep=True)
 if a.scenario=='rotation_fault':
  obj=next(o for o in candidate.spec['tabs'][0]['board']['objects'] if o['kind']=='rotation' and o['parents'][0]=='C')
  obj['direction']='counterclockwise' if obj['direction']=='clockwise' else 'clockwise'
 else:
  candidate.spec['tabs'][0]['board']['objects'].append({'id':'test_existing_edge','kind':'segment','parents':['A','B'],'visible':False})
 write_json(directory/'candidate.json',candidate.model_dump())
 observation=runner.observe(candidate)
 review=runner.review(source,candidate,observation);write_json(directory/'review.json',review.model_dump())
 report['verdict']=review.verdict;report['issues']=[i.model_dump() for i in review.issues]
 report['status']='pass' if ((a.scenario=='rotation_fault' and review.verdict=='revise' and any(i.stage=='diagram' for i in review.issues)) or
    (a.scenario=='harmless_edge' and review.verdict=='pass')) else 'failed'
except Exception as exc:report['error']=str(exc)
finally:
 signal.alarm(0);runner.provider.close();report.update(seconds=round(time.monotonic()-start,3),calls=runner.provider.calls)
 write_json(a.out/'result.json',report);print(json.dumps(report,ensure_ascii=False),flush=True)
