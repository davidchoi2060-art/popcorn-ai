"""ASUS 기획전 사용 예시 9장을 코드로 그린다. 실제 제품 화면이 아니라 설명용 그림이다.

    python tools/asus_use_art.py            # SVG 원본 9장 + WebP 9장 생성
    python tools/asus_use_art.py --svg      # SVG 만 생성

원본 SVG: docs/asus-ai-pc-v4/use-art/  ·  결과: mockups/mvp4/assets/images/asus/use-*.webp (파일명 유지)
표시 크기는 상세 화면 360x144, 모바일 약 310x124 이므로 캔버스를 4배(1440x576)로 잡는다.
- 글자는 50 이상만 쓴다(360 폭에서 12.5px, 310 폭에서 약 11px).
- 왼쪽 위 「사용 예시」 배지가 덮는 자리(폭 410, 높이 160)에는 제목줄 배경만 둔다.
- 수치 · 성능 · 실제 서비스처럼 보이는 내용은 넣지 않는다.
렌더링: 로컬 Chrome 헤드리스 + 저장소 글꼴(PretendardVariable). Pillow 로 WebP 변환.
"""
import argparse
import base64
import os
import subprocess
import sys
import tempfile
from io import BytesIO
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SVG_DIR = ROOT / 'docs/asus-ai-pc-v4/use-art'
OUT_DIR = ROOT / 'mockups/mvp4/assets/images/asus'
FONT = ROOT / 'mockups/mvp4/assets/fonts/PretendardVariable.woff2'
CHROME_PATHS = ('C:/Program Files/Google/Chrome/Application/chrome.exe', '/usr/bin/google-chrome')
W, H = 1440, 576

NAVY = '#07143F'
BLUE = '#0B4FEA'
DEEP = '#0A2BB5'
CYAN = '#3FE6FF'
PALE = '#E6EEFF'
LINE = '#B9C9EE'
WHITE = '#FFFFFF'
INK = '#07143F'
AMBER = '#FFB400'


def rect(x, y, w, h, fill, r=0, stroke=None, sw=0):
    s = f' stroke="{stroke}" stroke-width="{sw}"' if stroke else ''
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}"{s}/>'


def text(x, y, s, size=54, fill=INK, weight=800, anchor='start'):
    return f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{fill}" text-anchor="{anchor}">{s}</text>'


def path(d, stroke=INK, sw=10, fill='none'):
    return f'<path d="{d}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}" stroke-linecap="round" stroke-linejoin="round"/>'


def lines(x, y, widths, color=LINE, h=22, gap=44):
    return ''.join(rect(x, y + i * gap, w, h, color, h / 2) for i, w in enumerate(widths))


def arrow(x, y, length=70, color=CYAN, sw=16):
    return path(f'M{x} {y}H{x + length}M{x + length - 26} {y - 26}L{x + length} {y}L{x + length - 26} {y + 26}', color, sw)


def doc(x, y, w=92, h=118, fill=WHITE, stroke=BLUE):
    fold = 30
    d = f'M{x} {y}H{x + w - fold}L{x + w} {y + fold}V{y + h}H{x}Z'
    inner = path(f'M{x + 20} {y + h * .48:.0f}H{x + w - 20}M{x + 20} {y + h * .72:.0f}H{x + w - 20}', stroke, 9)
    return path(d, stroke, 10, fill) + path(f'M{x + w - fold} {y}V{y + fold}H{x + w}', stroke, 10) + inner


def magnifier(x, y, r=26, color=BLUE):
    return f'<circle cx="{x}" cy="{y}" r="{r}" fill="none" stroke="{color}" stroke-width="11"/>' + path(f'M{x + r * .72:.0f} {y + r * .72:.0f}L{x + r * 1.5:.0f} {y + r * 1.5:.0f}', color, 12)


def check(x, y, color=BLUE):
    return f'<circle cx="{x}" cy="{y}" r="24" fill="{color}"/>' + path(f'M{x - 12} {y}L{x - 3} {y + 10}L{x + 13} {y - 10}', WHITE, 8)


def wave(x, y, heights, color=CYAN, step=26, w=14):
    return ''.join(rect(x + i * step, y - h / 2, w, h, color, w / 2) for i, h in enumerate(heights))


def mic(x, y, color=WHITE):
    return rect(x - 20, y - 50, 40, 72, color, 20) + path(f'M{x - 36} {y - 4}A36 36 0 0 0 {x + 36} {y - 4}M{x} {y + 32}V{y + 52}M{x - 22} {y + 52}H{x + 22}', color, 10)


def gear(x, y, r=38, color=BLUE):
    teeth = ''.join(f'<rect x="{x - 9}" y="{y - r - 16}" width="18" height="24" rx="4" fill="{color}" transform="rotate({a} {x} {y})"/>' for a in range(0, 360, 45))
    return teeth + f'<circle cx="{x}" cy="{y}" r="{r}" fill="none" stroke="{color}" stroke-width="16"/>'


def scene(x, y, w, h, r=14):
    """풍경 자리 표시: 하늘 · 산 · 해. 사진처럼 보이지 않게 단순한 면으로만 그린다."""
    clip = f'clip{x}{y}'
    return (f'<clipPath id="{clip}"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}"/></clipPath><g clip-path="url(#{clip})">' +
            rect(x, y, w, h, '#2F7BFF') + f'<circle cx="{x + w * .74:.0f}" cy="{y + h * .3:.0f}" r="{h * .15:.0f}" fill="{AMBER}"/>' +
            f'<path d="M{x} {y + h}L{x + w * .3:.0f} {y + h * .42:.0f}L{x + w * .55:.0f} {y + h}Z" fill="{DEEP}"/>' +
            f'<path d="M{x + w * .32:.0f} {y + h}L{x + w * .68:.0f} {y + h * .5:.0f}L{x + w} {y + h}Z" fill="{NAVY}"/></g>')


def frame(title, body):
    """화면 틀: 얇은 베젤 + 제목줄. 제목은 배지를 피해 오른쪽에 둔다."""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="Pretendard, \'Malgun Gothic\', sans-serif">' +
            rect(0, 0, W, H, NAVY) + rect(14, 14, W - 28, H - 28, '#123A9E', 22) +
            rect(14, 14, W - 28, 124, DEEP, 22) + rect(14, 100, W - 28, 38, DEEP) +
            text(W - 60, 96, title, 58, WHITE, 800, 'end') + body + '</svg>')


def panel(x, y, w, h, fill=WHITE):
    return rect(x, y, w, h, fill, 22)


def b1():
    return frame('문서 검색',
                 panel(44, 160, 660, 376) + rect(72, 184, 604, 88, PALE, 44) + magnifier(122, 224) + text(176, 246, '보증 조건', 52) +
                 doc(84, 300, 74, 92) + rect(190, 318, 450, 24, CYAN, 12) + rect(190, 360, 300, 22, LINE, 11) +
                 doc(84, 418, 74, 92) + rect(190, 436, 410, 22, LINE, 11) + rect(190, 476, 260, 22, LINE, 11) +
                 arrow(722, 348, 66) +
                 panel(808, 160, 588, 376) + text(848, 234, '원문 확인', 54) +
                 lines(848, 268, [508, 440], LINE, 24, 48) + rect(848, 364, 508, 34, CYAN, 8) + lines(848, 424, [470, 300], LINE, 24, 48))


def b2():
    return frame('회의 정리',
                 panel(44, 160, 560, 376, NAVY) + f'<circle cx="324" cy="244" r="62" fill="{BLUE}"/>' + mic(324, 248) +
                 wave(82, 420, [40, 84, 130, 70, 150, 100, 56, 132, 88, 160, 76, 120, 60, 100, 44, 80], CYAN, 28, 16) +
                 arrow(622, 348, 62) +
                 panel(704, 160, 692, 176) + text(744, 228, '회의 요약', 54) + lines(744, 258, [612], LINE, 24, 46) + rect(744, 296, 420, 18, LINE, 9) +
                 panel(704, 352, 692, 184) + text(744, 420, '할 일', 54) + check(770, 484) + rect(812, 472, 540, 24, LINE, 12) + check(980, 408) + rect(1022, 396, 330, 24, LINE, 12))


def tag(x, y, label, fill):
    return rect(x, y, 170, 72, fill, 36) + text(x + 85, y + 53, label, 50, WHITE, 800, 'middle')


def b3():
    rows = [('배송', BLUE, 168), ('교환', '#7A3FF0', 286), ('AS', '#0A7F8F', 404)]
    body = panel(44, 160, 640, 376)
    for label, color, y in rows:
        body += tag(76, y + 12, label, color) + rect(272, y + 36, 372, 26, LINE, 13)
    body += arrow(702, 348, 66) + panel(790, 160, 606, 376) + text(830, 234, '답변 초안', 54)
    body += lines(830, 272, [526, 470, 526, 330], LINE, 24, 44)
    body += path('M1296 470L1350 416L1376 442L1322 496L1292 500Z', BLUE, 10, CYAN)
    return frame('문의 분류', body)


def timeline(x, y, w, tracks):
    out = ''
    for row, clips in enumerate(tracks):
        for start, length, color in clips:
            out += rect(x + start, y + row * 72, length, 58, color, 12)
    return out


def v1():
    body = panel(44, 160, 1352, 376, NAVY) + scene(70, 180, 470, 190)
    body += f'<circle cx="305" cy="275" r="48" fill="{WHITE}"/><path d="M288 246L334 275L288 304Z" fill="{BLUE}"/>'
    body += text(600, 248, '미리보기', 60, WHITE) + text(600, 334, '자르기 · 색 보정', 52, CYAN, 700)
    body += rect(70, 392, 1300, 8, '#3B5BB8', 4)
    body += timeline(70, 400, 1300, [[(0, 420, BLUE), (432, 540, '#2F7BFF'), (984, 316, BLUE)], [(120, 380, CYAN), (660, 460, CYAN)]])
    body += rect(800, 384, 10, 150, AMBER, 5) + '<path d="M785 376H825L805 402Z" fill="%s"/>' % AMBER
    return frame('영상 편집', body)


def v2():
    heights = [30, 70, 120, 60, 150, 96, 40, 110, 76, 140, 54, 34, 90, 130, 70, 150, 100, 50, 124, 80, 36, 66, 118, 150, 88, 48, 104, 136, 62, 92, 30, 74, 122, 58, 96, 40]
    body = panel(44, 160, 1352, 376, NAVY)
    body += rect(76, 184, 400, 168, '#1D4FC4', 14) + rect(516, 184, 450, 168, '#1D4FC4', 14) + rect(1006, 184, 358, 168, '#1D4FC4', 14)
    body += wave(88, 268, heights, CYAN, 36, 18)
    for x, w, label in ((76, 400, '자막 구간'), (516, 450, '받아쓰기'), (1006, 358, '수정')):
        body += rect(x, 376, w, 132, WHITE, 18) + text(x + w / 2, 460, label, 56, INK, 800, 'middle')
    return frame('자막 만들기', body)


def v3():
    body = panel(44, 160, 136, 376, NAVY)
    body += path('M86 206H138V258H86Z', WHITE, 10) + path('M86 318L136 300L138 354L100 366Z', CYAN, 10) + text(112, 492, 'T', 76, WHITE, 800, 'middle')
    body += panel(200, 160, 760, 376, '#DCE7FF') + scene(236, 184, 688, 328, 8)
    body += rect(236, 184, 688, 328, 'none', 8, WHITE, 8)
    for x, y in ((236, 184), (924, 184), (236, 512), (924, 512)):
        body += rect(x - 16, y - 16, 32, 32, WHITE, 6, BLUE, 8)
    body += panel(980, 160, 416, 376) + text(1018, 226, '시안 고르기', 52)
    body += scene(1018, 256, 340, 112, 10) + scene(1018, 392, 340, 112, 10) + rect(1018, 392, 340, 112, 'none', 10, BLUE, 10)
    return frame('썸네일 편집', body)


def a1():
    body = panel(44, 160, 540, 376, NAVY)
    body += doc(100, 196, 96, 122) + doc(222, 196, 96, 122, '#CFE0FF') + doc(344, 196, 96, 122)
    body += rect(84, 356, 472, 88, WHITE, 44) + magnifier(134, 398) + text(188, 420, '사내 문서', 52)
    body += arrow(602, 348, 62)
    body += panel(684, 160, 712, 376) + text(724, 234, '답변', 56)
    body += lines(724, 266, [632, 560, 400], LINE, 24, 46)
    body += rect(724, 420, 420, 88, CYAN, 44) + doc(756, 434, 44, 60, WHITE, INK) + text(824, 482, '출처 문서', 50)
    return frame('문서에서 찾기', body)


def a2():
    body = panel(44, 160, 660, 376) + panel(736, 160, 660, 376)
    for x, label, color, widths in ((44, '모델 A', BLUE, [560, 480, 560, 300]), (736, '모델 B', '#7A3FF0', [420, 560, 340, 500])):
        body += rect(x + 40, 188, 250, 88, color, 44) + text(x + 165, 250, label, 54, WHITE, 800, 'middle')
        body += lines(x + 40, 310, widths, LINE, 26, 50)
    return frame('같은 질문 비교', body)


def a3():
    body = panel(44, 160, 360, 290) + doc(174, 192, 100, 130) + text(224, 408, '문서', 58, INK, 800, 'middle')
    body += arrow(420, 305, 76)
    body += panel(512, 160, 416, 290, NAVY) + rect(632, 192, 176, 132, BLUE, 26) + text(720, 280, 'AI', 76, WHITE, 800, 'middle') + text(720, 408, '분류 · 초안', 54, CYAN, 800, 'middle')
    body += arrow(944, 305, 76)
    body += panel(1036, 160, 360, 290) + gear(1216, 256, 46) + text(1216, 408, '도구 설정', 58, INK, 800, 'middle')
    body += rect(44, 466, 1352, 70, '#0A2BB5', 18) + check(590, 501, CYAN) + text(630, 520, '담당자 확인', 50, WHITE, 800)
    return frame('업무 연결', body)


SCENES = {'use-business-1': b1, 'use-business-2': b2, 'use-business-3': b3,
          'use-video-1': v1, 'use-video-2': v2, 'use-video-3': v3,
          'use-ai-1': a1, 'use-ai-2': a2, 'use-ai-3': a3}


def chrome():
    for p in (os.environ.get('CHROME_BIN'), *CHROME_PATHS):
        if p and Path(p).exists():
            return p
    sys.exit('Chrome 을 찾지 못했습니다')


def render(svg, chrome_bin):
    font = base64.b64encode(FONT.read_bytes()).decode()
    page = ('<!doctype html><meta charset="utf-8"><style>@font-face{font-family:Pretendard;src:url(data:font/woff2;base64,' + font +
            ') format("woff2");font-weight:100 900}html,body{margin:0;padding:0;overflow:hidden;background:#07143F}svg{display:block}</style>' + svg)
    with tempfile.TemporaryDirectory() as tmp:
        html, png = Path(tmp) / 'a.html', Path(tmp) / 'a.png'
        html.write_text(page, encoding='utf-8')
        subprocess.run([chrome_bin, '--headless=new', '--disable-gpu', '--hide-scrollbars', '--force-device-scale-factor=1', f'--window-size={W},{H}',
                        '--virtual-time-budget=3000', f'--user-data-dir={tmp}/p', f'--screenshot={png}', html.as_uri()],
                       check=True, capture_output=True, timeout=120)
        im = Image.open(png).convert('RGB')
        im.load()
    if im.size != (W, H):
        sys.exit(f'렌더 크기 오류 {im.size}')
    return im


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--svg', action='store_true', help='SVG 만 생성')
    args = ap.parse_args()
    SVG_DIR.mkdir(parents=True, exist_ok=True)
    chrome_bin = None if args.svg else chrome()
    for name, draw in SCENES.items():
        svg = draw()
        (SVG_DIR / f'{name}.svg').write_text(svg + '\n', encoding='utf-8')
        if args.svg:
            continue
        buf = BytesIO()
        render(svg, chrome_bin).save(buf, 'WEBP', quality=92, method=6)
        (OUT_DIR / f'{name}.webp').write_bytes(buf.getvalue())
        print(name, len(buf.getvalue()))


if __name__ == '__main__':
    main()
