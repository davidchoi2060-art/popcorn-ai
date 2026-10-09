"""개발 서버 고객 추천 결과 점검(읽기 전용) — .github/workflows/dev-screen-check.yml 이 부른다.

화면(mockups/mvp3/api-client.js)과 같은 두 요청을 보낸다:
  POST /api/talk/parse {text}  ->  POST /api/grid/recommend {state}
응답에서 카드 수 · 대표 사진 url 유무 · 부품 사진(parts[].photo.url) 수를 세어 마크다운으로 출력한다.
비밀값·DB 접속 없음. 실패해도 0으로 끝내지 않는다(초록불이 「안 본 것」이 되지 않게).
"""
import json
import os
import sys
import time
import urllib.request

BASE = os.environ.get('BASE', 'https://popcornai.co.kr').rstrip('/')
TEXT = os.environ.get('TEXT', '배그와 롤, 150만원으로 추천해줘')


def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), method='POST',
                                 headers={'Content-Type': 'application/json'})
    t = time.monotonic()
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r), r.status, time.monotonic() - t


def cards(node):
    """product_code 를 가진 dict(추천 카드)를 모두 찾는다."""
    if isinstance(node, dict):
        if 'product_code' in node and 'price' in node:
            yield node
        for v in node.values():
            yield from cards(v)
    elif isinstance(node, list):
        for v in node:
            yield from cards(v)


def main():
    print('### 개발 서버 고객 추천 점검')
    print(f'- 시각(KST): {time.strftime("%Y-%m-%d %H:%M", time.gmtime(time.time() + 9 * 3600))}')
    print(f'- 문장: {TEXT}')
    parsed, s1, t1 = post('/api/talk/parse', {'text': TEXT})
    state = parsed.get('state')
    print(f'- /api/talk/parse: HTTP {s1}, {t1:.1f}s, state 키 {sorted(state) if isinstance(state, dict) else state!r}')
    if not isinstance(state, dict):
        print('- 실패: parse 응답에 state 가 없음')
        return 1
    rec, s2, t2 = post('/api/grid/recommend', {'state': state})
    found = list(cards(rec))
    print(f'- /api/grid/recommend: HTTP {s2}, {t2:.1f}s, 카드 {len(found)}개')
    print()
    print('| 상품 | 이름 | 가격 | 대표 사진 | 공개 구성 | 부품 사진 url |')
    print('|---|---|---|---|---|---|')
    for c in found:
        photo = c.get('photo') or {}
        conf = c.get('public_configuration')
        parts = (conf or {}).get('parts') or []
        with_url = sum(1 for p in parts if isinstance(p, dict) and (p.get('photo') or {}).get('url'))
        print(f"| {c.get('product_code')} | {str(c.get('name'))[:40]} | {c.get('price')} | "
              f"{photo.get('state')} {'url 있음' if photo.get('url') else 'url 없음'} | "
              f"{'있음' if conf else '없음'} | {with_url}/{len(parts)} |")
    print()
    return 0 if found else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as e:  # 실패도 요약에 남긴다
        print(f'- 실패: {type(e).__name__}: {e}')
        sys.exit(1)
