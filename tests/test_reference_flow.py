import copy,json
from dataclasses import replace
import pytest
from math_agent.contracts import Source
from math_agent.reference_flow import validate_math,assemble,patch_drawing,math_hash
from math_agent.scene_tools import PreviewSpec
from math_agent.pipeline import Runner
from math_agent.storage import write_json
from test_pipeline import provider,renderer,MemoryCache


def prepare(job,sample):
    source,candidate,review=copy.deepcopy(sample);source['topic_family']='rotation_translation'
    (job[2]/'answer.png').write_bytes(b'fixture')
    write_json(job[2]/'request.json',{'text':'参考答案流程夹具','images':[{'id':'I1','role':'answer','file':'answer.png','sha256':'fixture-answer-hash'}],'force':True})
    math={'solutions':candidate['solutions']}
    drawing={'tabs':[{k:t[k] for k in ('board','controls') if k in t} for t in candidate['spec']['tabs']]}
    return source,math,drawing,review


def test_math_then_drawing_and_local_repair_do_not_repeat_math(settings,job,sample):
    source,math,drawing,review=prepare(job,sample)
    revise=copy.deepcopy(review);revise.update(verdict='revise',issues=[{'stage':'diagram','target':'tab0','detail':'修复标签'}])
    update={'updates':[{'tab':0,**drawing['tabs'][0]}]};stages=[]
    runner=Runner(replace(settings,reference_mode=True),job[1],provider([source,math,review,drawing,revise,__import__('test_objection_gate').resolution(revise,sample[1]),update,review],stages),MemoryCache,renderer)
    runner.run()
    assert job[0].get(job[1])['status']=='completed'
    assert stages==['source','reference_math','math_review','draw','graph_review','adjudicate','draw_patch','graph_review']
    saved=json.loads((job[2]/'candidate.json').read_text())
    assert saved['solutions']==validate_math(math,Source.model_validate(source)).model_dump()['solutions']
    assert (job[2]/'math-review.json').exists()


def test_new_math_objection_invalidates_certificate_and_rechecks(settings,job,sample):
    source,math,drawing,review=prepare(job,sample)
    revise=copy.deepcopy(review);revise.update(verdict='revise',issues=[{'stage':'math','target':'Q1','detail':'发现遗漏分类'}])
    changed=copy.deepcopy(math);changed['solutions'][0]['cases']=['补充边界分类']
    stages=[]
    Runner(replace(settings,reference_mode=True),job[1],provider([source,math,review,drawing,revise,changed,review,drawing,review],stages),MemoryCache,renderer).run()
    assert job[0].get(job[1])['status']=='completed'
    assert stages==['source','reference_math','math_review','draw','graph_review','reference_math','math_review','draw','graph_review']
    report=json.loads((job[2]/'report.json').read_text())
    hashes=[x['sha256'] for x in report['audit'] if x['kind']=='math_certificate']
    assert len(hashes)==2 and hashes[0]!=hashes[1]


def test_missing_classification_uses_explicit_source_text(settings,job,sample):
    source,math,drawing,review=prepare(job,sample)
    source.pop('topic_family');source['problem_text']+=' 绕点A旋转。';stages=[]
    Runner(replace(settings,reference_mode=True),job[1],provider([source,math,review,drawing,review],stages),MemoryCache,renderer).run()
    assert job[0].get(job[1])['status']=='completed'
    assert stages.count('source')==1
    audit=json.loads((job[2]/'audit.json').read_text())
    assert any(x.get('text_fallback') for x in audit if x['kind']=='reference_scope')


def test_all_bad_references_report_their_locations(sample):
    source=Source.model_validate(sample[0]);raw={'solutions':copy.deepcopy(sample[1]['solutions'])}
    raw['solutions'][0]['steps'][0]['basis_ids']=['Q1','Q1:S99']
    raw['solutions'][1]['steps'][0]['basis_ids']=['Q2']
    with pytest.raises(ValueError) as exc:validate_math(raw,source)
    assert 'Q1:S1.basis_ids' in str(exc.value) and 'Q2:S1.basis_ids' in str(exc.value)
    assert 'Q1:S99' in str(exc.value)


def test_drawing_schema_cannot_change_math_or_untouched_tab(sample):
    source=Source.model_validate(sample[0]);draft=validate_math({'solutions':sample[1]['solutions']},source)
    drawing=PreviewSpec.model_validate({'tabs':[{k:t[k] for k in ('board','controls') if k in t} for t in sample[1]['spec']['tabs']]})
    original=assemble(source,draft,drawing)
    update={'updates':[{'tab':0,**drawing.tabs[0].model_dump(exclude_none=True)}]}
    patched=patch_drawing(source,draft,original,update)
    assert patched.solutions==original.solutions and patched.spec['tabs'][1]==original.spec['tabs'][1]
    update['solutions']=[]
    with pytest.raises(ValueError):patch_drawing(source,draft,original,update)
    update.pop('solutions');update['updates'][0]['tab']=11
    with pytest.raises(ValueError):patch_drawing(source,draft,original,update)


@pytest.mark.parametrize('reason',['no_answer','unsupported'])
def test_reference_scope_never_silently_falls_back(settings,job,sample,reason):
    source,math,drawing,review=prepare(job,sample);stages=[]
    if reason=='no_answer':write_json(job[2]/'request.json',{'text':'无答案','images':[],'force':True})
    else:source['topic_family']='parabola'
    Runner(replace(settings,reference_mode=True),job[1],provider([source],stages),MemoryCache,renderer).run()
    assert job[0].get(job[1])['status']=='failed'
    assert stages==([] if reason=='no_answer' else ['source'])


@pytest.mark.skipif(__import__('os').getenv('MATH_AGENT_BROWSER_TEST')!='1',reason='真实浏览器')
def test_reference_graph_renders_real_page(settings,job,sample):
    source,math,drawing,review=prepare(job,sample);stages=[]
    Runner(replace(settings,reference_mode=True),job[1],provider([source,math,review,drawing,review],stages),MemoryCache).run()
    assert job[0].get(job[1])['status']=='completed'
    report=json.loads((job[2]/'report.json').read_text())
    assert report['workflow']=='reference' and report['render_check']['status']=='pass'
    assert 'JSXGraph' in (job[2]/'output/result.html').read_text()
