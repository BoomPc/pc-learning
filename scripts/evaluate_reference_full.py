"""Explicit full Linux reference-flow experiment in a separate store; no resume/retry."""
import argparse,os,json,hashlib,sys,time
from pathlib import Path
from math_agent.config import Settings
from math_agent.storage import Store,write_json
from math_agent.worker import supervise
p=argparse.ArgumentParser();p.add_argument('--env',type=Path,required=True);p.add_argument('--origin',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
a.out.mkdir(parents=True,exist_ok=False)
for line in a.env.read_text().splitlines():
 if '=' in line and not line.startswith('#'):
  k,v=line.split('=',1);os.environ[k]=v
os.environ.update(AGENT_DATA_DIR=str((a.out/'runtime').resolve()),REDIS_URL='',AGENT_REFERENCE_MODE='true',AGENT_REVIEW_PLAN='false',AGENT_SOLVE_DRAFT='false',AGENT_JOB_TIMEOUT='240')
settings=Settings();store=Store(settings.data_dir);job,directory=store.prepare()
request=json.loads((a.origin/'request.json').read_text());request.pop('ocr_evidence',None);request['force']=True
for img in request['images']:
 data=(a.origin/img['file']).read_bytes();assert hashlib.sha256(data).hexdigest()==img['sha256'];(directory/img['file']).write_bytes(data)
write_json(directory/'request.json',request);store.enqueue(job);assert store.claim()==job
write_json(a.out/'config.json',{'workflow':'reference','model':settings.model,'effort':settings.effort,'timeout':settings.job_timeout,'scope':'fresh images→OCR→source→math→independent math review→native JSXGraph→graph review; separate store, no HTTP upload measurement'})
(a.out/'job-id.txt').write_text(job);print('job',job,flush=True);start=time.monotonic();last=None
def heartbeat():
 global last
 row=store.get(job);state=(row['status'],row['stage'])
 if state!=last:print(round(time.monotonic()-start,1),*state,flush=True);last=state
supervise(settings,store,job,lambda:False,heartbeat)
row=store.get(job);write_json(a.out/'result.json',{'status':row['status'],'error':row['error'],'seconds':round(time.monotonic()-start,3),'job_id':job});print(row['status'],row['error'],flush=True)
