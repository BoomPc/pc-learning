import copy,json
from dataclasses import replace
from math_agent.pipeline import Runner
from math_agent.cache import key_for
from test_pipeline import MemoryCache,renderer


def test_compact_solver_still_renders_and_reviews(settings,job,sample):
    queue=copy.deepcopy(list(sample));queue[1]=pack(queue[1]);queue[2]=__import__('test_compact_review').pack_review(queue[2]);seen={}
    class Provider:
        def __init__(self,*args):self.calls=0
        def generate(self,stage,messages,tools=None,dispatch=None):
            self.calls+=1;seen[stage]={t['function']['name'] for t in tools or []}
            return queue.pop(0)
        def close(self):pass
    Runner(replace(settings,compact_tools=True),job[1],Provider,MemoryCache,renderer).run()
    assert seen['solve']=={'algebra_batch','symbolic_geometry'}
    assert 'inspect_scene' in seen['review']
    assert (job[2]/'output/result.html').exists()
    assert job[0].get(job[1])['status']=='completed'
    request=json.loads((job[2]/'request.json').read_text())
    assert key_for(settings,request)!=key_for(replace(settings,compact_tools=True),request)


def pack(candidate):
    return {s['question_id']:{'proof':{k:v for k,v in s.items() if k!='question_id'},
        **{k:v for k,v in tab.items() if k in {'board','controls'}}}
        for s,tab in zip(candidate['solutions'],candidate['spec']['tabs'])}


def test_compact_contract_roundtrip(sample):
    import pytest
    from math_agent.compact_output import unpack, unique_object, output_schema
    from math_agent.contracts import Source, Candidate
    from math_agent.pipeline import canonical_page
    source=Source.model_validate(sample[0]); raw=pack(sample[1])
    actual=canonical_page(unpack(raw,source),source)
    expected=canonical_page(Candidate.model_validate(sample[1]),source)
    assert actual.solutions==expected.solutions
    from math_agent.jsxgraph.spec import Board
    assert [Board.model_validate(t['board']) for t in actual.spec['tabs']]==[Board.model_validate(t['board']) for t in expected.spec['tabs']]
    for malformed in ({}, {**raw,'unknown':next(iter(raw.values()))}):
        with pytest.raises(ValueError):unpack(malformed,source)
    with pytest.raises(ValueError):json.loads('{"Q1":{},"Q1":{}}',object_pairs_hook=unique_object)
    assert output_schema(sample[0])['required']==[q.id for q in source.questions]


def test_initial_tiles_cover_original_pixels(tmp_path):
    from PIL import Image
    from math_agent.solve_views import solve_views
    im=Image.new('RGB',(20,3300),(23,24,25)); im.save(tmp_path/'answer.png')
    items=solve_views({'images':[{'id':'I2','role':'answer','file':'answer.png'}]},tmp_path)
    manifest=json.loads((tmp_path/'solve-views.json').read_text())
    assert len(items)==6 and all(m['role']=='answer' for m in manifest)
    assert manifest[0]['pixel_box'][1]==0 and manifest[-1]['pixel_box'][3]==3300
    for a,b in zip(manifest,manifest[1:]):assert b['pixel_box'][1]<a['pixel_box'][3]
    for m in manifest:
        with Image.open(tmp_path/m['artifact']) as crop:
            assert crop.tobytes()==im.crop(m['pixel_box']).tobytes()


def test_loop_rejects_duplicate_question_json():
    import pytest
    from math_agent.agent_loop import run_loop
    def request(*args):return {'role':'assistant','content':'{"Q1":{},"Q1":{}}'},'stop'
    with pytest.raises(ValueError,match='JSON'):
        run_loop(request,[],[],None,lambda *args:None,'solve',ValueError)


def test_compact_prompt_uses_only_keyed_contract(tmp_path,sample):
    from math_agent.prompts import messages
    msg=messages('solve',{'text':'test','images':[]},tmp_path,{'source':sample[0]},compact=True)
    assert '"required": ["Q1", "Q2"]' in msg[0]['content']
    assert '输出 Candidate JSON Schema' not in msg[0]['content']
    assert 'preview_scene' not in msg[0]['content']


def test_parallel_model_contract_separates_each_questions_direct_conditions(sample):
    import pytest
    from jsonschema import validate,ValidationError
    from math_agent.compact_output import output_schema
    source=copy.deepcopy(sample[0]);source['conditions'].append({'id':'C2','text':'局部条件','question_ids':['Q1']})
    schema=output_schema(source,require_basis=True)
    q1=proof_constraints(schema,'Q1');q2=proof_constraints(schema,'Q2')
    validate({'proof':{'condition_ids':['C1','C2']}},q1)
    validate({'proof':{'condition_ids':['C1']}},q2)
    with pytest.raises(ValidationError):validate({'proof':{'condition_ids':['C2']}},q2)


def test_branch_contract_references_only_actual_completed_dependency_steps(sample):
    import pytest
    from jsonschema import validate,ValidationError
    from math_agent.compact_output import output_schema
    source=copy.deepcopy(sample[0]);source['questions']=source['questions'][1:]
    schema=output_schema(source,require_basis=True,completed_steps=['Q1:S1','Q1:S2'])
    local=proof_constraints(schema,'Q2')
    def proof(ids):return {'proof':{'steps':[{'basis_ids':ids}]}}
    validate(proof(['C1','Q1:S2','Q2:S1']),local)
    for invalid in ['Q1:S8','Q1','Q3:S1','C99']:
        with pytest.raises(ValidationError):validate(proof([invalid]),local)


def proof_constraints(schema,qid):
    defs=schema['$defs']
    def target(ref):return defs[ref['$ref'].rsplit('/',1)[1]]
    proof=target(target(schema['properties'][qid])['properties']['proof'])
    step=target(proof['properties']['steps']['items'])
    return {'properties':{'proof':{'properties':{'condition_ids':proof['properties']['condition_ids'],
            'steps':{'items':{'properties':{'basis_ids':step['properties']['basis_ids']}}}}}}}
