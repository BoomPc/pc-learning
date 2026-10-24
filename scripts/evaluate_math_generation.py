"""Fresh paid mathematics generation; saved source and original answer images, no gold solution."""
import argparse, hashlib, json, os, signal, time
from dataclasses import replace
from pathlib import Path
from math_agent.config import Settings
from math_agent.contracts import Source
from math_agent.provider import DeepSeek
from math_agent.reference_flow import validate_math, MathDraft
from math_agent.pipeline import Runner
from math_agent.storage import Store, write_json

p=argparse.ArgumentParser();p.add_argument('--env',type=Path,required=True);p.add_argument('--origin',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--model',required=True);p.add_argument('--thinking',choices=['off','low'],default='off');p.add_argument('--text-only',action='store_true');p.add_argument('--no-json-mode',action='store_true');a=p.parse_args()
a.out.mkdir(parents=True,exist_ok=False)
for line in a.env.read_text().splitlines():
 if '=' in line and not line.startswith('#'):
  k,v=line.split('=',1);os.environ[k]=v
settings=replace(Settings(),data_dir=a.out/'runtime',redis_url='',ocr_url='',max_calls=8,effort='low',max_tokens=32000,model=a.model)
source=Source.model_validate_json((a.origin/'source.json').read_text())
request=json.loads((a.origin/'request.json').read_text())
store=Store(settings.data_dir);job,directory=store.prepare();store.enqueue(job);store.claim()
for img in request['images']:
 data=(a.origin/img['file']).read_bytes();assert hashlib.sha256(data).hexdigest()==img['sha256'];(directory/img['file']).write_bytes(data)
if a.text_only:request={**request,'images':[]}
write_json(directory/'request.json',request)
class ExperimentProvider(DeepSeek):
 def generate(self,stage,messages,tools=None,dispatch=None):
  if a.text_only:
   messages=[dict(m) for m in messages]
   messages[0]['content']='你是受限的初中数学解题Agent。输入为已核实题设source，本轮不提供图片或参考答案。独立解答全部小问，保留初中可理解的完整推导、分类与边界。不假装看到图片或答案，不使用没有声明的图示条件。只输出solutions，不生成图。每步basis_ids只能用C编号或先前Qn:Sm；跨问引用必须说明条件仍成立。可用代数工具核验；涉及旋转平移坐标时，优先用symbolic_geometry精确构造并测量，避免手算旋转坐标。坐标系须与原题顺逆时针及点线条件相容，镜像会改变方向；工具只计算你给定的坐标，不证明坐标选得正确。不得用答案数值替代证明。返回单个JSON，遵守Schema：'+json.dumps(MathDraft.model_json_schema(),ensure_ascii=False)
  return super().generate(stage,messages,tools,dispatch)
 def request(self,stage,history,tools=None,**kwargs):
  kwargs['thinking_override']=a.thinking=='low'
  kwargs['json_mode']=not a.no_json_mode
  return super().request(stage,history,tools,**kwargs)
runner=Runner(settings,job,provider_factory=ExperimentProvider);runner.save_ledger(source)
report={'scope':'saved verified source and original images, fresh math generation; no OCR/review/draw, not end-to-end','status':'failed','model':a.model,'thinking':a.thinking,'text_only':a.text_only,'json_mode':not a.no_json_mode,'source_sha256':hashlib.sha256((a.origin/'source.json').read_bytes()).hexdigest()}
if a.text_only:report['scope']='verified source text only, independent solve; excludes OCR, images, reference answer, review and drawing'
start=time.monotonic()
def timeout(*_):
 report['deadline_hit']=True
 raise TimeoutError('240秒实验截止，没有自动重试')
signal.signal(signal.SIGALRM,timeout);signal.alarm(240)
try:
 draft=runner.validated('reference_math',{'source':source.model_dump(),'previous':None,'feedback':[]},lambda raw:validate_math(raw,source))
 write_json(a.out/'math-draft.json',draft.model_dump());report['status']='structured_output'
except Exception as exc:
 detail=str(exc)
 for secret in (settings.api_key,settings.access_token):
  if secret:detail=detail.replace(secret,'[REDACTED]')
 report['error']=detail[:4000]
finally:
 signal.alarm(0);runner.provider.close();report.update(seconds=round(time.monotonic()-start,3),calls=runner.provider.calls)
 store.finish(job,'completed' if report['status']=='structured_output' else 'failed',error=report.get('error'))
 write_json(a.out/'result.json',report);print(json.dumps(report,ensure_ascii=False))
