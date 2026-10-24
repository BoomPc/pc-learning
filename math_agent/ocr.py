"""Private OCR client. OCR is evidence, never an authoritative geometry source."""
import time
import io
import httpx
from PIL import Image
from pydantic import BaseModel, Field, ConfigDict


class OCRBlock(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: str
    text: str = Field(max_length=30000)
    bbox: list[float] = Field(min_length=4, max_length=4)


class OCRPage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    engine: str
    profile: str
    blocks: list[OCRBlock] = Field(max_length=2000)
    text: str = Field(max_length=120000)
    warnings: list[str]
    seconds: float
    cache_hit: bool


def healthy(settings):
    if not settings.ocr_url: return True
    try:
        with httpx.Client(timeout=2, trust_env=False) as client:
            r = client.get(settings.ocr_url+'/healthz')
            return r.status_code == 200 and r.json().get('ready') is True
    except (httpx.HTTPError, ValueError): return False


def recognize_image(client, settings, path):
    """Preserve long originals; only partition the private OCR transport."""
    started = time.monotonic()
    with Image.open(path) as original:
        width, height = original.size
        tiled = width * height > 16_000_000 or max(width, height) > 10000 or path.stat().st_size > 20*1024*1024
        boxes = ([(x, y, min(x+2048, width), min(y+3072, height))
                  for y in range(0, height, 3072) for x in range(0, width, 2048)]
                 if tiled else [(0, 0, width, height)])
        pages = []
        for box in boxes:
            remaining = settings.ocr_timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise RuntimeError('OCR分区识别超过总时限；未跳过剩余原图')
            stream = io.BytesIO()
            if tiled:
                original.crop(box).save(stream, format='PNG'); stream.seek(0)
            else:
                stream = path.open('rb')
            try:
                response = client.post(settings.ocr_url+'/recognize',
                    headers={'Authorization':'Bearer '+settings.access_token},
                    files={'image':('image.png', stream, 'image/png')},
                    timeout=httpx.Timeout(remaining, connect=min(5, remaining)))
                response.raise_for_status()
                page = OCRPage.model_validate(response.json())
            finally:
                stream.close()
            if tiled:
                for block in page.blocks:
                    left, top, right, bottom = block.bbox
                    if not 0 <= left < right <= box[2]-box[0] or not 0 <= top < bottom <= box[3]-box[1]:
                        raise ValueError('OCR分区返回了越界区域，不能用于原图定位')
                    block.bbox = [left+box[0], top+box[1], right+box[0], bottom+box[1]]
            pages.append(page)
    if len({p.profile for p in pages}) != 1:
        raise ValueError('OCR分区模型配置不一致')
    if not tiled:
        return pages[0], boxes
    page = OCRPage(engine=pages[0].engine, profile=pages[0].profile+'/pixel-tiles-v1',
        blocks=[b for p in pages for b in p.blocks], text='\n'.join(p.text for p in pages),
        warnings=list(dict.fromkeys([(f'原图分区{list(box)}：{w}' if not p.text.strip() else w)
            for p,box in zip(pages,boxes) for w in p.warnings] +
            ['长图已按原像素分区识别；分区边界可能截断文字，必须对照完整原图。'])),
        seconds=sum(p.seconds for p in pages), cache_hit=all(p.cache_hit for p in pages))
    return page, boxes


def recognize(settings, request, directory, audit):
    if not settings.ocr_url or not request['images']: return []
    evidence = []
    with httpx.Client(timeout=httpx.Timeout(settings.ocr_timeout, connect=5), trust_env=False) as client:
        for img in request['images']:
            if img.get('role', 'question') != 'question':
                audit('ocr_policy', {'image_id': img['id'], 'status': 'not_requested',
                    'reason': '参考答案由解题与复核阶段直接查看原图，不用于题设OCR'})
                continue
            started = time.monotonic()
            audit('ocr', {'stage':'ocr', 'image_id':img['id'], 'status':'running'})
            try:
                page, boxes = recognize_image(client, settings, directory/img['file'])
            except (httpx.HTTPError, ValueError):
                raise RuntimeError('OCR服务失败或返回无效结果；本次停止，不静默跳过识别或自动重发模型') from None
            evidence.append({'image_id':img['id'], 'role':img['role'], **page.model_dump()})
            audit('ocr', {'stage':'ocr','image_id':img['id'],'status':'done',
                'elapsed_seconds':round(time.monotonic()-started,3),'engine_seconds':page.seconds,
                'cache_hit':page.cache_hit,'blocks':len(page.blocks),'warnings':page.warnings,
                'pixel_tiles':[list(b) for b in boxes]})
    return evidence
