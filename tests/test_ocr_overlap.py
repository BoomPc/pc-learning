import copy,json,threading
from dataclasses import replace
from PIL import Image
from math_agent.pipeline import Runner
from math_agent.storage import write_json
from test_pipeline import MemoryCache,renderer
from test_compact_tools import pack
from test_compact_review import pack_review


def image_job(job):
    Image.new('RGB',(8,8),'white').save(job[2]/'q.png')
    write_json(job[2]/'request.json',{'text':'题目','force':True,'images':[
        {'id':'I1','role':'question','file':'q.png','sha256':'fixture'}]})


def test_ocr_overlaps_source_and_solve_but_is_joined_before_review(monkeypatch,settings,job,sample):
    image_job(job);solving=threading.Event();started=threading.Event();stages=[];requests={}
    page={'image_id':'I1','role':'question','blocks':[{'kind':'text','text':'原图文字','bbox':[0,0,8,8]}],'warnings':['不是题设真值']}
    def recognize(cfg,request,directory,audit):
        started.set();assert solving.wait(3)
        assert 'ocr_evidence' not in request
        return [copy.deepcopy(page)]
    monkeypatch.setattr('math_agent.ocr.recognize',recognize)
    source,candidate,review=copy.deepcopy(sample)
    class Provider:
        def __init__(self,*args):self.calls=0
        def generate(self,stage,messages,**kwargs):
            self.calls+=1;stages.append(stage)
            text=json.loads(messages[-1]['content'][0]['text']);requests[stage]=text
            if stage=='source':
                assert started.wait(3) and text['ocr_evidence']==[]
                return source
            if stage=='solve':solving.set();return pack(candidate)
            assert stage=='review' and text['ocr_evidence']==[page]
            return pack_review(review)
        def close(self):pass
    cfg=replace(settings,compact_tools=True,overlap_ocr=True,ocr_url='http://127.0.0.1:12345')
    runner=Runner(cfg,job[1],Provider,MemoryCache,renderer);runner.run()
    report=json.loads((job[2]/'report.json').read_text())
    assert report['status']=='completed',report.get('error')
    assert stages==['source','solve','review']
    assert json.loads((job[2]/'ocr.json').read_text())==[page]
    assert runner.pending_ocr.joined


def test_failed_parallel_ocr_never_reaches_review_or_publish(monkeypatch,settings,job,sample):
    image_job(job);stages=[]
    def recognize(*args):raise RuntimeError('OCR evidence unavailable')
    monkeypatch.setattr('math_agent.ocr.recognize',recognize)
    class Provider:
        def __init__(self,*args):self.calls=0
        def generate(self,stage,*args,**kwargs):
            self.calls+=1;stages.append(stage)
            assert stage in {'source','solve'}
            return copy.deepcopy(sample[0]) if stage=='source' else pack(sample[1])
        def close(self):pass
    cfg=replace(settings,compact_tools=True,overlap_ocr=True,ocr_url='http://127.0.0.1:12345')
    Runner(cfg,job[1],Provider,MemoryCache,renderer).run()
    report=json.loads((job[2]/'report.json').read_text())
    assert report['status']=='failed' and 'OCR evidence unavailable' in report['error']
    assert stages==['source','solve'] and job[0].get(job[1])['status']=='failed'
