import io
import json
from dataclasses import replace
from types import SimpleNamespace
import httpx
import pytest
from PIL import Image, ImageChops
from math_agent.api import create_app
from math_agent.image_input import save_image
from math_agent.ocr import recognize
from math_agent.storage import Store


def encoded(image):
    stream=io.BytesIO();image.save(stream,format='PNG');stream.seek(0);return stream


@pytest.mark.parametrize('size',[(24,12001),(4100,4100)])
def test_web_accepts_old_dimension_rejections_without_losing_pixels(settings,size):
    original=Image.new('RGB',size,'white')
    original.putpixel((size[0]-1,size[1]-1),(17,31,93))
    auth={'Authorization':'Bearer '+settings.access_token}
    client=create_app(settings).test_client()
    response=client.post('/api/jobs',headers=auth,data={
        'question':(encoded(Image.new('RGB',(20,30))),'q.png'),
        'answer':(encoded(original),'long.png')})
    assert response.status_code==202
    store=Store(settings.data_dir);directory=store.path(response.json['id'])
    request=json.loads((directory/'request.json').read_text())
    assert [i['role'] for i in request['images']]==['question','answer']
    with Image.open(directory/request['images'][1]['file']) as saved:
        assert saved.size==size
        assert ImageChops.difference(saved,original).getbbox() is None
    local=directory/'local.png'
    save_image(SimpleNamespace(stream=encoded(original)),local)
    assert local.read_bytes()==(directory/request['images'][1]['file']).read_bytes()


def test_transparent_long_image_keeps_visible_pixels_and_white_background(tmp_path):
    original=Image.new('RGBA',(3,12001),(0,0,0,0));original.putpixel((2,12000),(10,20,30,255))
    target=tmp_path/'image.png';save_image(SimpleNamespace(stream=encoded(original)),target)
    with Image.open(target) as result:
        assert result.size==original.size and result.mode=='RGB'
        assert result.getpixel((0,0))==(255,255,255)
        assert result.getpixel((2,12000))==(10,20,30)


def test_long_question_ocr_covers_last_pixel_and_maps_boxes_to_original(settings,tmp_path,monkeypatch):
    import math_agent.ocr as module
    original=Image.new('RGB',(24,12001),'white');original.putpixel((23,12000),(17,31,93))
    original.save(tmp_path/'question.png');requests=[]
    def handler(r):
        body=r.content;start=body.index(b'\x89PNG\r\n\x1a\n');end=body.index(b'IEND',start)+8
        with Image.open(io.BytesIO(body[start:end])) as tile:
            requests.append((tile.size,tile.getpixel((tile.width-1,tile.height-1))))
            assert tile.width*tile.height<=16_000_000 and max(tile.size)<=10000
        return httpx.Response(200,json=dict(engine='mock',profile='p',blocks=[
            dict(kind='text',text=str(len(requests)),bbox=[1,2,3,4])],
            text=str(len(requests)),warnings=[],seconds=1,cache_hit=False))
    client=httpx.Client
    monkeypatch.setattr(module.httpx,'Client',lambda **kwargs:client(transport=httpx.MockTransport(handler)))
    audit=[]
    evidence=recognize(replace(settings,ocr_url='http://127.0.0.1:18666'),
        {'images':[{'id':'I1','role':'question','file':'question.png'}]},tmp_path,lambda k,v:audit.append(v))
    assert sum(size[1] for size,_ in requests)==original.height
    assert requests[-1][1]==(17,31,93)
    assert evidence[0]['text']=='1\n2\n3\n4'
    assert evidence[0]['blocks'][-1]['bbox']==[1,9218,3,9220]
    assert evidence[0]['image_id']=='I1' and evidence[0]['role']=='question'
    assert len(audit[-1]['pixel_tiles'])==4


def test_failed_later_ocr_tile_does_not_publish_partial_recognition(settings,tmp_path,monkeypatch):
    import math_agent.ocr as module
    Image.new('RGB',(24,12001)).save(tmp_path/'question.png');calls=[]
    def handler(r):
        calls.append(1)
        if len(calls)==2:return httpx.Response(503)
        return httpx.Response(200,json=dict(engine='mock',profile='p',blocks=[],text='first',warnings=[],seconds=1,cache_hit=False))
    client=httpx.Client
    monkeypatch.setattr(module.httpx,'Client',lambda **kwargs:client(transport=httpx.MockTransport(handler)))
    with pytest.raises(RuntimeError,match='OCR服务失败'):
        recognize(replace(settings,ocr_url='http://127.0.0.1:18666'),
            {'images':[{'id':'I1','role':'question','file':'question.png'}]},tmp_path,lambda *a:None)
    assert len(calls)==2
