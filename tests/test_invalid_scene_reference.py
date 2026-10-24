import copy
import json
import pytest
from math_agent.inspection_recovery import target,reconcile,partition_pending,reference_failure
from math_agent.scene_tools import SceneTools,fingerprint
from math_agent.rendering import strict_spec
from math_agent.contracts import Source,Candidate
from math_agent.pipeline import Runner,canonical_page
from test_pipeline import MemoryCache,renderer


def scene(sample):
    source=Source.model_validate(sample[0]);candidate=canonical_page(Candidate.model_validate(sample[1]),source)
    for tab in candidate.spec['tabs']:
        tab.pop('controls',None)
        tab['board']={'bounding_box':[-1,3,4,-1],'objects':[{'id':'O','kind':'point','coords':[0,0]},
            {'id':'P','kind':'point','coords':[1,1]},{'id':'l','kind':'line','parents':['O','P']}]}
    canonical_page(candidate,source)
    return source,candidate


@pytest.mark.parametrize('bad',['unknown_point','nonpoint_object','static_parameter'])
def test_reference_failure_never_runs_browser_or_silently_resolves_batch(tmp_path,sample,bad):
    _,candidate=scene(sample);spec=candidate.spec
    invalid={'tab':1,'checks':[{'relation':'equal_length','points':['O','C','O','D'],'expected':True}]}
    if bad=='nonpoint_object':invalid['checks'][0]['points']=['O','l','O','P']
    if bad=='static_parameter':invalid={'tab':1,'parameter':7,'checks':[{'relation':'same_y','points':['O','P']}]}
    legal={'tab':0,'checks':[{'relation':'same_x','points':['O','P']}]}
    args={'probes':[invalid,legal]};original=copy.deepcopy(args)
    tools=SceneTools(tmp_path/'observations');tools.current=spec
    result=tools.dispatch('inspect_scene',args)
    assert result['ok'] is False and tools.count==0 and not list(tmp_path.rglob('request.json'))
    assert args==original
    recovery=reconcile([{'result':result}],fingerprint(strict_spec(spec)))
    blocked,referred=partition_pending(recovery['unresolved'],spec)
    assert len(blocked)==len(referred)==1
    assert referred[0]['referral_reason']==('invalid_parameter' if bad=='static_parameter' else 'invalid_point_reference')
    assert referred[0]['target']==target(invalid,invalid['checks'][0],spec)
    assert blocked[0]['target']==target(legal,legal['checks'][0],spec)
    # A new valid query never retroactively deletes the invalid old one.
    good={'result':{'ok':True,'spec_sha256':fingerprint(strict_spec(spec)),
        'probes':[{'tab':0,'parameter':None,'in_domain':True,'checks':[{'relation':'same_x','points':['O','P'],'holds':False}]}]}}
    blocked,referred=partition_pending(reconcile([{'result':result},good],fingerprint(strict_spec(spec)))['unresolved'],spec)
    assert not blocked and len(referred)==1


def test_dynamic_out_of_range_is_invalid_but_known_undefined_geometry_and_unknown_tab_stay_blocked(sample):
    _,candidate=scene(sample);spec=candidate.spec
    # Use the real sample's valid controls, while keeping independent test points.
    spec['tabs'][0]['controls']=copy.deepcopy(next(t['controls'] for t in sample[1]['spec']['tabs'] if t.get('controls')))
    slider=spec['tabs'][0]['controls']['slider']
    q={'relation':'same_y','points':['O','P']}
    bad={'target':target({'tab':0,'parameter':slider['max']+1},q,spec)}
    blocked,referred=partition_pending([bad],spec)
    assert not blocked and referred[0]['referral_reason']=='invalid_parameter'
    runtime={'target':target({'tab':0,'parameter':slider['default']},q,spec),'error':'point undefined during native execution'}
    assert partition_pending([runtime],spec)[0]==[runtime]
    wrong_tab=copy.deepcopy(runtime);wrong_tab['target']['tab']=99
    assert partition_pending([wrong_tab],spec)[0]==[wrong_tab]


@pytest.mark.parametrize('verdict',['invalid_check','real_issue','unresolved'])
def test_invalid_reference_still_requires_independent_adjudication(settings,job,sample,verdict):
    source,candidate=scene(sample)
    stages=[]
    class Model:
        def __init__(self,settings,audit):self.audit=audit;self.calls=0
        def close(self):pass
        def generate(self,stage,messages,tools,dispatch):
            self.calls+=1;stages.append(stage)
            if stage=='review':
                args={'probes':[{'tab':0,'checks':[{'relation':'same_y','points':['O','missing'],
                    'expected':True,'basis_ids':['C1'],'rationale':'invalid test query must not pass'}]}]}
                result=dispatch('inspect_scene',args)
                self.audit('tool',{'stage':stage,'name':'inspect_scene','arguments':json.dumps(args),'result':result})
                return copy.deepcopy(sample[2])
            assert stage=='adjudicate'
            return {'decisions':[{'assertion_id':'A1','verdict':verdict,'basis_ids':['C1'],
                'reason':'The original query references a missing point; no measurement was obtained. This requires an explicit independent decision.',
                'issue':{'stage':'diagram','target':'Q1','detail':'separately confirmed genuine diagram issue'} if verdict=='real_issue' else None}],
                'reviewed':None}
    runner=Runner(settings,job[1],Model,MemoryCache,renderer)
    from math_agent.pipeline import NeedsInput
    if verdict=='unresolved':
        with pytest.raises(NeedsInput):runner.review(source,candidate,{})
    else:
        review=runner.review(source,candidate,{})
        assert review.verdict==('pass' if verdict=='invalid_check' else 'revise')
    assert stages==['review','adjudicate']
