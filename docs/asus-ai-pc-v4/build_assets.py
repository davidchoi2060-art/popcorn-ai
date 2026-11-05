#!/usr/bin/env python3
"""ASUS AI PC 기획전 소재 생성 기록 겸 재생성 도구 (PIL만 사용, 외부 전송 없음).

사용: python build_assets.py <v3 추출 폴더> <v5 추출 폴더> <출력 폴더>
- GT502: PC1이 제작한 v5 소재를 형식 변환·축소만 한다(가로세로 비율 유지, 그림 내용 변경 없음).
- 배경: v5 desktop hero의 제품 없는 왼쪽 영역만 잘라 쓴다.
- 사용 예시: v3 PNG에서 GT302와 글자 없는 영역만 잘라낸다. 사용 예시 배지는 지운다(HTML로 다시 얹는다).
- ASUS 로고: v3 배너에서 추출해 흰색 단색으로 만든다.
"""
import pathlib
import sys

from PIL import Image, ImageDraw, ImageFilter

V3, V5, OUT = (pathlib.Path(a) for a in sys.argv[1:4])
OUT.mkdir(parents=True, exist_ok=True)


def build_gt502():
    cut = Image.open(V5 / "gt502-black-cutout.png").convert("RGBA")
    assert cut.size == (1254, 1254)
    cut.resize((800, 800), Image.LANCZOS).save(OUT / "gt502-black-cutout.webp", quality=90, method=6)
    desk = Image.open(V5 / "gt502-desktop-hero.png").convert("RGB")
    assert desk.size == (2172, 724)
    desk.save(OUT / "hero-desktop.webp", quality=86, method=6)
    mob = Image.open(V5 / "gt502-mobile-hero.png").convert("RGB")
    assert mob.size == (1122, 1402)
    mob.save(OUT / "hero-mobile.webp", quality=86, method=6)
    # 제품이 시작되는 x=1422보다 충분히 왼쪽만 잘라 배경으로 쓴다.
    desk.crop((0, 0, 1340, 724)).save(OUT / "bg-arcs.webp", quality=80, method=6)


def build_logo():
    src = Image.open(V3 / "pc/01-banner.png").convert("RGB").crop((100, 36, 404, 108))
    a = src.getchannel("R").point(lambda v: max(0, min(255, (v - 70) * 255 // 150)))
    logo = Image.new("RGBA", src.size, (255, 255, 255, 255))
    logo.putalpha(a)
    logo.crop(logo.getbbox()).save(OUT / "logo-asus-white.png", optimize=True)


def crop_use(src, box, name, chip=None, scale=2):
    im = Image.open(V3 / src).convert("RGB")
    if chip:
        # 배지 바로 아래 띠를 늘려 덮는다(배지 픽셀이 섞이면 어두운 네모가 남는다). 경계는 흐린다.
        chip = (chip[0] - 8, max(0, chip[1] - 8), chip[2] + 10, chip[3] + 8)
        cw, ch = chip[2] - chip[0], chip[3] - chip[1]
        patch = im.crop((chip[0], chip[3] + 3, chip[2], chip[3] + 15)).resize((cw, ch)).filter(ImageFilter.GaussianBlur(5))
        m = Image.new("L", (cw, ch), 0)
        ImageDraw.Draw(m).rectangle((0, 0, cw - 4, ch - 4), fill=255)
        im.paste(patch, chip[:2], m.filter(ImageFilter.GaussianBlur(2)))
    c = im.crop(box)
    c = c.resize((c.width * scale, c.height * scale), Image.LANCZOS).filter(ImageFilter.UnsharpMask(1.6, 45, 2))
    c.save(OUT / f"use-{name}.webp", quality=84, method=6)


build_gt502()
build_logo()
crop_use("pc/03-business.png", (446, 398, 752, 498), "business-1", (450, 400, 528, 424))
crop_use("pc/03-business.png", (446, 518, 758, 612), "business-2", (450, 520, 528, 544))
crop_use("pc/03-business.png", (446, 628, 758, 722), "business-3", (450, 630, 528, 654))
crop_use("mobile/04-video.png", (44, 768, 486, 930), "video-1", (46, 770, 156, 800))
crop_use("mobile/04-video.png", (44, 1080, 486, 1236), "video-2", (46, 1082, 156, 1112))
crop_use("pc/04-video.png", (26, 836, 300, 944), "video-3", (42, 838, 136, 866))
crop_use("mobile/05-local-ai.png", (330, 790, 688, 944), "ai-1")
crop_use("mobile/05-local-ai.png", (330, 1091, 688, 1230), "ai-2")
crop_use("mobile/05-local-ai.png", (330, 1376, 688, 1502), "ai-3")
