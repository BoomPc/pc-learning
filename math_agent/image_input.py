"""Shared web/evaluation image ingestion; preserve pixels of long documents."""
import hashlib
import io
import threading
import warnings
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_IMAGE = 32 * 1024 * 1024
MAX_PIXELS = 64_000_000
MAX_REQUEST = 200 * 1024 * 1024
_decode_lock = threading.Lock()


def save_image(upload, target):
    raw = upload.stream.read(MAX_IMAGE + 1)
    if not raw or len(raw) > MAX_IMAGE:
        raise ValueError('每张图片必须非空且不超过32 MiB')
    try:
        # Serialize large decodes in the multi-threaded API process.
        with _decode_lock, warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as source:
                if source.format not in {'JPEG', 'PNG', 'WEBP'}:
                    raise ValueError('只接受 PNG、JPEG、WebP 图片')
                if source.width * source.height > MAX_PIXELS:
                    raise ValueError('图片超过6400万像素处理容量')
                if getattr(source, 'n_frames', 1) != 1:
                    raise ValueError('请提交静态图片')
                image = (ImageOps.exif_transpose(source)
                         if source.getexif().get(274, 1) in range(2, 9) else source)
                if image.mode == 'RGB':
                    image.save(target, format='PNG')
                elif image.mode == 'RGBA' or 'transparency' in image.info or image.mode == 'LA':
                    background = Image.new('RGB', image.size, 'white')
                    for y in range(0, image.height, 1024):
                        box = (0, y, image.width, min(y + 1024, image.height))
                        tile = image.crop(box).convert('RGBA')
                        background.paste(tile, (0, y), tile.getchannel('A'))
                    background.save(target, format='PNG')
                else:
                    image.convert('RGB').save(target, format='PNG')
        target.chmod(0o600)
        # The OCR client partitions large PNGs before private-service transport.
        if target.stat().st_size > MAX_REQUEST:
            target.unlink()
            raise ValueError('图片解码后的文件超过服务处理容量')
    except (UnidentifiedImageError, OSError, Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise ValueError('图片损坏、格式不支持或超过服务处理容量') from None
    with target.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()
