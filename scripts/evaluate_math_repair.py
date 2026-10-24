"""Explicit paid correction+review experiment. Not a resume or end-to-end run."""
import argparse,json,os,shutil,time,hashlib
from dataclasses import replace
from pathlib import Path
from math_agent.config import ROOT,Settings
from math_agent.contracts import Source,Candidate
from math_agent.pipeline import Runner
from math_agent.storage import Store,write_json
ap=argparse.ArgumentParser();ap.add_argument('--origin',type=Path,required=True);ap.add_argument('--images',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);args=ap.parse_args()
out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
for line in (ROOT/'.env').read_text().splitlines():
 if '=' in line and not line.startswith('#'):
  k,v=line.split('=',1);os.environ[k]=v
settings=replace(Settings(),data_dir=out/'runtime',redis_url='',ocr_url='',effort='low',max_tokens=32000,max_calls=10)
request=json.loads((args.origin/'request.json').read_text());source=Source.model_validate_json((args.origin/'source.json').read_text());previous=Candidate.model_validate_json((args.origin/'candidate.json').read_text());feedback=json.loads((args.origin/'review.json').read_text())['issues']
store=Store(settings.data_dir);job,directory=store.prepare();store.enqueue(job);store.claim()
for img in request['images']:
 data=(args.images/img['file']).read_bytes();assert hashlib.sha256(data).hexdigest()==img['sha256'];(directory/img['file']).write_bytes(data)
write_json(directory/'request.json',request)
runner=Runner(settings,job);runner.save_ledger(source,previous);start=time.monotonic();report={'scope':'saved source/candidate correction, render and review; not end-to-end','status':'failed'}
try:
 candidate=runner.repair_math(source,previous,feedback);write_json(out/'candidate.json',candidate.model_dump());report['repair_seconds']=round(time.monotonic()-start,3)
 observation=runner.observe(candidate);review=runner.review(source,candidate,observation);write_json(out/'review.json',review.model_dump());report['status']=review.verdict
except Exception as exc:report['error']=str(exc)
finally:
 runner.provider.close();report.update(seconds=round(time.monotonic()-start,3),calls=runner.provider.calls);write_json(out/'result.json',report);print(json.dumps(report,ensure_ascii=False))
