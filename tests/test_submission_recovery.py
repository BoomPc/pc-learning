import copy
import json
from dataclasses import replace
import pytest
from math_agent.contracts import Source,Candidate
from math_agent.submission import decode,SubmissionError,patch_schema,apply_patch
from math_agent.jsxgraph.spec import Board
from math_agent.pipeline import Runner
from test_compact_tools import pack
from test_compact_review import pack_review
from test_pipeline import provider,MemoryCache,renderer


def test_named_view_converts_without_changing_coordinates(sample):
    raw=copy.deepcopy(sample[1]['spec']['tabs'][0]['board']);old=copy.deepcopy(raw['objects'])
    raw.pop('bounding_box',None);raw['view']={'x_min':-3,'x_max':7,'y_min':-4,'y_max':11}
    board=Board.model_validate(raw).model_dump(exclude_none=True)
    assert board['bounding_box']==[-3,11,7,-4] and 'view' not in board
    assert [o['id'] for o in board['objects']]==[o['id'] for o in old]


@pytest.mark.parametrize('extra',[
    {'view':{'x_min':3,'x_max':-3,'y_min':0,'y_max':5}},
    {'view':{'x_min':-3,'x_max':3,'y_min':5,'y_max':0}},
    {'view':{'x_min':-3,'x_max':3,'y_min':0,'y_max':5},'bounding_box':[-3,5,3,0]},
])
def test_named_view_rejects_invalid_or_conflicting_ranges(sample,extra):
    raw=copy.deepcopy(sample[1]['spec']['tabs'][0]['board']);raw.pop('bounding_box',None);raw.update(extra)
    with pytest.raises(ValueError):Board.model_validate(raw)


def test_collects_both_proof_and_each_board_error_atomically(sample):
    raw=pack(copy.deepcopy(sample[1]));raw['Q1']['board']['bounding_box']=[3,3,-3,-3]
    raw['Q2']['board']['bounding_box']=[0,5,0,5];raw['Q2']['proof']['condition_ids']=['Q1:S1']
    old=copy.deepcopy(raw)
    with pytest.raises(SubmissionError) as raised:decode(raw,Source.model_validate(sample[0]))
    issues=raised.value.issues
    assert {(i['question_id'],i['stage']) for i in issues}=={('Q1','diagram'),('Q2','diagram'),('Q2','math')}
    assert raw==old
    schema=patch_schema(issues)
    assert set(schema['properties']['updates']['properties']['Q1']['properties'])=={'board'}
    assert set(schema['properties']['updates']['properties']['Q2']['properties'])=={'board','proof'}


def test_collects_schema_errors_across_questions(sample):
    raw=pack(sample[1]);raw['Q1']['proof']['unexpected']=True;raw['Q2']['board']['objects'][0]['coords']=[0]
    with pytest.raises(SubmissionError) as raised:decode(raw,Source.model_validate(sample[0]))
    assert {(i['question_id'],i['stage']) for i in raised.value.issues}=={('Q1','math'),('Q2','diagram')}


@pytest.mark.parametrize('update',[
    {'updates':{'Q1':{'proof':{}}}}, {'updates':{'Q2':{'board':{}}}},
    {'updates':{'Q1':{}}}, {'updates':{},'source':{}},
])
def test_partial_update_cannot_escape_issue_scope(sample,update):
    raw=pack(sample[1]);old=copy.deepcopy(raw)
    with pytest.raises(ValueError):apply_patch(update,raw,[{'question_id':'Q1','path':'board'}])
    assert raw==old


def test_drawing_only_recovery_preserves_proofs_and_full_review(settings,job,sample):
    source,candidate,review=copy.deepcopy(sample);raw=pack(copy.deepcopy(candidate))
    raw['Q1']['board']['bounding_box']=[0,4,0,4]
    patch={'edits':[{'tab':0,'view':{'x_min':-3,'x_max':4,'y_min':-3,'y_max':6}}]}
    stages=[];runner=Runner(replace(settings,compact_tools=True),job[1],
        provider([source,raw,patch,pack_review(review)],stages),MemoryCache,renderer)
    runner.run();report=json.loads((job[2]/'report.json').read_text())
    assert report['status']=='completed',report.get('error')
    assert stages==['source','solve','diagram','review']
    actual=json.loads((job[2]/'candidate.json').read_text())
    assert actual['solutions']==Candidate.model_validate(candidate).model_dump()['solutions']
    assert actual['spec']['tabs'][0]['board']['bounding_box']==[-3,6,4,-3]


def test_drawing_only_recovery_cannot_touch_other_tab(settings,job,sample):
    source,candidate,review=copy.deepcopy(sample);raw=pack(copy.deepcopy(candidate));raw['Q1']['board']['bounding_box']=[0,4,0,4]
    patch={'edits':[{'tab':1,'axis':False}]};stages=[]
    runner=Runner(replace(settings,compact_tools=True),job[1],provider([source,raw,patch],stages),MemoryCache,renderer)
    runner.run();report=json.loads((job[2]/'report.json').read_text())
    assert report['status']=='failed' and '错误清单以外' in report['error']
    assert 'review' not in stages and not (job[2]/'output/result.html').exists()


def test_mixed_recovery_only_submits_authorized_fields(settings,job,sample):
    source,candidate,review=copy.deepcopy(sample);raw=pack(copy.deepcopy(candidate))
    raw['Q1']['board']['bounding_box']=[0,4,0,4];raw['Q2']['proof']['condition_ids']=['Q1:S1']
    patch={'updates':{'Q1':{'board':candidate['spec']['tabs'][0]['board']},'Q2':{'proof':pack(candidate)['Q2']['proof']}}}
    stages=[];runner=Runner(replace(settings,compact_tools=True),job[1],
        provider([source,raw,patch,pack_review(review)],stages),MemoryCache,renderer)
    runner.run();report=json.loads((job[2]/'report.json').read_text())
    assert report['status']=='completed',report.get('error')
    assert stages==['source','solve','solve','review']
    assert json.loads((job[2]/'candidate.json').read_text())['solutions']==Candidate.model_validate(candidate).model_dump()['solutions']


def test_local_correction_does_not_override_math_objection(settings,job,sample):
    source,candidate,review=copy.deepcopy(sample);raw=pack(copy.deepcopy(candidate))
    raw['Q1']['board']['bounding_box']=[0,4,0,4]
    patch={'edits':[{'tab':0,'view':{'x_min':-3,'x_max':4,'y_min':-3,'y_max':6}}]}
    review.update(verdict='revise',issues=[{'stage':'math','target':'Q2','detail':'缺少边界证明'}]);review['questions'][1]['verdict']='issue'
    stages=[];runner=Runner(replace(settings,compact_tools=True,max_repairs=0),job[1],
        provider([source,raw,patch,pack_review(review)],stages),MemoryCache,renderer)
    runner.run();report=json.loads((job[2]/'report.json').read_text())
    assert report['status']=='failed' and '修复次数' in report['error']
    assert stages==['source','solve','diagram','review']


def test_missing_basis_patch_preserves_every_math_and_board_field(sample):
    source=Source.model_validate(sample[0]);raw=pack(copy.deepcopy(sample[1]))
    with pytest.raises(SubmissionError) as raised:decode(raw,source,require_basis=True)
    issues=raised.value.issues
    assert issues and all(i['code']=='missing_basis' for i in issues)
    schema=patch_schema(issues)
    updates={}
    for qid,item in schema['properties']['updates']['properties'].items():
        assert set(item['properties'])=={'step_basis'}
        ids=item['properties']['step_basis']['required']
        updates[qid]={'step_basis':{sid:['C1'] for sid in ids}}
    actual=apply_patch({'updates':updates},raw,issues)
    expected=copy.deepcopy(raw)
    for q in expected.values():
        for step in q['proof']['steps']:step['basis_ids']=['C1']
    assert actual==expected and raw==pack(copy.deepcopy(sample[1]))
    decode(actual,source,require_basis=True)


@pytest.mark.parametrize('value',[{}, {'S1':[]}, {'S1':['C1','C1']}, {'S1':['C1'],'S2':['C1']}])
def test_missing_basis_patch_cannot_delete_duplicate_or_add_unreported_steps(sample,value):
    raw=pack(copy.deepcopy(sample[1]))
    issue=[{'question_id':'Q1','stage':'math','path':'proof.steps.0.basis_ids','code':'missing_basis'}]
    with pytest.raises(ValueError):apply_patch({'updates':{'Q1':{'step_basis':value}}},raw,issue)


def test_citation_only_patch_rejects_proof_rewrite(sample):
    raw=pack(copy.deepcopy(sample[1]))
    issue=[{'question_id':'Q1','stage':'math','path':'proof.steps.0.basis_ids','code':'missing_basis'}]
    with pytest.raises(ValueError):apply_patch({'updates':{'Q1':{'proof':raw['Q1']['proof']}}},raw,issue)
