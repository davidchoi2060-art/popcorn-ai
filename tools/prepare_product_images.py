"""Archive merchant photos and trim only uniform outer margins (Pillow required).

Original bytes are immutable. Detail PNGs preserve the decoded product pixels;
no generative editing, background replacement, or inferred product reconstruction.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
from statistics import median
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from PIL import Image, ImageChops, ImageOps

MAX_BYTES = 10 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 20_000_000


def trim_bounds(im):
    rgba = im.convert('RGBA')
    w, h = rgba.size
    rgb = rgba.convert('RGB')
    alpha = rgba.getchannel('A')
    if alpha.getextrema()[0] < 255:
        mask = alpha.point(lambda x: 255 if x > 8 else 0)
        mode = 'transparent_margin'
    else:
        # All four corners must agree. Nonuniform backgrounds are kept intact.
        corners = [(x, y) for x in (0, w-1) for y in (0, h-1)]
        colors = [rgb.getpixel(p) for p in corners]
        bg = tuple(int(median(c[k] for c in colors)) for k in range(3))
        if max(abs(c[k]-bg[k]) for c in colors for k in range(3)) > 18:
            return (0, 0, w, h), 'nonuniform_corners_keep_original'
        diff = ImageChops.difference(rgb, Image.new('RGB', (w, h), bg))
        r, g, b = diff.split()
        mask = ImageChops.lighter(ImageChops.lighter(r, g), b).point(lambda x: 255 if x > 18 else 0)
        mode = 'uniform_margin'
    bbox = mask.getbbox()
    if not bbox:
        return (0, 0, w, h), 'empty_foreground_keep_original'
    pad = max(3, math.ceil(max(w, h)*0.02))
    box = (max(0,bbox[0]-pad),max(0,bbox[1]-pad),min(w,bbox[2]+pad),min(h,bbox[3]+pad))
    if box == (0,0,w,h): mode = 'no_outer_margin'
    return box, mode


def prepare(row, output):
    code = int(row['product_code'])
    url = row.get('merchant_image_url') or row.get('image_url')
    result = dict(product_code=code, name=row['name'], source_url=url)
    if not url:
        return dict(result, status='missing_source')
    try:
        parsed = urlparse(url)
        if parsed.scheme != 'https' or parsed.hostname not in ('www.popcornpc.co.kr','popcornpc.co.kr'):
            raise ValueError('Unexpected merchant image host')
        with urlopen(Request(url,headers={'User-Agent':'PopcornAI product-image archive'}),timeout=30) as response:
            if urlparse(response.url).hostname not in ('www.popcornpc.co.kr','popcornpc.co.kr'):
                raise ValueError('Unexpected image redirect')
            raw = response.read(MAX_BYTES+1)
        if len(raw)>MAX_BYTES: raise ValueError('Image exceeds size limit')
        sha = hashlib.sha256(raw).hexdigest()
        with Image.open(io.BytesIO(raw)) as original:
            fmt=original.format
            if fmt not in ('JPEG','PNG','WEBP','GIF'): raise ValueError('Unsupported image format')
            if getattr(original,'n_frames',1)>1: raise ValueError('Animated image requires review')
            im=ImageOps.exif_transpose(original).convert('RGBA')
        box, mode=trim_bounds(im)
        cropped=im.crop(box)
        key=Path('products')/str(code)/sha[:16]
        folder=output/key;folder.mkdir(parents=True,exist_ok=True)
        original_path=folder/('original.'+{'JPEG':'jpg','PNG':'png','WEBP':'webp','GIF':'gif'}[fmt])
        if original_path.exists():
            assert original_path.read_bytes()==raw, 'Immutable archive mismatch'
        else: original_path.write_bytes(raw)
        detail_path=folder/'detail.png'
        if not detail_path.exists():cropped.save(detail_path,compress_level=9)
        with Image.open(detail_path) as check:
            assert check.convert('RGBA').tobytes()==cropped.tobytes(), 'Cropped pixels changed'
        thumb=cropped.copy();thumb.thumbnail((384,384),Image.Resampling.LANCZOS)
        thumb_path=folder/'thumb.webp'
        if not thumb_path.exists():thumb.save(thumb_path,lossless=True,method=6)
        with Image.open(thumb_path) as check:
            assert check.convert('RGBA').tobytes()==thumb.tobytes(), 'Use a new version for changed processing rules'
        return dict(result,status='ready',sha256=sha,original_key=original_path.relative_to(output).as_posix(),
                    detail_key=detail_path.relative_to(output).as_posix(),thumbnail_key=thumb_path.relative_to(output).as_posix(),
                    original_size=list(im.size),detail_size=list(cropped.size),crop_box=list(box),crop_mode=mode,
                    removed_area_ratio=round(1-cropped.width*cropped.height/(im.width*im.height),4),
                    detail_sha256=hashlib.sha256(detail_path.read_bytes()).hexdigest(),
                    original_bytes=len(raw),detail_bytes=detail_path.stat().st_size,thumbnail_bytes=thumb_path.stat().st_size)
    except Exception as exc:
        return dict(result,status='error',error=f'{type(exc).__name__}: {exc}')


def main():
    p=argparse.ArgumentParser();p.add_argument('input',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    rows=json.loads(a.input.read_text(encoding='utf-8'));a.output.mkdir(parents=True,exist_ok=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=[]
        for i,result in enumerate(pool.map(lambda row:prepare(row,a.output),rows),1):
            results.append(result)
            if i%25==0:print(f'Processed {i}/{len(rows)}',flush=True)
    manifest=dict(created_at=datetime.now(timezone.utc).isoformat(),method='original-pixel uniform-margin crop; 2% safety padding',
                  status_counts={k:sum(r['status']==k for r in results) for k in ('ready','missing_source','error')},items=results)
    (a.output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(manifest['status_counts']),flush=True)


if __name__=='__main__':main()
