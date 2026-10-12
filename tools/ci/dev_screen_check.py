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
import urllib.error
import urllib.request
import builtins
_LINES=[]
_print=builtins.print
def print(*a, **k):
    _LINES.append(' '.join(str(x) for x in a))
    _print(*a, **k)

BASE = os.environ.get('BASE', 'https://popcornai.co.kr').rstrip('/')
TEXT = os.environ.get('TEXT', '배그와 롤, 150만원으로 추천해줘')
# 추가 확인(GET 경로:반복 횟수, 쉼표 구분). 승인 구성 응답 시간과 부품 사진 응답을 본다.
PROBES = os.environ.get('PROBES', '/api/customer/pc-offers/97909:2,/api/product-images/111066/detail:1')


def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), method='POST',
                                 headers={'Content-Type': 'application/json'})
    t = time.monotonic()
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r), r.status, time.monotonic() - t


def probe(path):
    """GET 한 번 — (HTTP 코드, 초, 바이트). HTTP 오류도 코드로 돌려준다."""
    t = time.monotonic()
    try:
        with urllib.request.urlopen(BASE + path, timeout=90) as r:
            return r.status, time.monotonic() - t, len(r.read())
    except urllib.error.HTTPError as e:
        return e.code, time.monotonic() - t, len(e.read() or b'')
    except Exception as e:
        return f'{type(e).__name__}', time.monotonic() - t, 0


def probes():
    """PROBES 를 차례로 부른다. 추천 점검 결과(종료 코드)에는 영향을 주지 않는다."""
    items = [x.strip() for x in PROBES.split(',') if x.strip()]
    if not items:
        return
    print('### 추가 확인(GET)')
    print('| 경로 | 회차 | HTTP | 시간 | 바이트 |')
    print('|---|---|---|---|---|')
    for item in items:
        path, _, n = item.rpartition(':')
        if not path or not n.isdigit():
            path, n = item, '1'
        for i in range(1, int(n) + 1):
            code, sec, size = probe(path)
            print(f'| {path} | {i} | {code} | {sec:.2f}s | {size} |')
    print()


def cards(node):
    """product_code 와 숫자 price 를 가진 dict(추천 카드)를 모두 찾는다.
    공개 구성 안의 product_code(가격이 {'state': 'unknown', ...} 객체)는 카드가 아니다."""
    if isinstance(node, dict):
        if 'product_code' in node and isinstance(node.get('price'), (int, float)):
            yield node
        for v in node.values():
            yield from cards(v)
    elif isinstance(node, list):
        for v in node:
            yield from cards(v)


def expand(text):
    """「LONG:<글자 수>:<끝 문장>」 -> 그 길이의 긴 글 + 끝 문장(긴 글 예외 점검용)."""
    if text.startswith('LONG:'):
        _, n, tail = text.split(':', 2)
        body = '저는 게임을 오래 했어요. '
        return (body * (int(n) // len(body) + 1))[:int(n)] + tail
    return text


def talk_cases(texts):
    """여러 문장을 /api/talk/parse 에만 차례로 보내 고객이 보는 말을 표로 남긴다(추천은 안 부른다).

    TEXT 를 « || » 로 나누면 이 모드다(2026-10-11 코덱스 예외 55개 대표 10개 점검).
    HTTP 오류도 그 줄에 적는다 -- 「차단됐다」는 것 자체가 점검 결과다.
    """
    print('### 개발 서버 상담 문장 점검' + (' (이어 보내기는 추천 카드까지)' if texts and texts[0].startswith('CHAIN:') else ' (/api/talk/parse 만)'))
    print(f'- 시각(KST): {time.strftime("%Y-%m-%d %H:%M", time.gmtime(time.time() + 9 * 3600))}')
    print()
    # 첫 문장이 「CHAIN:」으로 시작하면 한 상담처럼 이어 보낸다(chat_flow·history 를 넘긴다).
    # 잡담 몇 번째에 PC 권유가 붙는지 같은 «여러 턴» 규칙을 실제 서버에서 볼 때 쓴다.
    chain = bool(texts) and texts[0].startswith('CHAIN:')
    if chain:
        texts = [texts[0][len('CHAIN:'):].strip()] + list(texts[1:])
        print('- 이어 보내기: state·chat_flow·history 를 넘김 (화면 live-flow.js 와 같은 왕복)')
        print()
    flow, state, history, failed, pending = None, None, [], 0, ''
    for i, raw in enumerate(texts, 1):
        text = expand(raw)
        shown = raw if len(raw) <= 60 else raw[:60] + '...'
        print(f'#### {i}. {shown!r} ({len(text)}자)')
        try:
            body = {'text': text}
            if chain:
                body.update({'state': state, 'chat_flow': flow, 'history': history[-6:]})
            parsed, code, sec = post('/api/talk/parse', body)
        except urllib.error.HTTPError as e:
            body = (e.read() or b'')[:300].decode('utf-8', 'replace')
            print(f'- HTTP {e.code}: {body!r}')
            print()
            failed += 1
            continue
        except Exception as e:
            print(f'- 실패: {type(e).__name__}: {e}')
            print()
            failed += 1
            continue
        print(f'- HTTP {code}, {sec:.1f}s')
        for key in ('pc_related', 'stage', 'chat_flow', 'state', 'missing', 'exceptions', 'handoff_offer', 'truncated', 'answer_error'):
            print(f'- {key}: {parsed.get(key)!r}')
        for key in ('answer', 'reply'):
            print(f'- {key}: {str(parsed.get(key) or "")[:600]!r}')
        if chain:
            # 화면(live-flow.js submit)과 같은 조건으로 추천을 부른다 -- 고객이 그 턴에 카드를 보는지까지 본다.
            pending = (pending + ' / ' + text if pending else text)[-300:]
            if (parsed.get('missing') or parsed.get('pc_related') is False or parsed.get('silent')
                    or parsed.get('fallback') or not isinstance(parsed.get('state'), dict)):
                print('- 추천 카드: 이 턴은 부르지 않음(화면과 같은 조건)')
            else:
                try:
                    rec, s2, t2 = post('/api/grid/recommend', {'state': parsed['state'], 'text': pending})
                    found = list(cards(rec))
                    pending = ''
                    print(f'- 추천 카드: HTTP {s2}, {t2:.1f}s, {len(found)}개'
                          + (f", needs={rec.get('needs')!r}" if rec.get('needs') else ''))
                    for c in found[:6]:
                        print(f"  - {c.get('product_code')} | {str(c.get('name'))[:50]} | {c.get('price')}원 | {c.get('tag') or ''}")
                except Exception as e:
                    print(f'- 추천 카드: 실패 {type(e).__name__}: {e}')
                    failed += 1
        print()
        if chain:
            flow, state = parsed.get('chat_flow'), parsed.get('state')
            history.append({'role': 'user', 'text': text[:1000]})
            for key in ('answer', 'reply'):
                if parsed.get(key):
                    history.append({'role': 'assistant', 'text': str(parsed[key])[:300]})
    # 한 문장이라도 실패하면 점검 실패로 끝낸다(코덱스 #141 검수: 종료 코드가 늘 0 이었다).
    if failed:
        print(f'- 실패한 문장: {failed}개')
    return 1 if failed else 0


def resume_case(text):
    """「RESUME:<문장>」 -- 대화 화면이 받은 카드와, 옛 화면이 복원할 때 다시 묻는 두 방식의 카드를 비교한다
    (2026-10-12 카드 검수: 부품 바꾸기를 누르면 고른 PC 를 못 찾음)."""
    print('### 복원 재현: ' + text)
    parsed, _, _ = post('/api/talk/parse', {'text': text})
    state = parsed.get('state')
    print(f"- missing: {parsed.get('missing')!r}")
    a, _, _ = post('/api/grid/recommend', {'state': state, 'text': text[:300]})
    wants = a.get('wants')
    print(f"- 대화 화면(state+text): {[c.get('product_code') for c in cards(a)]} wants={wants!r}")
    body = {'state': state}
    if isinstance(wants, dict):
        body['wants'] = wants
    b, _, _ = post('/api/grid/recommend', body)
    print(f"- 복원 1(state+wants): {[c.get('product_code') for c in cards(b)]}")
    c_, _, _ = post('/api/grid/recommend', {'state': state})
    print(f"- 복원 2(state 만): {[c.get('product_code') for c in cards(c_)]}")
    print(f"- 응답 키: {sorted(a) if isinstance(a, dict) else a!r}")
    print()
    return 0


def main():
    if TEXT.startswith('RESUME:'):
        return max(resume_case(t.strip()) for t in TEXT[len('RESUME:'):].split('##') if t.strip())
    texts = [t.strip() for t in TEXT.split('||')]
    if len(texts) > 1:
        return talk_cases(texts)
    print('### 개발 서버 고객 추천 점검')
    print(f'- 시각(KST): {time.strftime("%Y-%m-%d %H:%M", time.gmtime(time.time() + 9 * 3600))}')
    print(f'- 문장: {TEXT}')
    parsed, s1, t1 = post('/api/talk/parse', {'text': TEXT})
    state = parsed.get('state')
    print(f'- /api/talk/parse: HTTP {s1}, {t1:.1f}s, state 키 {sorted(state) if isinstance(state, dict) else state!r}')
    # 고객이 실제로 보는 말풍선(답변·되묻기)도 함께 남긴다 -- 예외 질문 점검용(2026-10-11).
    for key in ('pc_related', 'stage', 'narrowing', 'missing', 'answer_game_names', 'exceptions'):
        print(f'- {key}: {parsed.get(key)!r}')
    for key in ('answer', 'reply'):
        print(f'- {key}: {str(parsed.get(key) or "")[:800]!r}')
    if not isinstance(state, dict):
        print('- 실패: parse 응답에 state 가 없음')
        return 1
    rec, s2, t2 = post('/api/grid/recommend', {'state': state})
    found = list(cards(rec))
    print(f'- /api/grid/recommend: HTTP {s2}, {t2:.1f}s, 카드 {len(found)}개')
    for g in (rec.get('card_sets') or []) if isinstance(rec, dict) else []:
        if isinstance(g, dict):
            print(f"- 묶음 {g.get('usage')!r}: empty_reason={g.get('empty_reason')!r} empty_note={g.get('empty_note')!r}"
                  f" over_budget={[i.get('over_budget') for i in (g.get('items') or []) if isinstance(i, dict)]}")
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
    # 부품별 판매가와 「조립·기타」(PC 금액 - 부품 합) -- 2026-10-12 상세 화면 부품 금액 점검.
    for c in found:
        parts = ((c.get('public_configuration') or {}).get('parts')) or []
        real = [p for p in parts if isinstance(p, dict) and not p.get('pseudo')]
        if not real:
            continue
        lines = [f"{p.get('slot')} {str(p.get('name'))[:30]} x{p.get('quantity')} = {p.get('price')}" for p in real]
        missing = [p for p in real if not isinstance(p.get('price'), int)]
        total = sum(p['price'] * p['quantity'] for p in real if p not in missing)
        other = (c.get('price') - total) if not missing and isinstance(c.get('price'), int) else None
        print(f"- 부품 금액 {c.get('product_code')}: PC {c.get('price')} / 부품 합 {total} / 조립·기타 {other} / 값 없음 {len(missing)}")
        for line in lines:
            print(f"  - {line}")
    print()
    return 0 if found else 1


if __name__ == '__main__':
    try:
        rc = main()
    except Exception as e:  # 실패도 요약에 남긴다
        print(f'- 실패: {type(e).__name__}: {e}')
        rc = 1
    probes()
    blob='\n'.join(_LINES)
    for i in range(0, len(blob), 1200):
        part=blob[i:i+1200].replace('%','%25').replace('\r','%0D').replace('\n','%0A')
        _print(f'::notice title=check {i//1200:02d}::{part}')
    sys.exit(rc)
