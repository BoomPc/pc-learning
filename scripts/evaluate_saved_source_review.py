"""Explicit paid independent reread of a saved failure; never resumes its job."""
import argparse,json,os,shutil,time
from dataclasses import replace
from pathlib import Path
from math_agent.config import ROOT,Settings
from math_agent.contracts import Source
from math_agent.pipeline import Runner
from math_agent.source_review import check_reread,apply_reread
from math_agent.storage import Store,write_json
ap=argparse.ArgumentParser();ap.add_argument('--origin',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);args=ap.parse_args()
out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
for line in (ROOT/'.env').read_text().splitlines():
 if '=' in line and not line.startswith('#'):
  k,v=line.split('=',1);os.environ[k]=v
settings=replace(Settings(),data_dir=out/'runtime',redis_url='',ocr_url='',effort='low',max_calls=4)
source=Source.model_validate_json((args.origin/'source-before-reread.json').read_text())
request=json.loads((args.origin/'request.json').read_text());request['images']=[i for i in request['images'] if i['role']=='question'];request['ocr_evidence']=[]
store=Store(settings.data_dir);job,directory=store.prepare();store.enqueue(job);store.claim()
for img in request['images']:shutil.copyfile(args.origin/img['file'],directory/img['file'])
write_json(directory/'request.json',request)
runner=Runner(settings,job);start=time.monotonic();report={'scope':'independent source reread, not end-to-end','status':'failed'}
issues=[{'id':f'U{i+1}','text':s} for i,s in enumerate(source.uncertainties)]
try:
 value=runner.validated('source_review',{'previous_source':source.model_dump(),'issues':issues},lambda raw:check_reread(raw,issues,request['images']),request_override=request)
 result=apply_reread(value,issues);write_json(out/'resolution.json',value.model_dump())
 report.update(status='resolved' if not result.uncertainties else 'needs_input',remaining=result.uncertainties)
except Exception as exc:report.update(error=str(exc))
finally:
 runner.provider.close();report.update(seconds=round(time.monotonic()-start,3),calls=runner.provider.calls);write_json(out/'result.json',report);print(json.dumps(report,ensure_ascii=False))
