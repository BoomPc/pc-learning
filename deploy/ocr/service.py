"""CPU-only, private single-inference service. No arbitrary URLs or paths accepted."""
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from flask import Flask, request, jsonify
from PIL import Image, ImageOps
from waitress import serve
from paddleocr import PPStructureV3

PROFILE = 'ppstructure3-paddleocr3.4.0-paddlex3.4.3-paddle3.2.2-layoutplusL-ocr5mobileDet-serverRec-formulaplusS-mkldnn-cache1-batch1-v3'
TOKEN = os.environ['AGENT_ACCESS_TOKEN']
CACHE = Path(os.getenv('OCR_CACHE_DIR','/var/lib/math-agent-8666/ocr-cache'))
CACHE.mkdir(parents=True, exist_ok=True)
lock = threading.Lock()
pipeline = PPStructureV3(device='cpu', cpu_threads=4, enable_mkldnn=True, mkldnn_cache_capacity=1,
    layout_detection_model_name='PP-DocLayout_plus-L',
    text_detection_model_name='PP-OCRv5_mobile_det',
    text_recognition_model_name='PP-OCRv5_server_rec',
    text_recognition_batch_size=1,
    formula_recognition_model_name='PP-FormulaNet_plus-S',
    formula_recognition_batch_size=1,
    use_table_recognition=False, use_seal_recognition=False,
    use_chart_recognition=False, use_region_detection=False,
    use_doc_orientation_classify=False, use_doc_unwarping=False,
    use_textline_orientation=False, use_formula_recognition=True)
app=Flask(__name__)
app.config['MAX_CONTENT_LENGTH']=21*1024*1024

@app.get('/healthz')
def health(): return jsonify(ready=True, profile=PROFILE)

@app.post('/recognize')
def recognize():
    if not hmac.compare_digest(request.headers.get('Authorization','').encode(),('Bearer '+TOKEN).encode()):
        return jsonify(error='unauthorized'),401
    if 'image' not in request.files: return jsonify(error='image required'),400
    raw=request.files['image'].read()
    try:
        with Image.open(io.BytesIO(raw)) as source:
            if source.width*source.height>16_000_000 or max(source.size)>10000:
                return jsonify(error='image too large'),400
            rgba=ImageOps.exif_transpose(source).convert('RGBA')
            im=Image.new('RGB',rgba.size,'white'); im.paste(rgba,mask=rgba.getchannel('A'))
    except Exception: return jsonify(error='invalid image'),400
    digest=hashlib.sha256(PROFILE.encode()+str(im.size).encode()+im.tobytes()).hexdigest()
    cached=CACHE/(digest+'.json')
    started=time.monotonic()
    if not lock.acquire(blocking=False): return jsonify(error='OCR busy'),503
    try:
        if cached.exists():
            data=json.loads(cached.read_text()); data.update(cache_hit=True,seconds=round(time.monotonic()-started,3))
            return jsonify(data)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'image.png'; im.save(path)
            results=pipeline.predict(str(path))
            blocks=[]; scores=[]
            for result in results:
                data=result.json
                if isinstance(data,str): data=json.loads(data)
                data=data['res']
                for b in data['parsing_res_list']:
                    blocks.append(dict(kind=b['block_label'],text=b['block_content'],bbox=b['block_bbox']))
                scores.extend(data.get('overall_ocr_res',{}).get('rec_scores',[]))
        warnings=['OCR不是题设真值；公式识别未提供可信的逐公式置信度，须对照原图。',
                  '行内公式、图中点名和几何关系仍可能遗漏；不要从外观推断关系。']
        if any(float(s)<0.85 for s in scores): warnings.append('存在文字识别置信度低于0.85的区域。')
        text='\n'.join(b['text'] for b in blocks if b['text'])
        if not text.strip(): warnings.append('没有提取到文字，必须使用原图或请求补充清晰图片。')
        data=dict(engine='PaddleOCR + PP-FormulaNet',profile=PROFILE,blocks=blocks,text=text,
                  warnings=warnings,seconds=round(time.monotonic()-started,3),cache_hit=False)
        temp=cached.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False));temp.chmod(0o600);temp.replace(cached)
        return jsonify(data)
    except Exception as exc:
        app.logger.error('OCR failed: %s',type(exc).__name__)
        return jsonify(error='OCR inference failed'),500
    finally: lock.release()

if __name__=='__main__': serve(app,host='127.0.0.1',port=18666,threads=3)
