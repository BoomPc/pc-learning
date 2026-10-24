"""Explicit paid regression on saved Q48 data, not a generated/public lesson.

Two controlled cases: false parallelism expectation and a real displaced vertex.
Does not edit the source job or cache results. Run in the service environment.
"""
import copy,json,shutil,sys,time
from dataclasses import replace
from pathlib import Path
from math_agent.config import Settings
from math_agent.contracts import Source,Candidate
from math_agent.pipeline import Runner
from math_agent.storage import Store,write_json

settings=Settings();origin=Store(settings.data_dir).path(sys.argv[1])
out=Path(sys.argv[2]);out.mkdir(parents=True,exist_ok=True)
source=Source.model_validate(json.loads((origin/'source.json').read_text()))
base=Candidate.model_validate(json.loads((origin/'candidate.json').read_text()))
request=json.loads((origin/'request.json').read_text());request['force']=True
summary=[]
for name,expected in [('false_parallel','invalid_check'),('displaced_vertex','real_issue')]:
    config=replace(settings,data_dir=out/name,max_calls=6)
    store=Store(config.data_dir);job,directory=store.prepare()
    for img in request['images']:
        dest=directory/img['file'];dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(origin/img['file'],dest)
    write_json(directory/'request.json',request)
    candidate=copy.deepcopy(base)
    if name=='displaced_vertex':
        point=next(o for o in candidate.spec['tabs'][0]['board']['objects'] if o['id']=='Bp')
        # Intentionally faulty fixture; never change the original job or a production diagram.
        point.clear();point.update(id='Bp',kind='point',coords=[-1.3320508075688773,3],label='B′')
        check={'relation':'collinear','points':['Bp','C','Cp'],'expected':True,'basis_ids':['C5'],
               'rationale':'本小问题文明说B′C′经过C，必须共线'}
    else:
        check={'relation':'parallel','points':['B','C','Bp','Cp'],'expected':True,'basis_ids':['C3'],
               'rationale':'待审查的错误假设：旋转会使对应边平行'}
    runner=Runner(config,job);runner.review_candidate=candidate;runner.save_ledger(source,candidate)
    try:
        observation=runner.observe(candidate)
        result=runner.scenes.dispatch('inspect_scene',{'probes':[{'tab':0,'checks':[check]}]})
        write_json(directory/'injected-check.json',result)
        failed=result['probes'][0]['checks'][0]
        assert result['ok'] and failed['matches_expected'] is False
        decisions=runner.adjudicate(source,candidate,observation,[{'id':'A1','tab':0,'parameter':None,'check':failed}])
        actual=decisions.decisions[0].verdict
        summary.append({'case':name,'expected':expected,'actual':actual,'passed':actual==expected and (expected!='real_issue' or decisions.decisions[0].issue.stage=='diagram'),
                        'model_calls':runner.provider.calls,'seconds':round(time.monotonic()-runner.started,3),
                        'decision':decisions.model_dump(),'audit':runner.records})
    except Exception as exc:
        summary.append({'case':name,'passed':False,'error':str(exc),'model_calls':runner.provider.calls,'audit':runner.records})
    finally:runner.provider.close()
    write_json(out/'summary.json',summary)
    print(name,summary[-1].get('actual',summary[-1].get('error')),flush=True)
if not all(s['passed'] for s in summary):sys.exit(1)
