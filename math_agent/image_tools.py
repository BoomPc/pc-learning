"""Bounded read-only magnification of uploaded images, never model-selected files."""
import base64
import io
import math
from dataclasses import dataclass
from PIL import Image
from .tools import definition
from .storage import write_json

VIEW_REGION = definition('view_image_region', '放大本任务上传图片的局部，返回原始像素供你直接查看。核对点名撇号/下标、公式和明确标记；不生成或补画内容。bbox为原图归一化[left,top,right,bottom]，范围0到1。',
    {'image_id':{'type':'string','maxLength':40},
     'bbox':{'type':'array','items':{'type':'number','minimum':0,'maximum':1},'minItems':4,'maxItems':4},
     'reason':{'type':'string','minLength':1,'maxLength':500}}, ['image_id','bbox','reason'])

@dataclass
class ImageObservation:
    metadata: dict
    data_url: str

class ImageTools:
    def __init__(self, directory, images):
        self.directory, self.images = directory, {i['id']:i for i in images}
        self.count = len(list((directory/'image-views').glob('view-*.json')))

    def view(self, image_id, bbox, reason):
        if image_id not in self.images: raise ValueError('只能查看当前输入图片编号')
        if self.count >= 8: raise ValueError('本题局部读图次数达到8次上限')
        if not isinstance(reason,str) or not 1 <= len(reason) <= 500: raise ValueError('请说明局部查看目的')
        if len(bbox)!=4 or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1 for v in bbox):
            raise ValueError('bbox须为0到1的四个有限数字')
        l,t,r,b = bbox
        if l>=r or t>=b: raise ValueError('局部区域必须具有正宽高')
        img = self.images[image_id]
        path = (self.directory/img['file']).resolve()
        if not path.is_relative_to(self.directory.resolve()): raise ValueError('图片路径越界')
        with Image.open(path) as original:
            w,h=original.size
            box=(int(l*w),int(t*h),min(w,math.ceil(r*w)),min(h,math.ceil(b*h)))
            if box[2]-box[0]<16 or box[3]-box[1]<16: raise ValueError('区域过小，请包含周边文字或标记')
            crop=original.convert('RGB').crop(box)
            scale=min(3,1400/max(crop.size))
            crop=crop.resize((max(1,round(crop.width*scale)),max(1,round(crop.height*scale))),Image.Resampling.LANCZOS)
        self.count+=1
        folder=self.directory/'image-views';folder.mkdir(exist_ok=True)
        stem=f'view-{self.count:02d}'
        crop.save(folder/(stem+'.png'))
        meta={'ok':True,'image_id':image_id,'role':img['role'],'bbox':bbox,'pixel_box':box,
              'reason':reason,'artifact':'image-views/'+stem+'.png',
              'note':'原图裁切放大；文字仍需核对，参考答案图片不能充当题设。'}
        write_json(folder/(stem+'.json'),meta)
        stream=io.BytesIO();crop.save(stream,format='PNG')
        return ImageObservation(meta,'data:image/png;base64,'+base64.b64encode(stream.getvalue()).decode())
