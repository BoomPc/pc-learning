import httpx,concurrent.futures,os,zipfile,time
from pathlib import Path
url='https://storage.googleapis.com/chrome-for-testing-public/156.0.8078.4/linux64/chrome-linux64.zip'
root=Path('/opt/math-agent-8666/browser-parts');root.mkdir(exist_ok=True)
with httpx.Client(proxy='http://127.0.0.1:7890',timeout=40) as c:
 r=c.head(url);r.raise_for_status();size=int(r.headers['content-length']);print('bytes',size,flush=True)
n=8; chunk=(size+n-1)//n

def download(i):
 base=i*chunk;end=min(size-1,base+chunk-1);path=root/str(i)
 existing=path.stat().st_size if path.exists() else 0
 start=base+existing
 if start>end: return
 with httpx.Client(proxy='http://127.0.0.1:7890',timeout=60) as c:
  with c.stream('GET',url,headers={'Range':f'bytes={start}-{end}'}) as r:
   assert r.status_code==206,(r.status_code,i)
   assert r.headers['content-range']==f'bytes {start}-{end}/{size}'
   with path.open('ab') as f:
    for b in r.iter_bytes():f.write(b)
 assert path.stat().st_size==end-base+1
 print('done',i,flush=True)
with concurrent.futures.ThreadPoolExecutor(max_workers=n) as pool:list(pool.map(download,range(n)))
archive=root/'chromium.zip'
with archive.open('wb') as f:
 for i in range(n):
  with (root/str(i)).open('rb') as part:
   while b:=part.read(1024*1024):f.write(b)
with zipfile.ZipFile(archive) as z:
 assert z.testzip() is None
 z.extractall('/opt/math-agent-8666/browser-manual')
for name in ['chrome','chrome_crashpad_handler','chrome_sandbox']:
 p=Path('/opt/math-agent-8666/browser-manual/chrome-linux64')/name
 if p.exists():p.chmod(0o755)
print('READY',flush=True)
