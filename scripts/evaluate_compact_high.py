"""Explicit compact-high Linux experiment in a separate store; no resume/retry."""
import argparse,os,json,hashlib,sys,time
from pathlib import Path
from math_agent.config import Settings
from math_agent.storage import Store,write_json
from math_agent.worker import supervise
p=argparse.ArgumentParser();p.add_argument('--env',type=Path,required=True);p.add_argument('--origin',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--timeout',type=int);p.add_argument('--responses-review',action='store_true');p.add_argument('--max-tokens',type=int);p.add_argument('--effort',choices=('low','high','max'));a=p.parse_args()
a.out.mkdir(parents=True,exist_ok=False)
for line in a.env.read_text().splitlines():
 if '=' in line and not line.startswith('#'):
  k,v=line.split('=',1);os.environ[k]=v
profile=Path(__file__).resolve().parents[1]/'deploy/profiles/compact-high.env'
for line in profile.read_text().splitlines():
 if '=' in line and not line.startswith('#'):
  k,v=line.split('=',1);os.environ[k]=v
if a.effort is not None:os.environ['DEEPSEEK_REASONING_EFFORT']=a.effort
if a.responses_review:os.environ['AGENT_REVIEW_RESPONSES']='true'
if a.max_tokens is not None:os.environ['DEEPSEEK_MAX_TOKENS']=str(a.max_tokens)
if a.timeout is not None:os.environ['AGENT_JOB_TIMEOUT']=str(a.timeout)
os.environ.update(AGENT_DATA_DIR=str((a.out/'runtime').resolve()),REDIS_URL='')
settings=Settings()
def balance():
 import httpx
 try:
  r=httpx.get(settings.base_url.rstrip('/')+'/user/balance',headers={'Authorization':'Bearer '+settings.api_key},timeout=20)
  if r.status_code!=200:return {'status':r.status_code}
  return r.json()
 except httpx.HTTPError as exc:return {'error':type(exc).__name__}
write_json(a.out/'balance-before.json',balance())
store=Store(settings.data_dir);job,directory=store.prepare()
request=json.loads((a.origin/'request.json').read_text());request.pop('ocr_evidence',None);request['force']=True
for img in request['images']:
 data=(a.origin/img['file']).read_bytes();assert hashlib.sha256(data).hexdigest()==img['sha256'];(directory/img['file']).write_bytes(data)
write_json(directory/'request.json',request);store.enqueue(job);assert store.claim()==job
write_json(a.out/'config.json',{'workflow':'compact-classic','model':settings.model,'effort':settings.effort,'max_tokens':settings.max_tokens,'review_responses':settings.review_responses,'timeout':settings.job_timeout,'solve_max_tokens':settings.solve_max_tokens,'review_max_tokens':settings.review_max_tokens,'review_reserve_seconds':settings.review_reserve_seconds,'scope':'fresh images→OCR→source→solve+native JSXGraph→browser observation→combined review; separate store, no HTTP upload measurement'})
(a.out/'job-id.txt').write_text(job);print('job',job,flush=True);start=time.monotonic();last=None
def heartbeat():
 global last
 row=store.get(job);state=(row['status'],row['stage'])
 if state!=last:print(round(time.monotonic()-start,1),*state,flush=True);last=state
supervise(settings,store,job,lambda:False,heartbeat)
row=store.get(job);write_json(a.out/'result.json',{'status':row['status'],'error':row['error'],'seconds':round(time.monotonic()-start,3),'job_id':job});print(row['status'],row['error'],flush=True)

write_json(a.out/'balance-after.json',balance())
