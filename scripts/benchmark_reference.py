"""One explicitly requested full API run. No paid retries or auto-resume."""
import json,os,sys,time
from pathlib import Path
from contextlib import ExitStack
import httpx
from math_agent.config import ROOT
case,label=sys.argv[1:3]
assert case in {'20','48','52'} and label.replace('-','').isalnum()
out=ROOT/'evaluation/reference-v1'/label;out.mkdir(parents=True,exist_ok=False)
for line in (ROOT/'.env').read_text().splitlines():
 if '=' in line:
  k,v=line.split('=',1);os.environ[k]=v
write=lambda name,value:(out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2))
write('config.json',{k:os.getenv(k) for k in ['DEEPSEEK_MODEL','DEEPSEEK_REASONING_EFFORT','DEEPSEEK_MAX_TOKENS','AGENT_REFERENCE_MODE','AGENT_JOB_TIMEOUT']})
with httpx.Client(timeout=30,trust_env=False,headers={'Authorization':'Bearer '+os.environ['AGENT_ACCESS_TOKEN']}) as client:
 client.get('http://127.0.0.1:8666/readyz').raise_for_status()
 with ExitStack() as stack:
  q=ROOT/'fixtures'/f'{case}.png';answers=sorted((ROOT/'fixtures').glob(f'ref-{case}-answer-*.png'))
  assert answers
  files=[('question',(q.name,stack.enter_context(q.open('rb')),'image/png'))]
  files += [('answer',(a.name,stack.enter_context(a.open('rb')),'image/png')) for a in answers]
  started=time.monotonic();response=client.post('http://127.0.0.1:8666/api/jobs',data={'force':'true'},files=files)
 response.raise_for_status();job=response.json()['id'];(out/'job-id.txt').write_text(job);print('job',job,flush=True)
 last=None
 while time.monotonic()-started<320:
  response=client.get('http://127.0.0.1:8666/api/jobs/'+job);response.raise_for_status();row=response.json()
  state=(row['status'],row['stage'])
  if state!=last:print(round(time.monotonic()-started,1),*state,flush=True);last=state
  if row['status'] in {'completed','failed','needs_input','cancelled','interrupted'}:break
  time.sleep(2)
 write('status.json',row)
 directory=Path(os.environ['AGENT_DATA_DIR'])/'jobs'/job
 for name in ['audit.json','report.json','source.json','candidate.json','math-draft.json','math-review.json','graph-review.json','source-question-review.json']:
  if (directory/name).exists():(out/name).write_bytes((directory/name).read_bytes())
 if row['status']=='completed':
  for name in ['result.html','export-check.json']:
   if (directory/'output'/name).exists():(out/name).write_bytes((directory/'output'/name).read_bytes())
  for p in (directory/'output').glob('tab-*.png'):(out/p.name).write_bytes(p.read_bytes())
 print('final',row['status'],row.get('error'),flush=True)
