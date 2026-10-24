import copy,json
from dataclasses import replace
import pytest
from jsonschema import validate,ValidationError
from math_agent.contracts import Source,Candidate,Solution,Review,check_source
from math_agent.native_constructions import collect,require,ConstructionError,normalize
from math_agent.compact_output import output_schema
from math_agent.pipeline import Runner
from math_agent.storage import write_json
from test_pipeline import provider,MemoryCache,renderer
from test_compact_tools import pack
from test_compact_review import pack_review


def augment(sample):
    source,candidate,review=copy.deepcopy(sample)
    quote='取AB的中点H。';source['problem_text']+='\n'+quote
    source['conditions'].append({'id':'C2','quote':quote,'text':quote,'question_ids':['Q1'],
                                 'origin':'question_text','image_ids':[]})
    source['native_constructions']=[{'id':'N1','question_ids':['Q1'],'point':'H','kind':'midpoint',
                                    'parents':['A','B'],'condition_ids':['C2'],'quote':quote}]
    candidate['spec']['problem_text']=source['problem_text']
    candidate['spec']['tabs'][0]['board']['objects'].append({'id':'H','label':'H','kind':'point','coords':[0,0]})
    review['conditions'].append({'id':'C2','verdict':'pass','evidence':'原文中点条件明确'})
    return source,candidate,review


@pytest.mark.parametrize('defect',['quote','condition','scope','duplicate','parents','answer'])
def test_source_construction_evidence_cannot_be_invented_or_escape_scope(sample,defect):
    raw,_,_=augment(sample);r=raw['native_constructions'][0]
    if defect=='quote':r['quote']='原文没有的中点H'
    elif defect=='condition':r['condition_ids']=['C99']
    elif defect=='scope':r['question_ids']=['Q2']
    elif defect=='duplicate':raw['native_constructions'].append(copy.deepcopy(r))
    elif defect=='parents':r['parents']=['A']
    else:raw['conditions'][-1]['origin']='question_image';raw['conditions'][-1]['quote']='';raw['conditions'][-1]['image_ids']=['I1']
    with pytest.raises(ValueError):check_source(Source.model_validate(raw),[{'id':'I1','role':'question'}])


def test_kind_and_parent_binding_are_checked_without_geometry_edits(sample):
    s,c,_=augment(sample);source=Source.model_validate(s);candidate=Candidate.model_validate(c);old=candidate.model_dump()
    issues=collect(source,candidate.solutions[0],c['spec']['tabs'][0]['board'])
    assert len(issues)==1 and 'kind=point' in issues[0]['detail']
    assert candidate.model_dump()==old
    with pytest.raises(ConstructionError):require(source,candidate)
    h=candidate.spec['tabs'][0]['board']['objects'][-1];h.pop('coords');h.update(kind='midpoint',parents=['A','B'])
    require(source,candidate)
    h['parents']=['A','P']
    with pytest.raises(ConstructionError,match='父对象'):require(source,candidate)


def test_scoped_schema_requires_native_target_without_constraining_other_question(sample):
    s,c,_=augment(sample);schema=output_schema(s);raw=pack(c)
    with pytest.raises(ValidationError):validate(raw,schema)
    h=raw['Q1']['board']['objects'][-1];h.pop('coords');h.update(kind='midpoint',parents=['A','B'])
    for answer in raw.values():
        b=answer['board'];box=b.pop('bounding_box');b['view']={'x_min':box[0],'x_max':box[2],'y_min':box[3],'y_max':box[1]}
    raw['Q2']['board']['objects'].append({'id':'H','label':'H','kind':'point','coords':[0,0]})
    validate(raw,schema)
    raw['Q1']['board']['objects'].pop()
    with pytest.raises(ValidationError):validate(raw,schema)


def test_native_curve_names_and_line_endpoint_aliases_bind_only_real_parents():
    text='将点D平移得到点E，两曲线y₁与y₂交于点F，线段DE的中点为M。'
    s=Source.model_validate({'title':'构造','problem_text':text,'conditions':[{'id':'C1','quote':text,
        'text':text,'origin':'question_text','image_ids':[]}],'questions':[{'id':'Q1','text':'求距离'}],
        'reference_summary':'','uncertainties':[],'native_constructions':[
        {'id':'N1','question_ids':['Q1'],'point':'E','kind':'translation','parents':['D'],'condition_ids':['C1'],'quote':text},
        {'id':'N2','question_ids':['Q1'],'point':'F','kind':'intersection','parents':['y₁','y₂'],'condition_ids':['C1'],'quote':text},
        {'id':'N3','question_ids':['Q1'],'point':'M','kind':'midpoint','parents':['D','E'],'condition_ids':['C1'],'quote':text}]})
    check_source(s,[])
    sol=Solution(question_id='Q1',result='结果',steps=[{'premise':'条件','rule':'计算','conclusion':'结果'}],
                 cases=[],domain_and_boundaries='范围',condition_ids=['C1'])
    board={'objects':[{'id':'d','label':'D','kind':'point','coords':[0,0]},
        {'id':'e','label':'E','kind':'translation','parents':['d'],'vector':[1,1]},
        {'id':'g1','label':'y1','kind':'functiongraph','expression':'x','domain':[-2,2]},
        {'id':'g2','label':'y₂=x²','kind':'functiongraph','expression':'x^2','domain':[-2,2]},
        {'id':'f','label':'F','kind':'intersection','parents':['g2','g1'],'branch':0},
        {'id':'m','label':'M','kind':'midpoint','parents':['e','d']}]}
    assert not collect(s,sol,board)
    board['objects'].append({'id':'wrong','label':'y1','kind':'functiongraph','expression':'2*x','domain':[-2,2]})
    assert [i['point_name'] for i in collect(s,sol,board)]==['F']
    assert normalize('A²')!=normalize('A2') and normalize('A₁')==normalize('A1')


def test_curve_source_identity_is_independent_of_display_formula():
    text='一次函数与二次函数的图象相交于点F。'
    raw={'title':'来源绑定','problem_text':text,'conditions':[{'id':'C1','text':text,'quote':text,'origin':'question_text','image_ids':[]}],
         'questions':[{'id':'Q1','text':'求交点'}],'reference_summary':'','uncertainties':[],
         'native_constructions':[{'id':'N1','point':'F','kind':'intersection','parents':['一次函数','二次函数'],
             'question_ids':['Q1'],'condition_ids':['C1'],'quote':text}]}
    source=Source.model_validate(raw)
    proof={'result':'F=(1,1)','steps':[{'premise':'题设','rule':'联立','conclusion':'F=(1,1)'}],
           'cases':[],'domain_and_boundaries':'实数','condition_ids':['C1']}
    board={'view':{'x_min':-2,'x_max':2,'y_min':-2,'y_max':3},'objects':[
        {'id':'f','kind':'functiongraph','label':'y=x','expression':'x','domain':[-2,2]},
        {'id':'g','kind':'functiongraph','label':'y=x²','expression':'x^2','domain':[-2,2]},
        {'id':'F','kind':'intersection','label':'F','parents':['f','g'],'branch':1}]}
    answer={'Q1':{'proof':proof,'board':board}}
    solution=Solution(question_id='Q1',**proof);schema=output_schema(raw)
    with pytest.raises(ValidationError):validate(answer,schema)
    assert collect(source,solution,board)
    original=copy.deepcopy(board)
    board['objects'][0]['source_names']=['一次函数'];board['objects'][1]['source_names']=['二次函数']
    validate(answer,schema)
    assert not collect(source,solution,board)
    stripped=copy.deepcopy(board)
    for obj in stripped['objects']:obj.pop('source_names',None)
    assert stripped==original # no formula/label/coordinates/parents changed
    board['objects'][2]['parents']=['f','f']
    assert collect(source,solution,board)


def test_ambiguous_source_names_cannot_bypass_native_parent_identity():
    from math_agent.native_constructions import resolve
    from math_agent.jsxgraph.spec import CURVES
    objects=[{'id':k,'kind':'functiongraph','label':label,'source_names':['原文曲线']} for k,label in [('f','y=x'),('g','y=2x')]]
    assert len(resolve(objects,'原文曲线',CURVES))==2


def test_empty_source_names_preserve_old_scene_hash_but_real_bindings_invalidate_it(sample):
    from math_agent.rendering import strict_spec
    from math_agent.scene_tools import fingerprint
    before=strict_spec(sample[1]['spec']);empty=copy.deepcopy(sample[1]['spec'])
    empty['tabs'][0]['board']['objects'][0]['source_names']=[]
    assert strict_spec(empty)==before
    empty['tabs'][0]['board']['objects'][0]['source_names']=['原文对象']
    assert fingerprint(strict_spec(empty))!=fingerprint(before)


@pytest.mark.parametrize('kind,parents',[('rotation',['A','B']),('reflection',['A','BC']),('perpendicularpoint',['A','BC'])])
def test_rotation_reflection_and_foot_bind_ordered_parents_and_prime_names(kind,parents):
    quote='依据题意由A构造新点X′。'
    s=Source.model_validate({'title':'构造','problem_text':quote,'conditions':[{'id':'C1','quote':quote,'text':quote,'origin':'question_text','image_ids':[]}],
        'questions':[{'id':'Q1','text':'求值'}],'reference_summary':'','uncertainties':[],
        'native_constructions':[{'id':'N1','question_ids':['Q1'],'point':'X′','kind':kind,'parents':parents,'condition_ids':['C1'],'quote':quote}]})
    sol=Solution(question_id='Q1',result='结果',steps=[{'premise':'条件','rule':'计算','conclusion':'结果'}],cases=[],domain_and_boundaries='范围',condition_ids=['C1'])
    board={'objects':[{'id':p,'label':p,'kind':'point','coords':[i,0]} for i,p in enumerate(['A','B','C'])]+[
        {'id':'ln','kind':'line','parents':['B','C']},{'id':'seg','kind':'segment','parents':['C','B']},
        {'id':'image','label':"X'",'kind':kind,'parents':['A','B' if kind=='rotation' else 'ln']}]}
    assert collect(s,sol,board)==[]
    board['objects'][-1]['parents'].reverse()
    assert collect(s,sol,board)


def test_reference_flow_observe_enforces_same_obligation(settings,job,sample):
    from test_reference_flow import prepare
    s,c,r=augment(sample)
    s,math,drawing,r=prepare(job,(s,c,r));stages=[]
    h=copy.deepcopy(drawing['tabs'][0]['board']['objects'][-1]);h.pop('coords');h.update(kind='midpoint',parents=['A','B'])
    patched=copy.deepcopy(drawing['tabs'][0]);patched['board']['objects'][-1]=h
    queue=[s,math,r,drawing,{'updates':[{'tab':0,**patched}]},r]
    Runner(replace(settings,reference_mode=True,native_constructions=True),job[1],provider(queue,stages),MemoryCache,renderer).run()
    assert job[0].get(job[1])['status']=='completed'
    assert stages==['source','reference_math','math_review','draw','draw_patch','graph_review']


def test_inspect_model_schema_rejects_wrong_arity_and_requires_basis_for_assertions():
    from math_agent.scene_tools import inspection_definition,INSPECT
    schema=inspection_definition()['function']['parameters']
    args={'probes':[{'tab':0,'checks':[{'relation':'perpendicular','points':['C','F','E']}]}]}
    validate(args,INSPECT['function']['parameters']) # old recovery input decoder is unchanged
    with pytest.raises(ValidationError):validate(args,schema)
    check=args['probes'][0]['checks'][0];check['points']=['C','F','F','E'];validate(args,schema)
    check['expected']=True
    with pytest.raises(ValidationError):validate(args,schema)
    check.update(basis_ids=['C1'],rationale='原题直角条件')
    validate(args,schema)


def test_typed_inspect_preserves_changed_tab_and_query_only_restrictions():
    from math_agent.scene_tools import inspection_definition
    from math_agent.review_reuse import query_tool
    base=query_tool({'changed_tabs':[2]});original=copy.deepcopy(base)
    schema=inspection_definition(base)['function']['parameters']
    args={'probes':[{'tab':2,'checks':[{'relation':'same_x','points':['A','B']}]}]}
    validate(args,schema)
    args['probes'][0]['tab']=0
    with pytest.raises(ValidationError):validate(args,schema)
    args['probes'][0]['tab']=2;args['probes'][0]['checks'][0]['expected']=True
    with pytest.raises(ValidationError):validate(args,schema)
    assert base==original


@pytest.mark.parametrize('compact',[False,True])
def test_same_source_obligation_repairs_diagram_and_keeps_proofs(settings,job,sample,compact):
    s,c,r=augment(sample);fixed=copy.deepcopy(c)
    h=fixed['spec']['tabs'][0]['board']['objects'][-1];h.pop('coords');h.update(kind='midpoint',parents=['A','B'])
    correction=({'edits':[{'tab':0,'upsert':[h]}]} if compact else fixed)
    stages=[];queue=[s,pack(c) if compact else c,correction,pack_review(r) if compact else r]
    runner=Runner(replace(settings,compact_tools=compact,native_constructions=True),job[1],provider(queue,stages),MemoryCache,renderer)
    runner.run();report=json.loads((job[2]/'report.json').read_text())
    assert report['status']=='completed',report.get('error')
    assert stages==['source','solve','diagram','review']
    final=Candidate.model_validate(json.loads((job[2]/'candidate.json').read_text()))
    assert final.solutions==Candidate.model_validate(c).solutions
    require(Source.model_validate(s),final)


def test_false_model_pass_cannot_write_cache_or_publish(monkeypatch,settings,job,sample):
    s,c,r=augment(sample);stages=[]
    monkeypatch.setattr('math_agent.flow.execute_graph',lambda *args:{'source':Source.model_validate(s),
        'candidate':Candidate.model_validate(c),'review':Review.model_validate(r)})
    runner=Runner(settings,job[1],provider([],stages),MemoryCache,renderer);runner.run()
    assert job[0].get(job[1])['status']=='failed' and not stages and runner.cache.data is None
    assert not (job[2]/'output/result.html').exists()


def test_invalid_cached_construction_never_falls_back_to_model(settings,job,sample):
    s,c,r=augment(sample);from math_agent.pipeline import canonical_page
    candidate=canonical_page(Candidate.model_validate(c),Source.model_validate(s));stages=[]
    runner=Runner(settings,job[1],provider([],stages),MemoryCache,renderer)
    runner.cache.data={'source':s,'candidate':candidate.model_dump(),'review':r}
    runner.run()
    assert job[0].get(job[1])['status']=='failed' and not stages
    assert not (job[2]/'output/result.html').exists()


def test_native_mode_cache_cannot_omit_reading_contract_and_trigger_paid_fallback(settings,job,sample):
    source,candidate,review=sample;stages=[]
    from math_agent.pipeline import canonical_page
    final=canonical_page(Candidate.model_validate(candidate),Source.model_validate(source))
    runner=Runner(replace(settings,native_constructions=True),job[1],provider([],stages),MemoryCache,renderer)
    runner.cache.data={'source':source,'candidate':final.model_dump(),'review':review}
    runner.run()
    assert job[0].get(job[1])['status']=='failed' and not stages
    assert '不能省略构造关系清单' in job[0].get(job[1])['error']
