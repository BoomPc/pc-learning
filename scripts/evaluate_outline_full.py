"""Explicit isolated full-image test; no resume, no production configuration changes."""
import argparse, hashlib, json, os, signal, time
from dataclasses import replace
from pathlib import Path
from math_agent.config import Settings
from math_agent.storage import Store, write_json
from math_agent.outline_agent import OutlineProvider, OutlineRunner

p=argparse.ArgumentParser()
for name in ('env','origin','out'): p.add_argument('--'+name,type=Path,required=True)
modes=p.add_mutually_exclusive_group()
modes.add_argument('--split',action='store_true')
modes.add_argument('--transcript',action='store_true')
a=p.parse_args();a.out=a.out.resolve();a.out.mkdir(parents=True,exist_ok=False)
for line in a.env.read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k,v=line.split('=',1);os.environ[k]=v
settings=replace(Settings(),data_dir=a.out/'runtime',redis_url='',reference_mode=True,
    solve_draft=False,review_plan=False,model='deepseek-flash',thinking=True,effort='low',
    max_calls=12,max_tokens=32000,job_timeout=240)
if not settings.ocr_url: raise ValueError('完整实验必须配置真实OCR')
request=json.loads((a.origin/'request.json').read_text());request.pop('ocr_evidence',None);request['force']=True
store=Store(settings.data_dir);job,directory=store.prepare()
for img in request['images']:
    data=(a.origin/img['file']).read_bytes()
    assert hashlib.sha256(data).hexdigest()==img['sha256']
    (directory/img['file']).write_bytes(data)
write_json(directory/'request.json',request);store.enqueue(job);assert store.claim()==job
report={'job_id':job,'scope':'fresh images→OCR→source→outline→expansion→independent math review→native drawing→graph review; excludes HTTP upload','deadline_hit':False}
write_json(a.out/'config.json',{'model':settings.model,'effort':settings.effort,'timeout':240,'max_calls':12,'workflow':'outline-reference'})
if a.transcript:
    from math_agent.reference_transcript import TranscriptRunner, TranscriptProvider
    runner=TranscriptRunner(settings,job,provider_factory=TranscriptProvider)
elif a.split:
    from math_agent.split_outline import SplitOutlineRunner, SplitOutlineProvider
    runner=SplitOutlineRunner(settings,job,provider_factory=SplitOutlineProvider)
else:
    runner=OutlineRunner(settings,job,provider_factory=OutlineProvider)
report['split_questions']=a.split
report['reference_transcript']=a.transcript
start=time.monotonic()
def deadline(*_):
    report['deadline_hit']=True
    raise TimeoutError('240秒完整实验截止；不自动重发')
signal.signal(signal.SIGALRM,deadline);signal.alarm(240)
try: runner.run()
finally:
    signal.alarm(0)
    row=store.get(job)
    report.update(status=row['status'],error=row['error'],seconds=round(time.monotonic()-start,3),calls=runner.provider.calls)
    report['ocr']=[{k:r.get(k) for k in ('image_id','cache_hit','elapsed_seconds')} for r in runner.records if r['kind']=='ocr' and r.get('status')=='done']
    write_json(a.out/'result.json',report);print(json.dumps(report,ensure_ascii=False))
