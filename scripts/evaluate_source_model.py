"""Explicit isolated paid source experiment with saved OCR; never resumes a job."""
import argparse,json,os,shutil,time
from dataclasses import replace
from pathlib import Path
from math_agent.config import ROOT,Settings
from math_agent.pipeline import Runner
from math_agent.storage import Store,write_json
ap=argparse.ArgumentParser();ap.add_argument('--origin',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);ap.add_argument('--model',required=True);ap.add_argument('--source-max-tokens',type=int,default=8000);args=ap.parse_args()
out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
for line in (ROOT/'.env').read_text().splitlines():
 if '=' in line and not line.startswith('#'):
  k,v=line.split('=',1);os.environ[k]=v
settings=replace(Settings(),model=args.model,source_max_tokens=args.source_max_tokens,data_dir=out/'runtime',redis_url='',ocr_url='',effort='low',max_tokens=32000,max_calls=6)
request=json.loads((args.origin/'request.json').read_text());request['images']=[i for i in request['images'] if i['role']=='question'];request['ocr_evidence']=json.loads((args.origin/'ocr.json').read_text())
store=Store(settings.data_dir);job,directory=store.prepare();store.enqueue(job);store.claim()
for img in request['images']:shutil.copyfile(args.origin/img['file'],directory/img['file'])
write_json(directory/'request.json',request)
runner=Runner(settings,job);start=time.monotonic();report={'scope':'source only, saved OCR, excludes OCR runtime','model':args.model,'status':'failed'}
try:
 source=runner.extract();write_json(out/'source.json',source.model_dump());report['status']='source_pass'
except Exception as exc:report['error']=str(exc)
finally:
 runner.provider.close();report.update(seconds=round(time.monotonic()-start,3),calls=runner.provider.calls);write_json(out/'result.json',report);print(json.dumps(report,ensure_ascii=False))
