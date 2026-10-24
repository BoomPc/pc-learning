import copy
import json
import os
import pytest
from math_agent.scene_tools import probe_scene, INSPECT
from math_agent.pipeline import Runner
from math_agent.storage import write_json
from test_pipeline import MemoryCache, provider, renderer


def test_browser_observation_is_given_to_reviewer(settings, job, sample):
    source,candidate,review = sample
    queued=[source,candidate,review]; observed=[]
    class Model:
        def __init__(self,settings,audit): self.calls=0
        def generate(self,stage,messages,**kwargs):
            self.calls+=1
            if stage=='review':
                observed.append(json.loads(messages[1]['content'][0]['text'])['context']['browser_observation'])
                assert 'inspect_scene' in [d['function']['name'] for d in kwargs['tools']]
                assert 'preview_scene' not in [d['function']['name'] for d in kwargs['tools']]
            return copy.deepcopy(queued.pop(0))
        def close(self): pass
    Runner(settings,job[1],Model,MemoryCache,renderer).run()
    assert observed[0]['status']=='pass'
    assert job[0].get(job[1])['status']=='completed'
    report=json.loads((job[2]/'report.json').read_text())
    assert [r['node'] for r in report['audit'] if r['kind']=='graph_node']==['source','solve','observe','review']


@pytest.mark.parametrize('tool_result',[{'ok':False,'error':'观察失败'},{'ok':True,'assertions_pass':False,'error':'P/M横坐标不相等'}])
def test_failed_real_inspection_cannot_be_overridden_by_model_pass(settings,job,sample,tool_result):
    from dataclasses import replace
    source,candidate,review=sample;queued=[source,candidate,review,review]
    class Model:
        def __init__(self,settings,audit):self.calls=0;self.audit=audit
        def generate(self,stage,*args,**kwargs):
            self.calls+=1
            if stage=='review':self.audit('tool',{'stage':stage,'name':'inspect_scene','result':tool_result})
            return copy.deepcopy(queued.pop(0))
        def close(self):pass
    Runner(replace(settings,max_repairs=0),job[1],Model,MemoryCache,renderer).run()
    assert job[0].get(job[1])['status']=='failed'
    assert '真实图形工具' in job[0].get(job[1])['error']


def test_missing_browser_report_stops_publication(settings,job,sample):
    from dataclasses import replace
    def no_evidence(spec,directory,**kw):directory.mkdir(exist_ok=True)
    stages=[]
    Runner(replace(settings,max_repairs=0),job[1],provider(list(sample),stages),MemoryCache,no_evidence).run()
    assert stages==['source','solve']
    assert job[0].get(job[1])['status']=='failed'


@pytest.mark.skipif(os.getenv('MATH_AGENT_BROWSER_TEST')!='1',reason='真实浏览器测试')
def test_observe_vertical_is_not_perpendicular_to_slanted_line(tmp_path):
    spec={'format':'jsxgraph-v1','title':'关系测试','problem_text':'PM应竖直','tabs':[{
        'tab_title':'关系','steps':[{'head':'条件','content':'PM竖直'}],'conclusion':'检查',
        'board':{'bounding_box':[-2,6,6,-2],'axis':True,'objects':[
            {'id':'B','kind':'point','coords':[3,0]},{'id':'C','kind':'point','coords':[0,3]},
            {'id':'P','kind':'point','coords':[1.5,3.75]}, {'id':'BC','kind':'line','parents':['B','C']},
            {'id':'wrong','kind':'perpendicular','parents':['BC','P']},
            {'id':'M','kind':'intersection','parents':['BC','wrong'],'branch':0}]}}]}
    result=probe_scene(spec,[{'tab':0,'checks':[
        {'relation':'same_x','points':['P','M']},
        {'relation':'same_x','points':['P','M'],'expected':False},
        {'relation':'same_x','points':['P','M'],'expected':True}]}],tmp_path)
    assert result['ok'] and not result['assertions_pass']
    checks=result['probes'][0]['checks']
    assert checks[0]['holds'] is False and checks[0]['matches_expected'] is None
    assert checks[1]['matches_expected'] is True and checks[2]['matches_expected'] is False
    assert result['probes'][0]['points']['M']==pytest.approx([.375,2.625])
    assert result['probes'][0]['checks'][0]['observed']['P']==[1.5,3.75]


@pytest.mark.skipif(os.getenv('MATH_AGENT_BROWSER_TEST')!='1',reason='真实浏览器测试')
def test_boundary_near_endpoint_fails_even_if_deciles_pass(tmp_path):
    from math_agent.jsxgraph.export import export
    from math_agent.rendering import strict_spec
    # Undefined only beyond .9; open endpoint previously skipped by uniform decile checks.
    spec={'format':'jsxgraph-v1','title':'边界','problem_text':'观察','tabs':[{
        'tab_title':'边界','steps':[{'head':'条件','content':'0<t<1'}],'conclusion':'观察',
        'controls':{'slider':{'min':0,'max':1,'default':.5,'min_inclusive':False,'max_inclusive':False},'solution_targets':[],'jump_buttons':[]},
        'board':{'bounding_box':[-2,2,2,-2],'axis':True,'objects':[{'id':'P','kind':'point','coords':['t','sqrt(0.95-t)']}]}}]}
    with pytest.raises(ValueError,match='无定义'):export(strict_spec(spec),tmp_path)
    failure=json.loads((tmp_path/'observation-failure.json').read_text())
    assert failure['parameter']>.95 and failure['undefined']==['P']


def test_scene_sequence_survives_explicit_resume(tmp_path):
    from math_agent.scene_tools import SceneTools
    (tmp_path/'scene-01').mkdir();(tmp_path/'scene-03').mkdir()
    assert SceneTools(tmp_path).count==3
