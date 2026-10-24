from dataclasses import replace
import json
import httpx
import pytest
from math_agent.ocr import recognize
from math_agent.provider import DeepSeek
from math_agent.prompts import messages


def test_source_budget_separate_and_thinking_off(settings):
    requests=[]
    def handler(r):
        requests.append(json.loads(r.content))
        return httpx.Response(200,json={'choices':[{'message':{'content':'{}'},'finish_reason':'stop'}]})
    client=DeepSeek(replace(settings,max_tokens=32000,source_max_tokens=8000),lambda *a:None,httpx.MockTransport(handler))
    try:
        client.request('source',[]);client.request('solve',[])
    finally: client.close()
    assert requests[0]['thinking']=={'type':'disabled'}
    assert requests[0]['max_tokens']==8000 and 'reasoning_effort' not in requests[0]
    assert requests[1]['thinking']=={'type':'enabled'} and requests[1]['max_tokens']==32000


def test_ocr_preserves_roles_and_formula_is_evidence(settings,tmp_path,monkeypatch):
    import math_agent.ocr as module
    from PIL import Image
    Image.new('RGB',(100,100),'white').save(tmp_path/'q.png')
    Image.new('RGB',(100,100),'black').save(tmp_path/'a.png')
    def handler(r):
        assert r.headers['Authorization']=='Bearer '+settings.access_token
        return httpx.Response(200,json=dict(engine='test',profile='p',blocks=[dict(kind='formula',text=r'x^2',bbox=[0,0,1,1])],text=r'x^2',warnings=['uncertain'],seconds=1,cache_hit=False))
    original=httpx.Client
    monkeypatch.setattr(module.httpx,'Client',lambda **kwargs:original(transport=httpx.MockTransport(handler)))
    request=dict(text='',images=[dict(id='I1',role='question',file='q.png'),dict(id='I2',role='answer',file='a.png')])
    evidence=recognize(replace(settings,ocr_url='http://127.0.0.1:18666'),request,tmp_path,lambda *a:None)
    assert [e['role'] for e in evidence]==['question']
    request['ocr_evidence']=evidence
    prompt=messages('source',request,tmp_path)
    content=json.loads(prompt[-1]['content'][0]['text'])
    assert len(content['ocr_evidence']) == 1
    assert content['ocr_evidence'][0]['blocks'][0]['text']==r'x^2'
    assert sum(b['type']=='image_url' for b in prompt[-1]['content'])==3
    assert '不得从OCR框坐标推断几何坐标' in prompt[0]['content']


def test_ocr_failure_stops_and_no_retry(settings,tmp_path,monkeypatch):
    import math_agent.ocr as module
    from PIL import Image
    Image.new('RGB',(20,30),'white').save(tmp_path/'q.png'); calls=[]
    def handler(r):
        calls.append(1);return httpx.Response(503,json={'error':'busy'})
    original=httpx.Client
    monkeypatch.setattr(module.httpx,'Client',lambda **kwargs:original(transport=httpx.MockTransport(handler)))
    with pytest.raises(RuntimeError,match='OCR服务失败'):
        recognize(replace(settings,ocr_url='http://127.0.0.1:18666'),dict(images=[dict(id='I1',file='q.png')]),tmp_path,lambda *a:None)
    assert len(calls)==1


def test_text_only_skips_ocr(settings,tmp_path):
    assert recognize(replace(settings,ocr_url='http://127.0.0.1:18666'),{'images':[]},tmp_path,lambda *a:None)==[]


def test_independent_reread_removes_ocr_and_answer_but_keeps_uncertainty_guard(settings,job,sample):
    import copy
    from math_agent.pipeline import Runner,NeedsInput
    from math_agent.storage import write_json
    store,job_id,directory=job
    source=copy.deepcopy(sample[0]);source['uncertainties']=['原图仍有未决条件']
    request={'text':'完整题干','images':[{'id':'I1','role':'question','file':'q.png'},{'id':'I2','role':'answer','file':'a.png'}], 'force':True,
             'ocr_evidence':[{'image_id':'I1','role':'question','blocks':[],'warnings':[]}]}
    write_json(directory/'request.json',request)
    runner=Runner(settings,job_id)
    seen=[]
    def ask(stage,payload=None,request_override=None):
        seen.append(request_override)
        if stage == 'source_review':
            return {'source':copy.deepcopy(source),'decisions':[{'issue_id':'U1','verdict':'unresolved','condition_ids':[], 'quote':'','reason':'原图仍未确定'}]}
        return copy.deepcopy(source)
    runner.ask=ask
    try:
        with pytest.raises(NeedsInput):runner.extract()
        assert len(seen)==2
        assert seen[1]['ocr_evidence']==[]
        assert [i['id'] for i in seen[1]['images']]==['I1']
        assert (directory/'source-before-reread.json').exists()
        with pytest.raises(NeedsInput):runner.extract()
        assert len(seen)==3  # one bounded reread per job, never an endless paid loop
    finally:runner.provider.close()


def test_source_context_and_crop_cannot_read_answer(settings,job,sample):
    from math_agent.pipeline import Runner
    from math_agent.storage import write_json
    store,job_id,directory=job
    for name in ['q.png','a.png']:
        (directory/name).write_bytes(b'image')
    request={'text':'题干','images':[{'id':'I1','role':'question','file':'q.png'}, {'id':'I2','role':'answer','file':'a.png'}], 'force':True,
        'ocr_evidence':[{'image_id':'I1','role':'question','blocks':[],'warnings':[]}, {'image_id':'I2','role':'answer','blocks':[],'warnings':[]}]}
    write_json(directory/'request.json',request)
    runner=Runner(settings,job_id)
    def generate(stage,prompt,tools,dispatch):
        content=json.loads(prompt[-1]['content'][0]['text'])
        assert content['image_roles']==[{'id':'I1','role':'question'}]
        assert [p['image_id'] for p in content['ocr_evidence']]==['I1']
        assert sum(p['type']=='image_url' for p in prompt[-1]['content'])==1
        with pytest.raises(ValueError,match='不能查看'):
            dispatch('view_image_region', {'image_id':'I2','bbox':[0,0,1,1],'reason':'test'})
        return sample[0]
    runner.provider.generate=generate
    try:
        runner.ask('source')
        assert len(runner.request['images'])==2
    finally: runner.provider.close()


def test_diagram_can_disable_thinking_without_disabling_math(settings):
    requests=[]
    def handler(r):
        requests.append(json.loads(r.content))
        return httpx.Response(200,json={'choices':[{'message':{'content':'{}'},'finish_reason':'stop'}]})
    client=DeepSeek(replace(settings,thinking=True,diagram_thinking=False),lambda *a:None,httpx.MockTransport(handler))
    try:
        for stage in ['source','solve','diagram','review']:client.request(stage,[])
    finally: client.close()
    assert [r['thinking']['type'] for r in requests]==['disabled','enabled','disabled','enabled']
