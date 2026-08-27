# -*- coding: utf-8 -*-
"""관리자 응답 문구용 — 상품명·사양 원문에 섞인 HTML 태그를 표시에서만 벗긴다 (2026-08-27).

■ 배경
  products.product_name · spec_source_text 는 몰(원천)에서 그대로 받은 값이다. 몰이
  <font color=red>…</font> · <P> 같은 마크업으로 색·줄바꿈을 표현하는데, 우리 관리자
  화면은 그 값을 그대로 보여줘서(A-38 ⑤ — 운영자는 원천을 본다) 태그가 글자 그대로
  찍힌다(2026-08-26 사장님 발견, /admin2/category-mapping?scope=violation).

  대부분의 관리자 화면은 브라우저(JS)에서 렌더링하므로 그 쪽은
  `mockups/shared/admin2/admin2-text.js`(Admin2Text.stripHtml)가 맡는다. 이 모듈은
  **서버가 문자열을 직접 조립해 JSON에 담아 보내는** 자리를 위한 파이썬 짝이다 — 예:
  `api/admin_imports.py`가 만드는 "적재됨 — <상품명 40자>" 안내 문구. 그 문구는 클라이언트가
  다시 손볼 수 없는 완성된 텍스트라 서버에서 먼저 벗겨야 한다(안 그러면 40자 절단이
  태그 중간을 자를 수도 있다 — 예: "…NO.05.90614M <font colo").

■ 이 모듈이 하는 일 — «표시»에서만 태그를 지운다
  `api/product_name.py`의 `display_name()`과는 다른 축이다 — 그건 "판매조건 꼬리"를
  자르는 **고객 응답 전용** 파생이다. 이 모듈은 "HTML 마크업만" 벗기고, 관리자 화면이
  원천을 그대로 보는 규약은 건드리지 않는다 — 태그는 내용이 아니라 표시 방식이기
  때문이다. **DB는 고치지 않는다** — `products.product_name` 자체를 갱신하는 경로에는
  쓰지 않는다.

■ 실측 (2026-08-26~27, products 전체 — 자매 파일 admin2-text.js와 같은 규칙·같은 실측)
  태그 이름은 font·p/P·br·strong/em/b(오탈자 storng 포함) 뿐이고, "<30cm" 류 부등호
  (부품 스펙) 사용은 두 필드 전체에서 0건이었다 — 그래서 "<" 바로 뒤가 글자가 아니면
  (숫자·한글 등) 태그로 보지 않는다. 전량 시뮬레이션으로 빈 문자열이 되는 행 0건을
  확인했다.
"""
import re

_BLOCK_TAGS = re.compile(r"^(p|br|div|tr|td|th|li|h[1-6])$", re.I)
_TAG_RE = re.compile(r"<\/?\s*([a-zA-Z][a-zA-Z0-9]*)\b[^<>]*>")
# 닫는 ">" 없이 원문이 절단된 조각(실측: product_code 109378 — "...</font"로 끝남).
_TRAILING_TAG_RE = re.compile(r"<\/?\s*(?:font|p|br|strong|storng|em|b)\b[^<>]*$", re.I)


def strip_html_display(raw):
    """읽기 전용 표시 문구용 — 태그를 벗긴 일반 텍스트를 돌려준다.

    products.product_name 등 DB 컬럼을 갱신하는 값에는 쓰지 않는다(표시 전용).
    """
    if raw is None:
        return ""
    s = str(raw)
    if "<" not in s and "&" not in s:
        return s

    def _repl(m):
        return " " if _BLOCK_TAGS.match(m.group(1)) else ""

    s = _TAG_RE.sub(_repl, s)
    s = _TRAILING_TAG_RE.sub(" ", s)
    s = re.sub(r"&#65279;", "", s, flags=re.I)
    s = re.sub(r"&#160;|&nbsp;", " ", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip()
    return s or str(raw)
