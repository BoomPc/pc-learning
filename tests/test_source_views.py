import json
from PIL import Image
from math_agent.source_views import source_text_views


def test_crops_are_bounded_question_pixels_not_answer_or_diagram(tmp_path):
    Image.new('RGB',(300,200),'red').save(tmp_path/'q.png')
    request={'images':[{'id':'Q','role':'question','file':'q.png'},{'id':'A','role':'answer','file':'missing.png'}],
        'ocr_evidence':[{'image_id':'Q','role':'question','blocks':[
            {'kind':'text','bbox':[20,30,100,60]}, {'kind':'text','bbox':[20,30,100,60]},
            {'kind':'image','bbox':[100,100,200,190]}, {'kind':'text','bbox':[-1,0,100,20]},
            {'kind':'text','bbox':[0,0,float('nan'),20]}, {'kind':'text','bbox':[110,30,200,60]}]},
            {'image_id':'A','role':'answer','blocks':[{'kind':'text','bbox':[20,30,100,60]}]}]}
    content=source_text_views(request,tmp_path,limit=1)
    manifest=json.loads((tmp_path/'source-text-views.json').read_text())
    assert len(content)==2 and len(manifest)==1
    assert manifest[0]['pixel_box']==[8,18,112,72]
    with Image.open(tmp_path/manifest[0]['artifact']) as crop:
        assert crop.size==(104,54) and crop.getpixel((0,0))==(255,0,0)


def test_no_ocr_means_no_extra_image(tmp_path):
    assert source_text_views({'images':[]},tmp_path)==[]
