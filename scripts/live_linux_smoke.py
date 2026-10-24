"""One explicitly authorized real task on the deployed host. Never retries paid requests."""
import json,time,os
from pathlib import Path
import httpx
root=Path('/opt/math-agent-8666'); out=root/'live-evidence';out.mkdir(exist_ok=True)
for line in (root/'.env').read_text().splitlines():
    if '=' in line:
        k,v=line.split('=',1);os.environ[k]=v
with httpx.Client(timeout=30,trust_env=False,headers={'Authorization':'Bearer '+os.environ['AGENT_ACCESS_TOKEN']}) as c:
    for attempt in range(10):
        try:
            ready=c.get('http://127.0.0.1:8666/readyz')
            if ready.status_code == 200: break
        except httpx.ConnectError: pass
        time.sleep(2)
    else: raise RuntimeError('service not ready; no job submitted')
    ready.raise_for_status()
    (out/'ready.json').write_text(json.dumps(ready.json(),ensure_ascii=False,indent=2))
    with (root/'fixtures/48.png').open('rb') as q, (root/'fixtures/48答案.png').open('rb') as a:
        r=c.post('http://127.0.0.1:8666/api/jobs',data={'force':'true'},files=[('question',('48.png',q,'image/png')),('answer',('48答案.png',a,'image/png'))])
    r.raise_for_status();job=r.json()['id'];(out/'job-id.txt').write_text(job);print('job',job,flush=True)
    start=time.monotonic(); last=None
    while time.monotonic()-start<1900:
        row=c.get('http://127.0.0.1:8666/api/jobs/'+job).json()
        state=(row['status'],row['stage'])
        if state!=last:print(round(time.monotonic()-start,1),*state,flush=True);last=state
        if row['status'] in {'completed','failed','needs_input','cancelled','interrupted'}:break
        time.sleep(3)
    (out/'status.json').write_text(json.dumps(row,ensure_ascii=False,indent=2))
    for name in ['report.json','ocr.json','result.html','preview.png']:
        r=c.get('http://127.0.0.1:8666/api/jobs/'+job+'/artifacts/'+name)
        if r.status_code==200:(out/name).write_bytes(r.content)
    print('final',row['status'],row.get('error'),flush=True)
