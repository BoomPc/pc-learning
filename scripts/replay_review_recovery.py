"""Replay saved Q36 reviewer decisions through actual validation/browser, no model API."""
import json
from pathlib import Path
from math_agent.config import Settings, ROOT
from math_agent.contracts import Source, Candidate
from math_agent.pipeline import Runner, route
from math_agent.storage import Store, write_json

out=ROOT/'evaluation/recovery-fix'
prior=ROOT/'evaluation/preview-agent'
records=[r for r in json.loads((prior/'report.json').read_text())['audit'] if r.get('name')=='inspect_scene']
source=Source.model_validate_json((out/'source-36.json').read_text())
candidate=Candidate.model_validate_json((prior/'candidate.json').read_text())
review=json.loads((prior/'model-12-review.json').read_text())
settings=Settings(data_dir=out/'replay-data',api_key='no-network-replay',access_token='x'*40,redis_url='',ocr_url='')
store=Store(settings.data_dir);job,directory=store.prepare()
write_json(directory/'request.json',{'text':'存档复核重放','images':[],'force':True})
store.enqueue(job);store.claim()
class Replay:
    def __init__(self,settings,audit):self.calls=0;self.audit=audit
    def close(self):pass
    def generate(self,stage,messages,tools,dispatch):
        assert stage=='review'
        for old in records:
            args=json.loads(old['arguments'])
            result=dispatch('inspect_scene',args)
            self.audit('tool',{'stage':stage,'name':'inspect_scene','arguments':json.dumps(args),'result':result})
        return review
runner=Runner(settings,job,provider_factory=Replay)
try:
    result=runner.review(source,candidate,{'status':'pass','scope':'archived candidate; actual checks rerun'})
    recovery=[r for r in runner.records if r['kind']=='inspection_recovery'][-1]
    assert result.verdict=='revise' and route(result)=='diagram'
    assert len(recovery['resolved'])==1 and not recovery['unresolved']
    assert result.issues==__import__('math_agent.contracts',fromlist=['Review']).Review.model_validate(review).issues
    write_json(out/'replay-result.json',{'status':'pass','scope':'保存的模型决策重放，真实浏览器重新检查；不是新付费模型生成验收',
        'route':route(result),'review':result.model_dump(),'recovery':recovery,'audit':runner.records})
    store.finish(job,'completed',summary={'scope':'offline replay only'})
    print(json.dumps({'status':'pass','route':route(result),'resolved':len(recovery['resolved']),'retained_issues':len(result.issues)}))
finally:
    runner.provider.close()
