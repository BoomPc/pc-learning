"""One explicit paid source-review evaluation of archived Q20; no retries on transport errors."""
import json,os,shutil,time
from pathlib import Path
from math_agent.config import ROOT,Settings
from math_agent.contracts import Source
from math_agent.pipeline import Runner
from math_agent.source_review import check_reread,apply_reread
from math_agent.storage import Store,write_json
for line in (ROOT/'.env').read_text().splitlines():
    if '=' in line:
        key,value=line.split('=',1);os.environ[key]=value
settings=Settings(data_dir=ROOT/'evaluation/source-review/live-data',redis_url='',ocr_url='')
original=Path('/var/lib/math-agent-8666/jobs/jobs/857b614ea6f54ee0856fbf59bfc4f2b0')
source=Source.model_validate_json((original/'source.json').read_text())
store=Store(settings.data_dir);job,directory=store.prepare()
shutil.copy2(original/'input-01.png',directory/'input-01.png')
request={'text':'','images':[{'id':'I1','role':'question','file':'input-01.png'}],'force':True,'ocr_evidence':[]}
write_json(directory/'request.json',request);store.enqueue(job);store.claim()
runner=Runner(settings,job);start=time.monotonic()
issues=[{'id':f'U{i+1}','text':t} for i,t in enumerate(source.uncertainties)]
try:
    value=runner.validated('source_review',{'previous_source':source.model_dump(),'issues':issues},
        lambda raw:check_reread(raw,issues,request['images']),request_override=request)
    result=apply_reread(value,issues)
    report={'seconds':time.monotonic()-start,'model_calls':runner.provider.calls,
        'decisions':value.model_dump(),'remaining':result.uncertainties,'audit':runner.records,
        'scope':'真实模型独立核对原第20题误阻断；非整题生成'}
    write_json(ROOT/'evaluation/source-review/live-reread.json',report)
    print(json.dumps({'seconds':report['seconds'],'model_calls':report['model_calls'],'remaining':result.uncertainties,'decisions':[d.verdict for d in value.decisions]},ensure_ascii=False))
finally:runner.provider.close()
