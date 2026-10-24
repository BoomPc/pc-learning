"""Lossless pixel tiles for provider limits; original task images stay unchanged."""
import base64,copy,hashlib,io,json,threading
from collections import OrderedDict
from typing import NamedTuple
from PIL import Image

MAX_SIDE=4096  # Also valid when the conversation grows beyond 14 images.
MAX_IMAGES=600
MAX_BODY=48*1024*1024


class Tile(NamedTuple):
    origin_sha256: str
    origin_size: tuple
    kind: str
    pixel_box: tuple | None
    size: tuple
    sha256: str
    url: str


def _split_image(url,max_side):
    raw=base64.b64decode(url.split(',',1)[1],validate=True)
    with Image.open(io.BytesIO(raw)) as original:
        w,h=original.size
        if max(w,h)<=max_side and len(raw)<=32*1024*1024:return ()
        if original.format not in {'PNG','JPEG','WEBP','GIF'}:raise ValueError('不支持的原图格式')
        if getattr(original,'n_frames',1)>1:raise ValueError('超限动态图不能静默只传第一帧')
        sha=hashlib.sha256(raw).hexdigest()
        # Overview is for layout only. Every original pixel is also carried in tiles.
        overview=original.copy();overview.thumbnail((2048,2048))
        images=[('overview',None,overview)];result=[]
        stride=max_side-128
        for y in range(0,h,stride):
            for x in range(0,w,stride):
                box=(x,y,min(w,x+max_side),min(h,y+max_side))
                images.append(('original_pixels',box,original.crop(box)))
        for kind,box,img in images:
            encoded=io.BytesIO();img.save(encoded,format='PNG');data=encoded.getvalue()
            if len(data)>32*1024*1024:raise ValueError('单个原像素裁片仍超过模型文件大小上限')
            result.append(Tile(sha,(w,h),kind,box,tuple(img.size),hashlib.sha256(data).hexdigest(),
                               'data:image/png;base64,'+base64.b64encode(data).decode()))
        return tuple(result)


class PixelTiles:
    """Bounded task-local immutable input preparation, never inference results.

    Shared by a task's providers. The lock prevents duplicate first-time PNG
    encoding when two question agents request the same original concurrently.
    Role and message/part positions are deliberately excluded and rebuilt fresh.
    """
    def __init__(self,max_entries=8,max_bytes=32*1024*1024):
        self.max_entries=max_entries;self.max_bytes=max_bytes
        self._entries=OrderedDict();self._bytes=0;self._hits=0;self._misses=0
        self._lock=threading.RLock()

    def get(self,url,max_side):
        key=(url,max_side)
        with self._lock:
            if key in self._entries:
                self._hits+=1;self._entries.move_to_end(key)
                return self._entries[key][0]
            self._misses+=1
            tiles=_split_image(url,max_side)
            weight=len(url)+sum(len(t.url) for t in tiles)
            if tiles and self.max_entries>0 and weight<=self.max_bytes:
                while self._entries and (len(self._entries)>=self.max_entries or self._bytes+weight>self.max_bytes):
                    _,(_,old_weight)=self._entries.popitem(last=False);self._bytes-=old_weight
                self._entries[key]=(tiles,weight);self._bytes+=weight
            return tiles

    def snapshot(self):
        with self._lock:return {'hits':self._hits,'misses':self._misses,'entries':len(self._entries),'bytes':self._bytes}


def prepare_messages(messages,pixel_cache=None):
    history=copy.deepcopy(messages);manifest=[];image_count=0
    for mi,m in enumerate(history):
        if not isinstance(m.get('content'),list):continue
        parts=[]
        for pi,part in enumerate(m['content']):
            if part.get('type')!='image_url':parts.append(part);continue
            url=part['image_url']['url']
            if not url.startswith('data:'):parts.append(part);image_count+=1;continue
            tiles=pixel_cache.get(url,MAX_SIDE) if pixel_cache is not None else _split_image(url,MAX_SIDE)
            if not tiles:parts.append(part);image_count+=1;continue
            for tile in tiles:
                record={'message':mi,'part':pi,'origin_sha256':tile.origin_sha256,'origin_size':list(tile.origin_size),
                    'kind':tile.kind,'pixel_box':list(tile.pixel_box) if tile.pixel_box is not None else None,
                    'size':list(tile.size),'sha256':tile.sha256}
                manifest.append(record)
                parts.extend([{'type':'text','text':'同一原图的传输分区（保持前述图片编号与question/answer角色）：'+json.dumps(record,ensure_ascii=False)+
                    ('；总览仅看布局，细小文字以随附原始像素裁片为准。' if tile.kind=='overview' else '；这是原图对应pixel_box的完整像素，未重绘，裁片坐标不是数学坐标。')},
                    {'type':'image_url','image_url':{'url':tile.url,'detail':'original'}}])
                image_count+=1
        m['content']=parts
    if image_count>MAX_IMAGES:raise ValueError('模型图片数量超过上限；未发出付费请求')
    return history,manifest


def check_body(body):
    size=len(json.dumps(body,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode())
    if size>MAX_BODY:raise ValueError('模型请求超过48MiB；未发出付费请求')
    return size
