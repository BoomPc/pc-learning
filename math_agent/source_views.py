"""Bounded source-text crops: OCR locates pixels, never supplies geometry truth."""
import base64
import io
import math
from PIL import Image
from .storage import write_json


def source_text_views(request, directory, limit=10):
    images={i['id']:i for i in request['images'] if i['role']=='question'}
    content=[];manifest=[];seen=set()
    for page in request.get('ocr_evidence',[]):
        image_id=page.get('image_id');img=images.get(image_id)
        if not img or page.get('role')!='question' or not page.get('blocks') or len(manifest)>=limit:continue
        path=(directory/img['file']).resolve()
        if not path.is_relative_to(directory.resolve()):raise ValueError('图片路径越界')
        with Image.open(path) as original:
            w,h=original.size
            for block in page.get('blocks',[]):
                if len(manifest)>=limit:break
                if block.get('kind') not in {'text','formula','paragraph_title'}:continue
                box=block.get('bbox')
                if not isinstance(box,list) or len(box)!=4 or any(type(v) not in (int,float) or not math.isfinite(v) for v in box):continue
                l,t,r,b=box
                if not 0<=l<r<=w or not 0<=t<b<=h:continue
                # Small margin preserves punctuation and superscripts at detected borders.
                pixel=(max(0,math.floor(l)-12),max(0,math.floor(t)-12),min(w,math.ceil(r)+12),min(h,math.ceil(b)+12))
                key=(image_id,pixel)
                if key in seen:continue
                seen.add(key)
                crop=original.convert('RGB').crop(pixel)
                crop.thumbnail((1800,700),Image.Resampling.LANCZOS)
                folder=directory/'source-text-views';folder.mkdir(exist_ok=True)
                artifact=f'source-text-views/text-{len(manifest)+1:02d}.png';crop.save(directory/artifact)
                meta={'image_id':image_id,'role':'question','pixel_box':pixel,'artifact':artifact}
                manifest.append(meta)
                stream=io.BytesIO();crop.save(stream,format='PNG')
                content.extend([{'type':'text','text':f'原题{image_id}文字区域{pixel}：逐字查看像素，重点核对点名、撇号、上下标与符号；OCR仅定位，不能覆盖图片。'},
                    {'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(stream.getvalue()).decode()}}])
    write_json(directory/'source-text-views.json',manifest)
    return content
