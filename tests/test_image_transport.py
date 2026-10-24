import base64,io
import pytest
from PIL import Image,ImageChops
from math_agent.image_transport import prepare_messages,check_body


def image_url(img):
    b=io.BytesIO();img.save(b,format='PNG')
    return 'data:image/png;base64,'+base64.b64encode(b.getvalue()).decode()


def test_long_image_is_fully_covered_by_original_pixels_and_roles_survive():
    image=Image.new('RGB',(16,9702))
    for y in range(image.height):
        for x in range(image.width):image.putpixel((x,y),(y%256,x,(y//256)%256))
    messages=[{'role':'user','content':[{'type':'text','text':'I2 参考答案（不是题设）'},
        {'type':'image_url','image_url':{'url':image_url(image)}}]}]
    old_url=messages[0]['content'][1]['image_url']['url']
    result,records=prepare_messages(messages)
    assert result[0]['content'][0]['text']=='I2 参考答案（不是题设）'
    assert messages[0]['content'][1]['image_url']['url']==old_url
    pieces=[p for p in result[0]['content'] if p['type']=='image_url'];assert len(pieces)==len(records)
    reconstructed=Image.new('RGB',image.size);coverage=[False]*image.height
    for p,r in zip(pieces,records):
        im=Image.open(io.BytesIO(base64.b64decode(p['image_url']['url'].split(',')[1])))
        assert max(im.size)<=4096
        if r['kind']=='original_pixels':
            box=r['pixel_box'];assert ImageChops.difference(im,image.crop(box)).getbbox() is None
            reconstructed.paste(im,tuple(box[:2]));coverage[box[1]:box[3]]=[True]*(box[3]-box[1])
    assert all(coverage) and ImageChops.difference(reconstructed,image).getbbox() is None


def test_small_image_history_and_private_reasoning_are_preserved():
    h=[{'role':'user','content':[{'type':'image_url','image_url':{'url':image_url(Image.new('RGB',(20,30)))}}]},
        {'role':'assistant','content':None,'_response_items':[{'type':'reasoning','content':[]}]}]
    result,records=prepare_messages(h);assert result==h and not records


def test_task_pixel_reuse_preserves_wire_bytes_roles_positions_and_mutation_isolation(monkeypatch):
    import copy
    import math_agent.image_transport as m
    url=image_url(Image.new('RGB',(16,5000),(23,61,101)))
    h=[{'role':'user','content':[{'type':'text','text':'I1 原题'},
        {'type':'image_url','image_url':{'url':url}}]}];original=copy.deepcopy(h)
    expected=m.prepare_messages(h);calls=[];split=m._split_image
    def counted(*args):calls.append(1);return split(*args)
    monkeypatch.setattr(m,'_split_image',counted);cache=m.PixelTiles()
    first=m.prepare_messages(h,cache)
    assert first==expected and h==original
    first[1][1]['pixel_box'][0]=999
    assert m.prepare_messages(h,cache)==expected and calls==[1]
    changed=[{'role':'system','content':'范围限定'}, {'role':'user','content':[
        {'type':'text','text':'I2 参考答案（不是题设）'},{'type':'text','text':'新的消息位置'},
        {'type':'image_url','image_url':{'url':url}}]}]
    reused,manifest=m.prepare_messages(changed,cache)
    assert all(r['message']==1 and r['part']==2 for r in manifest)
    assert reused[1]['content'][0]['text']=='I2 参考答案（不是题设）'
    assert calls==[1] and cache.snapshot()['hits']==2


def test_pixel_reuse_is_bounded_and_never_drops_tiles_on_eviction(monkeypatch):
    import math_agent.image_transport as m
    a=image_url(Image.new('RGB',(16,5000),'red'));b=image_url(Image.new('RGB',(16,5000),'blue'))
    calls=[];split=m._split_image
    def counted(*args):calls.append(1);return split(*args)
    monkeypatch.setattr(m,'_split_image',counted)
    cache=m.PixelTiles(max_entries=1);first=cache.get(a,m.MAX_SIDE)
    cache.get(b,m.MAX_SIDE);again=cache.get(a,m.MAX_SIDE)
    assert first==again and len(calls)==3 and cache.snapshot()['entries']==1
    tiny=m.PixelTiles(max_bytes=1)
    assert tiny.get(a,m.MAX_SIDE)==tiny.get(a,m.MAX_SIDE)==first
    assert tiny.snapshot()['entries']==0 and tiny.snapshot()['bytes']==0


def test_parallel_providers_encode_same_uploaded_original_once(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    import math_agent.image_transport as m
    url=image_url(Image.new('RGB',(16,5000),'green'));cache=m.PixelTiles();calls=[];split=m._split_image
    barrier=threading.Barrier(2)
    def counted(*args):calls.append(1);return split(*args)
    monkeypatch.setattr(m,'_split_image',counted)
    def task():barrier.wait(2);return cache.get(url,m.MAX_SIDE)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(task) for _ in range(2)];values=[f.result(3) for f in futures]
    assert values[0]==values[1] and calls==[1] and cache.snapshot()['hits']==1


def test_request_limits_are_checked_again_even_when_tiles_are_reused(monkeypatch):
    import math_agent.image_transport as m
    url=image_url(Image.new('RGB',(16,5000),'green'));cache=m.PixelTiles()
    h=[{'role':'user','content':[{'type':'image_url','image_url':{'url':url}}]}]
    expected=m.prepare_messages(h,cache)
    monkeypatch.setattr(m,'MAX_IMAGES',2)
    with pytest.raises(ValueError,match='图片数量'):m.prepare_messages(h,cache)
    monkeypatch.setattr(m,'MAX_IMAGES',600)
    assert m.prepare_messages(h,cache)==expected


@pytest.mark.parametrize('native',[False,True])
def test_preparation_that_exhausts_deadline_never_sends_or_claims_api_usage(monkeypatch,settings,native):
    import httpx
    from dataclasses import replace
    import math_agent.image_transport as m
    from math_agent.provider import DeepSeek,ModelError
    from math_agent.parallel_budget import ParallelBudget
    now=[0.0];sent=[];records=[];prepare=m.prepare_messages
    def slow(*args,**kwargs):
        result=prepare(*args,**kwargs);now[0]=2.0;return result
    monkeypatch.setattr(m,'prepare_messages',slow)
    cfg=replace(settings,compact_tools=True,solve_responses=native)
    provider=DeepSeek(cfg,lambda k,v:records.append((k,v)),httpx.MockTransport(lambda r:sent.append(r)))
    provider.shared_budget=ParallelBudget(12,timeout_seconds=1,clock=lambda:now[0])
    try:
        with pytest.raises(ModelError):provider.generate('solve',[{'role':'user','content':'题目'}],
            **({'output_schema':{'type':'object'}} if native else {}))
        assert sent==[]
        blocked=[r for k,r in records if k=='model' and r.get('not_sent')]
        assert len(blocked)==1 and 'usage' not in blocked[0]
        usage=provider.shared_budget.snapshot()['usage']
        assert usage['complete'] and usage['not_sent_calls']==1 and usage['reported_calls']==0
        assert usage['known_prompt_tokens']==usage['known_completion_tokens']==0
    finally:provider.close()


def test_request_size_fails_before_network(monkeypatch):
    import math_agent.image_transport as m
    monkeypatch.setattr(m,'MAX_BODY',10)
    with pytest.raises(ValueError,match='48MiB'):check_body({'messages':['long payload']})


def test_invalid_image_never_reaches_network(settings):
    import httpx
    from math_agent.provider import DeepSeek,ModelError
    sent=[]
    c=DeepSeek(settings,lambda *a:None,httpx.MockTransport(lambda r:sent.append(r)))
    try:
        with pytest.raises(ModelError,match='原图传输预检失败'):
            c.generate('source',[{'role':'user','content':[{'type':'image_url','image_url':{'url':'data:image/png;base64,AAAA'}}]}])
        assert not sent
    finally:c.close()


def test_http_error_diagnostic_does_not_record_secrets_or_image_data(settings):
    import httpx
    from math_agent.provider import DeepSeek,ModelError
    audit=[]
    def handler(r):return httpx.Response(400,json={'error':{'code':'bad_image','message':settings.api_key+' dimension exceeded data:image/png;base64,AAAA'}})
    c=DeepSeek(settings,lambda k,v:audit.append(v),httpx.MockTransport(handler))
    try:
        with pytest.raises(ModelError):c.generate('source',[])
        text=str(audit);assert 'dimension exceeded' in text and 'bad_image' in text
        assert settings.api_key not in text and 'base64,AAAA' not in text
    finally:c.close()
