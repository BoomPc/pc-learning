import copy,json,os
from pathlib import Path
import pytest
from math_agent.contracts import Source,Candidate
from math_agent.pipeline import Runner,NeedsInput,canonical_page
from math_agent.rotation_probe import prepare,evaluate
from test_pipeline import MemoryCache,renderer


def data():
    source=Source(title='旋转证明前提',problem_text='三角形绕A旋转，探索对应弦长的比。',
        conditions=[{'id':'C1','text':'AB=AD=3，AC=AE=5，D/E是B/C绕A同角旋转的点。','origin':'question_text','image_ids':[]}],
        questions=[{'id':'Q1','text':'证明BD/CE=3/5，并核对边界。'}],reference_summary='',uncertainties=[])
    solution={'question_id':'Q1','result':'BD/CE=3/5','steps':[{'premise':'△ADB与△AEC中，两组边成比例且夹角相等。',
        'rule':'两边成比例且夹角相等的两个三角形相似','conclusion':'△ADB∽△AEC。','basis_ids':['C1']}],
        'condition_ids':['C1'],'cases':[],'domain_and_boundaries':'非重合位置上述相似关系成立。'}
    spec={'format':'jsxgraph-v1','title':source.title,'problem_text':source.problem_text,'tabs':[{'tab_title':'旋转',
        'board':{'viewport':'fit_points','axis':False,'objects':[
            {'id':'A','kind':'point','coords':[0,0]}, {'id':'B','kind':'point','coords':[0,-3]}, {'id':'C','kind':'point','coords':[4,-3]},
            {'id':'D','kind':'rotation','parents':['B','A'],'degrees':90,'direction':'counterclockwise'},
            {'id':'E','kind':'rotation','parents':['C','A'],'degrees':90,'direction':'counterclockwise'}]},
        'steps':[],'conclusion':''}]}
    c=canonical_page(Candidate(solutions=[solution],spec=spec),source)
    r={'verdict':'pass','conditions':[{'id':'C1','verdict':'pass','evidence':'离线夹具的原题转写核对'}],
       'questions':[{'id':'Q1','verdict':'pass','evidence':'模拟复核忽略退化前提'}],'issues':[]}
    args={'tab':0,'step_id':'Q1:S1','rotation_ids':['D','E'],'angles':[90,180],
          'triangles':[['A','D','B'],['A','E','C']],'rationale':'检查作者相似步骤是否遗漏旋转半周的共线位置。'}
    return source,c,r,args


def fake_collinear(spec,probes,directory,timeout):
    return {'ok':True,'probes':[{'tab':0,'parameter':None,'checks':[
        {'holds':True,'points':x['points'],'observed':{p:[0,0] for p in x['points']}} for x in probes[0]['checks']]}]}


@pytest.mark.parametrize('bad',['partial','free_point','wrong_step','not_declared','wrong_rule','slider','extra','too_many'])
def test_scope_cannot_manufacture_a_counterexample_by_partial_edit_or_unbound_claim(tmp_path,bad):
    s,c,r,a=data()
    if bad=='partial':a['rotation_ids']=['D']
    elif bad=='free_point':a['rotation_ids']=['A']
    elif bad=='wrong_step':a['step_id']='Q2:S1'
    elif bad=='not_declared':a['triangles']=[['B','C','D']]
    elif bad=='wrong_rule':c.solutions[0].steps[0].rule='直接写答案'
    elif bad=='slider':c.spec['tabs'][0]['controls']={'slider':{'min':0,'max':360,'default':90}}
    elif bad=='extra':a['spec']={}
    else:a['angles']=[0,45,90,180,360]
    with pytest.raises(ValueError):evaluate(c,a,tmp_path,observe=lambda *x:pytest.fail('参数无效不得启动浏览器'))


def test_variant_receipts_are_bound_and_candidate_proof_drawing_remain_unchanged(tmp_path):
    s,c,r,a=data();old=c.model_dump()
    result=evaluate(c,a,tmp_path,observe=fake_collinear)
    assert c.model_dump()==old and len(result['observations'])==2 and len(result['counterexamples'])==4
    assert all(f['basis_ids']==['Q1:S1'] for f in result['counterexamples'])
    assert result['observations'][1]['original_spec_sha256']!=result['observations'][1]['case_spec_sha256']
    assert (tmp_path/'result.json').is_file()


def test_observation_failure_is_explicitly_unknown_not_a_counterexample_or_pass(tmp_path):
    s,c,r,a=data()
    result=evaluate(c,a,tmp_path,observe=lambda *x:{'ok':False,'error':'browser not available'})
    assert not result['ok'] and len(result['unobserved'])==2 and not result['counterexamples']


@pytest.mark.skipif(os.getenv('MATH_AGENT_BROWSER_TEST')!='1',reason='原生旋转实际观察')
@pytest.mark.parametrize('rename',[False,True])
def test_actual_native_180_degree_degeneracy_without_renaming_math_or_default_drawing(tmp_path,rename):
    s,c,r,a=data()
    if rename:
        objects=c.spec['tabs'][0]['board']['objects'];mapping={o['id']:'node'+str(i) for i,o in enumerate(objects)}
        for o in objects:
            old=o['id'];o['id']=mapping[old];o['label']=old
            if 'parents' in o:o['parents']=[mapping[p] for p in o['parents']]
        a['rotation_ids']=[mapping[p] for p in a['rotation_ids']]
        a['triangles']=[[mapping[p] for p in row] for row in a['triangles']]
    old=c.model_dump();result=evaluate(c,a,tmp_path)
    assert result['ok'] and not result['unobserved'] and c.model_dump()==old
    assert len(result['counterexamples'])==2
    assert all(f['case_evidence']['angle_degrees']==180 for f in result['counterexamples'])
    assert all(not x.get('error') for row in result['observations'] for p in row['observation']['probes'] for x in p['checks'])


@pytest.mark.parametrize('outcome',['real_issue','unresolved','already_reported','unobserved'])
def test_agent_selected_evidence_enters_existing_gate_and_cannot_be_silently_passed(settings,job,monkeypatch,outcome):
    import math_agent.rotation_probe as rp
    s,c,r,a=data();a['angles']=[180];a['triangles']=[a['triangles'][0]];stages=[]
    real_evaluate=rp.evaluate
    observer=(lambda *x:{'ok':False,'error':'no native observation'}) if outcome=='unobserved' else fake_collinear
    monkeypatch.setattr(rp,'evaluate',lambda cand,args,path:real_evaluate(cand,args,path,observe=observer))
    monkeypatch.setattr('math_agent.proof_guards.collect',lambda *x:{'failures':[],'observations':[],'unobserved':[]})
    class Model:
        calls=0
        def __init__(self,settings,audit):self.audit=audit
        def generate(self,stage,messages,**kw):
            self.calls+=1;stages.append(stage)
            context=json.loads(messages[-1]['content'][0]['text'])['context']
            if stage=='review':
                assert 'probe_rotation_rule' in [t['function']['name'] for t in kw['tools']]
                result=kw['dispatch']('probe_rotation_rule',a)
                self.audit('tool',{'stage':stage,'name':'probe_rotation_rule','arguments':json.dumps(a),'result':result})
                if outcome=='already_reported':
                    value=copy.deepcopy(r);value.update(verdict='revise',issues=[{'stage':'math','target':'Q1:S1','detail':'旋转180°相似前提需要独立验证'}]);return value
                return r
            assert stage=='adjudicate'
            f=context['failed_assertions'][0];assert f['kind']=='proof_guard'
            decision='unresolved' if outcome in {'unresolved','unobserved'} else 'real_issue'
            return {'decisions':[{'assertion_id':f['id'],'verdict':decision,'basis_ids':['Q1:S1'],
                'reason':'离线模拟独立裁决保留实际反例或未知义务，不以默认图正常与长度比成立代替相似证明。',
                'issue':{'stage':'math','target':'Q1:S1','detail':'180°相似退化，需补写独立共线位置证明。'} if decision=='real_issue' else None}]}
    runner=Runner(settings,job[1],Model,MemoryCache,renderer)
    if outcome in {'unresolved','unobserved'}:
        with pytest.raises(NeedsInput):runner.review(s,c,{})
    else:
        value=runner.review(s,c,{})
        assert value.verdict=='revise' and value.issues[0].stage=='math'
        if outcome=='already_reported':assert runner.deferred_reviews.pending
    assert stages==(['review'] if outcome=='already_reported' else ['review','adjudicate'])


def test_timed_out_native_query_terminates_only_its_own_browser_group(tmp_path,monkeypatch):
    import math_agent.rotation_probe as rp
    killed=[];waits=[]
    class Process:
        pid=12345;returncode=-9
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def wait(self,timeout=None):
            waits.append(timeout)
            if timeout is not None:raise rp.subprocess.TimeoutExpired('own-child',timeout)
    def popen(*a,**kw):
        assert kw['start_new_session'] is True
        assert kw['cwd']==rp.ROOT
        return Process()
    monkeypatch.setattr(rp.subprocess,'Popen',popen)
    monkeypatch.setattr(rp.os,'killpg',lambda pid,sig:killed.append((pid,sig)))
    value=rp.native_observe({},[],tmp_path,0.01)
    assert not value['ok'] and killed==[(12345,rp.signal.SIGKILL)] and waits==[0.01,None]


@pytest.mark.parametrize('error',[KeyboardInterrupt,TimeoutError])
def test_external_cancellation_reaps_browser_and_propagates_without_returning_a_pass(tmp_path,monkeypatch,error):
    import math_agent.rotation_probe as rp
    killed=[]
    class Process:
        pid=12346
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def wait(self,timeout=None):
            if timeout is not None:raise error('external cancellation')
    monkeypatch.setattr(rp.subprocess,'Popen',lambda *a,**kw:Process())
    monkeypatch.setattr(rp.os,'killpg',lambda pid,sig:killed.append((pid,sig)))
    with pytest.raises(error):rp.native_observe({},[],tmp_path,1)
    assert killed==[(12346,rp.signal.SIGKILL)]
