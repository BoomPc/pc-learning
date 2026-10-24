"""One explicit schema probe; no math acceptance and no automatic retry."""
import argparse,json,os,time
from dataclasses import replace
from pathlib import Path
import httpx
from jsonschema import validate
from math_agent.config import Settings
from math_agent.compact_review import output_schema,unpack
from math_agent.contracts import Source,check_review
from math_agent.responses_transport import body,message
from math_agent.storage import write_json
p=argparse.ArgumentParser()
for name in ('env','source','out'):p.add_argument('--'+name,type=Path,required=True)
p.add_argument('--contract',choices=['review','solve'],default='review')
p.add_argument('--price-multiplier',type=int,choices=[1,2],default=1)
a=p.parse_args();a.out.mkdir(parents=True,exist_ok=False)
for line in a.env.read_text().splitlines():
 if '=' in line and not line.startswith('#'):
  k,v=line.split('=',1);os.environ[k]=v
s=replace(Settings(),effort='high' if a.contract=='review' else 'low',max_tokens=32000 if a.contract=='review' else 512)
source=json.loads(a.source.read_text());schema=output_schema(source)
msgs=[{'role':'system','content':'这是JSON协议测试，不是数学审核。未提供原图和解答，不能声称已核验数学；verdict=needs_input，全部conditions/questions的verdict=unknown，evidence写“协议测试，未提供待审解答”，issues=[]。严格按给定Schema输出，保留所有编号。'},
 {'role':'user','content':json.dumps({'source':source},ensure_ascii=False)}]
if a.contract=='solve':
 from math_agent.compact_output import output_schema as solve_schema
 schema=solve_schema(source,require_basis=True)
 msgs=[{'role':'user','content':'这是请求格式兼容性探针，不是数学验收。只在输出额度内输出JSON，不声称已完成数学核验。'}]
request=body(s,msgs,schema,thinking=a.contract=='review',strict=a.contract=='solve');start=time.monotonic()
report={'scope':'native Responses JSON Schema compatibility probe; NOT math or end-to-end acceptance','contract':a.contract,
 'reasoning_effort':s.effort if a.contract=='review' else 'none','max_output_tokens':s.max_tokens,'max_requests':1,'status':'failed'}
try:
 with httpx.Client(timeout=httpx.Timeout(120,connect=15)) as client:
  r=client.post(s.base_url.rstrip('/')+'/responses',headers={'Authorization':'Bearer '+s.api_key},json=request)
 report['http_status']=r.status_code
 if r.status_code!=200:raise ValueError('HTTP '+str(r.status_code)+' '+r.text[:1000].replace(s.api_key,'[REDACTED]'))
 result=r.json();report['usage']=result.get('usage',{});report['model']=result.get('model');report['api_status']=result.get('status')
 if a.contract=='solve':
  report['status']='protocol_accepted'
  report['detail']='HTTP200仅证明完整解题Schema被接受；输出上限512token，允许截断，不解析为数学候选，不生成网页'
 else:
  msg,finish=message(result)
  if finish!='stop':raise ValueError('schema probe unexpectedly requested tools')
  raw=json.loads(msg['content']);validate(raw,schema)
  review=unpack(raw,Source.model_validate(source));check_review(review,Source.model_validate(source))
  if review.verdict!='needs_input' or any(x.verdict!='unknown' for x in review.conditions+review.questions):raise ValueError('probe incorrectly claimed math verification')
  write_json(a.out/'probe-output.json',raw);report['status']='pass';report['condition_count']=len(review.conditions);report['question_count']=len(review.questions)
except Exception as exc:report['error']=str(exc)
usage=report.get('usage') or {};total=usage.get('input_tokens',0);hit=usage.get('input_tokens_details',{}).get('cached_tokens',0)
report['known_usage_cost_cny_estimate']=(round(a.price_multiplier*(hit*.02+max(0,total-hit)+usage.get('output_tokens',0)*4)/1_000_000,6) if usage else None)
report['incomplete_usage']=not bool(usage);report['price_multiplier']=a.price_multiplier
report['seconds']=round(time.monotonic()-start,3);write_json(a.out/'result.json',report);print(json.dumps(report,ensure_ascii=False),flush=True)
