"""Overlapping original-pixel strips, preserving source identity and full images."""
import base64
from PIL import Image
from .storage import write_json

def solve_views(request, directory, limit=8):
    content=[]; manifest=[]
    folder=directory/'solve-views'; folder.mkdir(exist_ok=True)
    for img in request['images']:
        path=(directory/img['file']).resolve()
        if not path.is_relative_to(directory.resolve()): raise ValueError('图片路径越界')
        with Image.open(path) as original:
            w,h=original.size
            if h<=1600: continue
            for top in range(0,h,1400):
                if len(manifest)>=limit: break
                bottom=min(h,top+1600)
                crop=original.crop((0,top,w,bottom))
                artifact=f'solve-views/strip-{len(manifest):02d}.png'
                crop.save(directory/artifact)
                meta={'image_id':img['id'],'role':img['role'],'pixel_box':[0,top,w,bottom],'artifact':artifact}
                manifest.append(meta)
                content.extend([{'type':'text','text':f'原图分区 {meta}。这是原始像素裁剪；answer角色仅是待核对参考答案，不是题设。'},
                    {'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode((directory/artifact).read_bytes()).decode()}}])
                if bottom==h: break
    write_json(directory/'solve-views.json',manifest)
    return content
