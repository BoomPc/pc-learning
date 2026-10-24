"""Run on deployed host; no paid model calls. Preserve real OCR outputs/timings."""
import json, os, time
from pathlib import Path
import httpx
root=Path('/opt/math-agent-8666')
for line in (root/'.env').read_text().splitlines():
    if '=' in line:
        k,v=line.split('=',1);os.environ[k]=v
out=root/'ocr-evidence';out.mkdir(exist_ok=True)
summary=[]
with httpx.Client(timeout=300,trust_env=False,headers={'Authorization':'Bearer '+os.environ['AGENT_ACCESS_TOKEN']}) as client:
    for name in ['16.png','36.png','48.png','48答案.png']:
        start=time.monotonic()
        with (root/'fixtures'/name).open('rb') as image:
            response=client.post('http://127.0.0.1:18666/recognize',files={'image':(name,image,'image/png')})
        elapsed=round(time.monotonic()-start,3)
        record={'image':name,'http':response.status_code,'seconds':elapsed}
        if response.status_code==200:
            data=response.json();(out/(name+'.json')).write_text(json.dumps(data,ensure_ascii=False,indent=2))
            record.update(cache_hit=data['cache_hit'],blocks=len(data['blocks']),formulas=sum(b['kind']=='formula' for b in data['blocks']),text_chars=len(data['text']))
        else: record['error']=response.text[:300]
        summary.append(record);print(json.dumps(record,ensure_ascii=False),flush=True)
        (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
