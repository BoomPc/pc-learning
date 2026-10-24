import copy
import json
import os
import pytest
from jsonschema import validate, ValidationError
from math_agent.scene_tools import PREVIEW, preview_page, probe_scene
from math_agent.pipeline import review_payload, canonical_page
from math_agent.contracts import Candidate, Source


def test_preview_contract_resolves_nested_geometry_and_rejects_bad_references(sample):
    minimal={'tabs':[{'board':sample[1]['spec']['tabs'][0]['board']}]}
    # This example has dynamic expressions; preserve controls for faithful validation.
    if 'controls' in sample[1]['spec']['tabs'][0]:
        minimal['tabs'][0]['controls']=sample[1]['spec']['tabs'][0]['controls']
    args={'spec':minimal,'probes':[{'tab':0,'checks':[]}]}
    validate(args,PREVIEW['function']['parameters'])
    before=copy.deepcopy(minimal)
    page=preview_page(minimal)
    from math_agent.jsxgraph.spec import Board
    assert page['tabs'][0]['board']==Board.model_validate(minimal['tabs'][0]['board']).model_dump(exclude_none=True)
    assert minimal==before
    bad=copy.deepcopy(args);bad['spec']['tabs'][0]['board']['objects'][0]['kind']='run_shell'
    with pytest.raises(ValidationError):validate(bad,PREVIEW['function']['parameters'])


def test_review_compaction_keeps_math_checks_and_original(sample):
    candidate=canonical_page(Candidate.model_validate(sample[1]),Source.model_validate(sample[0]))
    original=candidate.model_dump()
    records=[{'name':'preview_scene','arguments':json.dumps({'spec':original['spec'],'probes':[{'tab':0,'checks':[]}]}),
        'result':{'ok':False,'error':'failed geometry','probes':[{'holds':False}]}}]
    compact,evidence=review_payload(candidate,records)
    assert compact['solutions']==original['solutions']
    assert compact['spec']['tabs'][0]['board']==original['spec']['tabs'][0]['board']
    assert 'steps' not in compact['spec']['tabs'][0]
    assert evidence[0]['result']==records[0]['result']
    assert 'draft_spec_sha256' in json.loads(evidence[0]['arguments'])
    assert candidate.model_dump()==original and 'spec' in json.loads(records[0]['arguments'])


@pytest.mark.skipif(os.getenv('MATH_AGENT_BROWSER_TEST')!='1',reason='真实浏览器')
def test_minimal_preview_observes_native_midpoint(tmp_path):
    spec={'tabs':[{'board':{'bounding_box':[-1,3,5,-1],'objects':[
        {'id':'A','kind':'point','coords':[0,0]}, {'id':'B','kind':'point','coords':[4,2]},
        {'id':'M','kind':'midpoint','parents':['A','B']}]}}]}
    result=probe_scene(preview_page(spec),[{'tab':0,'checks':[{'relation':'collinear','points':['A','M','B'],'expected':True}]}],tmp_path)
    assert result['ok'] and result['assertions_pass']
    assert result['probes'][0]['points']['M']==pytest.approx([2,1])
