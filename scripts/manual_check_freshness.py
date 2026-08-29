# -*- coding: utf-8 -*-
"""운영자 매뉴얼 — 「그림이 지금 화면과 같은가」 검사 (2026-08-29 신설).

배경 — `scripts/manual_check_pins.py`는 매뉴얼 문서 **안**의 핀 배지가 그 문서 안 그림
경계·서로와 겹치는지만 본다. 즉 "이미지 «안»에서 핀끼리 안 겹치는가"다. **"그 이미지가
지금 관리자 화면과 같은가"는 아무도 안 본다.** 2026-08-27 커밋 f888e07
(`mockups/shared/admin2/admin2.css`, `--a2-zoom: 1.15` 신설 — 이 파일은 그 커밋을
건드리지 않는다, 대상 밖)이 콘텐츠 영역 전체를 15% 키우고 재배치했는데, 그 전에 찍은
캡처 6개(dashboard·products·reviews·categories·operators·ops-settings)가 낡은 채
`manual_check_pins.py`에서는 계속 "위반 0건"이었다 — 그 검사가 원래 못 보는 것을 안
본 것뿐이라 거짓말은 아니지만, 매뉴얼 신선도를 아무도 자동으로 재지 않고 있었다.

무엇을 잰다
    `mockups/shared/manual/shots/<slug>-coords.json`의 `elements[].px`(캡처 당시
    `getBoundingClientRect()` 실측값 — `scripts/manual_capture_common.py`의 `shoot()`가
    남긴 것, 지어낸 값이 아니다)를, **같은 선택자로 지금 살아있는 화면에서 다시 재서**
    비교한다. 어느 한 축(x·y·width·height)이라도 문턱(PX_THRESHOLD)을 넘으면 그
    요소는 "낡음"이다.

선택자는 어디서 얻는가 — coords.json에는 없다
    coords.json은 {요소이름: %/px 값}만 담는다. **CSS 선택자 문자열은 어디에도
    저장돼 있지 않다** — 그 선택자를 아는 유일한 곳은 그 요소를 찍은
    `scripts/manual_shots_<screen>.py`(또는 reviews의 경우 `manual_shots.py` — 파일명을
    그대로 남긴 이유는 `manual_capture_common.py` 모듈 docstring 참고)의 **소스 코드
    자신**뿐이다. 그래서 이 파일은 그 소스를 **정적으로(AST로, import·실행하지 않고)**
    읽어 `shoot(page, "<이름>", <clip>, {선택자 dict}, coords)` /
    `shoot_scrolled(page, "<이름>", <selector>, {선택자 dict}, coords)` 호출에서
    "이름 -> {요소이름: 선택자}" 대응을 복원한다.

    ⚠ **클릭·입력 등으로 상태를 바꾼 "이후"의 캡처는 다루지 않는다** — 지시서 원문
    "같은 조건으로 연다"를 지키려면, 우리가 다시 열 수 있는 조건은 "그 경로를 열고
    기다린 뒤 아무것도 누르지 않은 초기 상태"뿐이다(행 클릭·드로어 열기·탭 전환·표
    필터링을 거친 뒤의 캡처는 이 스크립트가 그 인터랙션을 실제로 재현하지 않는 한
    같은 조건이 아니다 — 재현하려면 서버에 실제 쓰기가 나갈 수 있는 화면도 있다,
    예: stock-inbound의 "확정"→"되돌리기". 재현하지 않는다). 그래서 각 캡처 스크립트의
    `main()` 소스를 **등장 순서대로** 훑다가 상태를 바꾸는 첫 Playwright 호출
    (`.click()`·`.fill()`·`.check()`·`.hover()` 등 — `INTERACTIVE_METHODS`, 그 호출을
    감싼 도우미 함수도 재귀적으로 포함)을 만나면 그 지점에서 멈춘다. 그 전까지 나온
    `shoot()`/`shoot_scrolled()` 호출만 이 검사의 대상이다 — 대개 "-full"·"-header"와
    바로 다음 1~4개 하위 확대(필터바·통계·탭 등, 전부 재계산만 하고 클릭은 없다)가
    여기 해당한다(2026-08-29 16개 전수 확인 — 화면당 3~7개 캡처, 21~52개 요소).
    선택자 인자가 리터럴 dict가 아니라 변수 참조(행 반복으로 만든 el_sel 등)인
    경우도 **복원하지 않고 건너뛴다** — 지어내는 대신 건너뛴 이유를 `skip_notes`에
    담아 돌려준다(지시서 "그 대응이 코드에 없으면 그 사실 자체를 보고하라").
    ⚠ **기본 실행(옵션 없음)에서도 몇 건 건너뛰었는지는 항상 보인다**(요약 줄에
    "건너뜀 N건" — 아래 `run_freshness_checks()` 참조). 사유 전문(어느 shoot() 호출을
    왜 못 읽었는지, 줄 단위)은 `--verbose`에서만 찍는다 — 매번 무조건 쏟아내면
    102건(2026-08-29 실측)이 늘 화면을 채워 그 자체가 소음이 된다. **개수는 숨기지
    않고, 사유 전문만 옵션 뒤로 미룬다** — 전에는 `--verbose` 없이 돌리면 건너뜀
    개수조차 0으로 보여 "N개는 봤다"가 "그 화면 전부를 봤다"로 오인되기 쉬웠다
    (2026-08-29 확인자 지적 — `grep -c "건너뜀" 옵션없는출력` 이 0인데 `--verbose`를
    주면 102건이 나왔다).

    이 한계 때문에 **인터랙션 이후에만 보이는 화면(드로어·모달·"-table"의 강조행 등)은
    이 검사 범위 밖이다.** 정적 초기 화면(좌측 메뉴·헤더·필터바·통계 카드 등 —
    이번 사고의 실제 증상인 헤더 높이·필터 위치가 전부 여기 있다)의 신선도만 보증한다.

문턱 — 왜 절대 px, 왜 2.0px (지시서 "상대오차와 절대오차 중 무엇이 맞는지 판단하라")
    상대오차는 이 사고에 안 맞는다: `--a2-zoom`은 `.a2-main`(콘텐츠 전체)에 걸리므로
    요소마다 실제로 움직이는 **절대량**이 자기 크기가 아니라 "그 요소가 콘텐츠
    영역 안 어디에 있는가"에 좌우된다 — 실측 사례(사장님 제공)로도 헤더 높이는
    52->59.8px(+15.0%, 즉 52*1.15)인데 필터 x좌표는 882.8->981.7px(+11.2%)·
    1075.7->1204.6px(+12.0%)로 **요소마다 %가 다르다**(원점이 0이 아니라 LNB
    폭 212px만큼 이동된 좌표계라 배율 하나로 안 맞아떨어진다). 그러니 "15%"
    같은 상대 문턱은 요소별로 새로 계산해야 해서 실용적이지 않고, 반대로 작은
    아이콘(예: 10px 배지)은 1~2px만 밀려도 %로는 거대해 보여 오탐이 난다.
    **절대 px가 더 단순하고 직접적이다**: "이 요소가 지금 매뉴얼이 말하는 자리에서
    N px 벗어났다"고 그대로 말할 수 있다.
    2.0px를 고른 근거 — 위·동일 소스 커밋의 실측 두 극단 사이에 크게 여유를 두고
    잡았다: 정상(신선) 화면은 요소 6개 전부 오차 **0.00px**였고(사장님 제공 실측 —
    이 스크립트로 category-mapping·activity-logs를 재실행해도 같게 나와야 한다),
    낡은 화면의 가장 작은 실측 편차조차 헤더 높이 **7.8px**(52->59.8)였다. 2.0px는
    브라우저 서브픽셀 렌더링 잡음(폰트 힌팅 등 — `manual_check_pins.py`의
    `NOISE_PX=0.1`은 **같은 페이지 안** 두 사각형을 재는 값이라 이 값보다 작아도
    되지만, 이 스크립트는 **서로 다른 두 시점의 내비게이션**을 비교하므로 여유를
    더 둔다)보다는 위, 가장 작은 실제 결함(7.8px)보다는 한참 아래다 — 그 사이
    어디를 잡아도 이번 8개 판정은 갈리지 않는다.

살아있는 텍스트 자동 판별 — 왜 예외 목록이 아니라 재실측인가(2026-08-29 확인자 실측
으로 판정이 재실행마다 뒤집힌 것을 발견한 뒤 추가. 아래 "직전 설계가 왜 부족했는가"
참고)
    이 검사는 원래 "지금 화면이 좌표 JSON과 다르다"는 사실만 보고, «왜» 다른지는
    구분하지 않았다. 그런데 실제로는 위반이 CSS 회귀가 «아닌» 채로 뜨는 경우가
    있다 — 화면이 그 순간의 데이터를 글자로 렌더하고, 그 데이터가 캡처 이후 실제로
    바뀐 경우다. activity-logs의 `#alScopeLine`("원장 조건 내 N건")이 실례다: N은
    이 화면이 속한 로그 테이블의 실시간 총건수라, 다른 운영자(또는 이 저장소처럼
    여러 에이전트가 동시에 쓰는 공유 개발 서버의 다른 작업)가 그 사이 로그를 남기면
    자릿수가 바뀌어 폭이 흔들린다(dw=3.0 실측) — 게다가 같은 행에 이어 배치된
    `#refreshBtn`까지 **덩달아** 밀린다(레이아웃 흐름상 앞 요소가 넓어지면 다음
    요소가 밀려난다 — x좌표가 바뀌지만 `#refreshBtn` 자신은 CSS도 안 바뀌었다).

    **직전 설계가 왜 부족했는가**: 처음엔 "consult-sessions의 `#lastAt`은 살아있는
    텍스트다"라고 이 자리에 이름을 적어 알려진 한계로만 남겼다. 그런데 activity-logs
    사고로 바로 드러났듯 **이런 요소는 계속 새로 생긴다** — 이름을 하나씩 적는
    예외 목록은 다음 요소를 놓친다(오늘 이 저장소에서 "같은 라벨의 버튼이 셋인데
    하나만 잡아" 게이트가 샌 전례와 같은 모양의 함정). 그리고 앞 문단의 `#refreshBtn`
    처럼 "흔들리는 요소 자신"이 아니라 "그 옆에서 흔들림을 옮아 받는 요소"까지
    있어서, "이 요소는 살아있는 텍스트다/아니다"를 이름으로 미리 정해 두는 방식으론
    애초에 다 못 잡는다.

    **그래서 이름이 아니라 재실측으로 판별한다** — 문턱을 넘은 요소만(위반이
    0건인 화면은 이 비용을 전혀 안 낸다) 다시 두 가지 방법으로 잰다:
        ① 같은 페이지에서 `LIVE_RECHECK_WAIT_MS` 만큼 기다렸다 다시 잰다 — JS
           타이머로 스스로 값이 바뀌는 요소(초 단위로 다시 그리는 시계 등)를 잡는다.
        ② 페이지를 다시 열어(`LIVE_RECHECK_RELOADS`회) 다시 잰다 — ①로는 못
           잡는, "로드되는 그 순간에만 서버에서 값을 새로 받아오는" 요소
           (`#alScopeLine`처럼 fetch 결과를 렌더하고 그 뒤로는 안 바뀌는 값)를
           잡는다. 리로드를 여러 번 하는 이유는 순전히 "그 사이 다른 쓰기가
           끼어들 시간"을 늘리기 위해서다 — 값이 원래 안 바뀌면 몇 번을 다시 열어도
           똑같다.
    둘 중 어느 쪽이든, 최초 실측과 `LIVE_STABILITY_NOISE_PX`보다 크게 달라지면
    그 요소는 "살아있는 텍스트"로 보고 `live_excluded`로 옮긴다(위반 집계·FAIL
    판정에서 뺀다 — 다만 로그에서 안 지운다, 아래 참조). 원인이 그 요소 자신이든
    옆 요소의 흔들림을 옮아 받은 것이든 **이 재실측은 값 자체를 다시 재서 비교하므로
    구분 없이 잡는다** — 이름을 아는지 모르는지에 기대지 않는다.

    **뭐가 남는가 — 재실측에도 값이 그대로면 진짜 회귀다**: products의 `#fmfr`
    (dx=98.9px)·reviews의 `#pillStatus`(dx=128.8px, 둘 다 2026-08-27 zoom 회귀 —
    파일 상단 배경 참고)는 재실측해도 **같은 값**이 나온다 — CSS가 실제로 바뀐
    것이라 언제 다시 열어도 그 자리다. 이런 요소는 `live_excluded`로 안 빠지고
    그대로 `drift`(FAIL)에 남는다.

    **⚠ 데이터가 바뀐 게 전부 살아있는 텍스트는 아니다 — suppliers는 다른 부류다.**
    suppliers의 `#spTbody .sp-row.inactive`는 "ID로 고정된 행"이 아니라 "지금
    DOM에서 처음 만나는 비활성 행"을 가리키는 선택자다. 2026-08-29 확인자가 3회
    재실행 전부에서 dy=6349.0(완전히 같은 값)을 봤다 — 즉 공급처 데이터가 캡처
    시점(2026-08-28) 이후 한 번 바뀐 채로 **안정적으로 고정**돼 있다는 뜻이다
    (같은 셀렉터가 이제 다른 회사를 가리킬 수도 있다 — dw=dh=0이라 "같은 모양"
    이지만 "같은 행"이라는 보장은 이 검사 범위 밖이다). 이런 요소는 재실측에서도
    값이 흔들리지 않으므로(값 자체가 안 흔들리는 게 아니라, 이미 바뀐 뒤로 그
    상태에서 안 흔들리는 것이다) `live_excluded`로 안 빠지고 `drift`(FAIL)에
    그대로 남는다 — **의도한 동작이다**: "매 실행마다 다른 값"과 "매뉴얼 캡처
    이후 한 번 바뀐 뒤 고정된 값"은 다른 문제(전자는 검사 대상이 될 수 없는
    데이터, 후자는 선택자를 ID 기준으로 다시 짜야 하는 실제 결함)라서, FAIL로
    남겨 사람이 선택자를 ID 기준으로 바꿀지 판단하게 둔다. 즉 "위반이 뜨면
    CSS 회귀가 아닐 수 있다"는 사실 자체가 사라진 게 아니라, **그중 재실측으로
    가려낼 수 있는 절반(살아있는 텍스트)만 자동으로 제외되고, 나머지 절반(안정적
    으로 재현되는 선택자/데이터 결함)은 여전히 사람의 판단을 요구하며 FAIL로
    남는다.**

    **잔여 위험(지어내지 않고 그대로 적는다)**: 재실측이 실제로 다른 값을 잡으려면
    ①·②의 짧은 시간창(대략 수 초) 안에 실제로 그 값이 바뀌어야 한다. 아무도 그
    사이에 로그를 안 남기면(조용한 서버) `#alScopeLine`류 요소도 "재실측해도
    똑같다"로 나와 `drift`(FAIL)에 남을 수 있다 — **이건 안전한 쪽으로 치우친
    실패다**: 놓치는 방향(진짜 회귀를 살아있는 텍스트로 오판해 숨김)이 아니라
    과잉 검출 방향(살아있는 텍스트를 못 걸러 FAIL로 남김)이라 "진짜 회귀를
    놓치면 안 된다"는 원칙을 어기지 않는다. 사람이 `--verbose`의 기록/실측
    좌표를 보고 여전히 최종 판단할 수 있다(아래 요약 줄이 `drift`/`live_excluded`
    개수를 나눠 보여주므로 뭐가 왜 남았는지 구분된다).

사용법(서버를 먼저 띄우고 --base로 그 포트를 가리킨다. GET만 나간다 — 사장님
서버 8000에 그대로 돌려도 안전하다):

    .venv/Scripts/python scripts/manual_check_freshness.py
    .venv/Scripts/python scripts/manual_check_freshness.py --base=http://127.0.0.1:8031
    .venv/Scripts/python scripts/manual_check_freshness.py --slugs=dashboard,products
    .venv/Scripts/python scripts/manual_check_freshness.py --threshold=2.0
    .venv/Scripts/python scripts/manual_check_freshness.py --verbose   # 요소별 세부 출력

종료 코드 0 = 위반 0건(비교 대상이 0건인 화면이 하나라도 있으면 "확인 못 함"으로
별도 보고하되, 그 자체로 실패 취급하지는 않는다 — 아래 `check_slug()` 참조).

`scripts/manual_check_pins.py`가 이 모듈의 `run_freshness_checks()`를 불러 같은
`capture_session()`(같은 브라우저) 안에서 함께 돌린다 — 이 파일 단독으로도 실행된다.
"""
import ast
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from manual_capture_common import BASE, capture_session, log  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
FRAGMENTS_DIR = ROOT / "docs" / "manual" / "screens"
SHOTS_DIR = ROOT / "mockups" / "shared" / "manual" / "shots"
SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent

# 캡처가 항상 이 뷰포트로 이뤄졌다(scripts/manual_capture_common.py VIEWPORT — 16개
# 스크립트 전부 이 상수를 그대로 쓴다, 화면마다 다시 정의하지 않는다). coords.json에
# `_meta.viewport`가 있으면 그 값을 우선한다 — 이 상수는 그게 없을 때만 쓰는 폴백.
FALLBACK_VIEWPORT = {"width": 1680, "height": 1050}

PX_THRESHOLD = 2.0  # 근거는 파일 docstring 참조

# ── 살아있는 텍스트 재검증 상수 (2026-08-29 확인자 실측 후 신설) ──────────────────
# 근거·설계는 파일 docstring "살아있는 텍스트 자동 판별" 참고. 문턱을 넘은 요소만
# 이 비용을 낸다 — 위반이 0건인 화면(대다수)은 아래 세 상수와 무관하게 기존 속도
# 그대로다.
LIVE_RECHECK_WAIT_MS = 1200   # ①(같은 페이지 재측정) 전 대기 — 초 단위로 다시
# 그리는 시계라면 이 안에 값이 바뀐다.
LIVE_RECHECK_RELOADS = 2      # ②(리로드 재측정) 반복 횟수 — 매번 새로 여는 이유는
# "그 사이 다른 운영자/에이전트의 쓰기가 끼어들 시간"을 늘리기 위해서다(이 저장소는
# 여러 제작자가 동시에 쓰는 공유 개발 서버 — CANON.md "같은 시각에 다른 제작자가
# 다른 파일을 짓고 있다"). 값 자체가 원래 안 바뀌는 요소라면 몇 번을 다시 열어도
# 최초 실측과 같은 값만 나온다 — 오탐(진짜 회귀를 살아있는 텍스트로 오판)을 늘리지
# 않는다.
LIVE_STABILITY_NOISE_PX = 0.5  # 재실측 두 값이 "같다"고 볼 허용치. PX_THRESHOLD
# (2.0)보다 훨씬 촘촘하다 — 여기서 묻는 건 "매뉴얼 기록과 같은가"가 아니라 "방금
# 잰 값과 방금 또 잰 값이 같은가"이므로, manual_check_pins.py의 NOISE_PX(0.1, 같은
# 페이지 안 두 사각형 비교)와 같은 종류의 서브픽셀 잡음 말고는 흔들릴 이유가 없다.

# main() 안에서 이 메서드 호출을 만나면 "초기 상태"가 끝난 것으로 본다(그 이후 shoot()는
# 대상에서 제외). hover도 포함한다 — 서버에 아무것도 안 보내지만 CSS :hover로 레이아웃이
# 바뀔 수 있는 화면이 있어 안전 쪽으로 잡았다.
INTERACTIVE_METHODS = {
    "click", "dblclick", "fill", "type", "press", "check", "uncheck",
    "select_option", "set_input_files", "drag_to", "tap", "hover",
}

JS_MEASURE = r"""
(selectors) => {
  const out = {};
  for (const name in selectors) {
    const el = document.querySelector(selectors[name]);
    if (!el) { out[name] = null; continue; }
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || el.hidden) { out[name] = null; continue; }
    const r = el.getBoundingClientRect();
    out[name] = {x: r.x, y: r.y, width: r.width, height: r.height};
  }
  return out;
}
"""


def _console_safe(s: str) -> str:
    """콘솔이 인코딩 못 하는 문자를 이스케이프로 바꾼다 — `manual_check_pins.py`와
    같은 방어(그 파일이 겪은 cp949 크래시와 같은 함정 — 여기서도 fig/selector 원문이
    다른 제작자 소유 소스에서 온 동적 문자열이라 똑같이 걸릴 수 있다)."""
    enc = sys.stdout.encoding or "utf-8"
    try:
        s.encode(enc)
        return s
    except UnicodeEncodeError:
        return s.encode(enc, errors="backslashreplace").decode(enc)


def discover_slugs() -> list[str]:
    return sorted(p.stem for p in FRAGMENTS_DIR.glob("*.html"))


def _slug_to_script(slug: str) -> pathlib.Path | None:
    """캡처 스크립트 경로. 특례: reviews -> manual_shots.py — 파일명을 안 바꾼 이유는
    `scripts/manual_capture_common.py` 모듈 docstring "왜 파일명을 그대로 남겼는가" 참고
    (그 파일이 이번 작업 담당이 아니라 다시 옮겨 적지 않고 참조만 한다)."""
    p = SCRIPTS_DIR / ("manual_shots.py" if slug == "reviews"
                        else f"manual_shots_{slug.replace('-', '_')}.py")
    return p if p.exists() else None


def _interactive_func_names(tree: ast.Module) -> set[str]:
    """모듈 안 함수 중 자기 몸통에(직접 또는 다른 interactive 함수를 통해 간접적으로)
    상태를 바꾸는 호출이 있는 함수 이름 집합 — 클릭을 감싼 도우미 함수(예:
    `manual_shots_activity_logs.py`의 클릭 도우미)를 통째로 놓치지 않으려는 것이다."""
    funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    interactive: set[str] = set()
    changed = True
    while changed:
        changed = False
        for name, node in funcs.items():
            if name in interactive:
                continue
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Call):
                    continue
                f = sub.func
                if isinstance(f, ast.Attribute) and f.attr in INTERACTIVE_METHODS:
                    interactive.add(name)
                    changed = True
                    break
                if isinstance(f, ast.Name) and f.id in interactive:
                    interactive.add(name)
                    changed = True
                    break
    return interactive


def _literal_selector_dict(node: ast.AST):
    """ast.Dict 리터럴이면 {str: str}로, 아니면(변수 참조 등) None을 돌려준다.
    지어내지 않는다 — 정적으로 확실히 읽히는 것만 쓴다."""
    if not isinstance(node, ast.Dict):
        return None
    try:
        value = ast.literal_eval(node)
    except Exception:
        return None
    if not isinstance(value, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in value.items()
    ):
        return None
    return value


def extract_pre_interaction_shots(script_path: pathlib.Path):
    """캡처 스크립트 소스를 정적으로 읽어 {shot이름: {요소이름: css선택자}}를 복원한다.

    반환: (복원된 대응 dict, 건너뛴 이유 문자열 목록). `main()`이 없거나 파싱이
    실패하면 빈 dict + 그 사실을 담은 note 하나를 돌려준다(지어내지 않는다).
    """
    notes: list[str] = []
    try:
        src = script_path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(script_path))
    except Exception as e:
        return {}, [f"소스 파싱 실패({script_path.name}): {e}"]

    main_node = None
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == "main":
            main_node = n
            break
    if main_node is None:
        return {}, [f"{script_path.name}: main() 함수를 못 찾았습니다"]

    interactive_funcs = _interactive_func_names(tree)
    calls = sorted(
        (n for n in ast.walk(main_node) if isinstance(n, ast.Call)),
        key=lambda n: n.lineno,
    )

    shots: dict[str, dict[str, str]] = {}
    for c in calls:
        f = c.func
        is_interactive = (
            (isinstance(f, ast.Attribute) and f.attr in INTERACTIVE_METHODS)
            or (isinstance(f, ast.Name) and f.id in interactive_funcs)
        )
        if is_interactive:
            break  # 이후는 인터랙션을 거친 상태 — "같은 조건"이 아니다
        is_shoot = isinstance(f, ast.Name) and f.id in ("shoot", "shoot_scrolled")
        if not is_shoot or len(c.args) < 4:
            continue
        name_arg, sel_arg = c.args[1], c.args[3]
        if not (isinstance(name_arg, ast.Constant) and isinstance(name_arg.value, str)):
            notes.append(f"{script_path.name}:L{c.lineno}: shoot() 이름 인자가 문자열 리터럴이 아님 - 건너뜀")
            continue
        selectors = _literal_selector_dict(sel_arg)
        if selectors is None:
            notes.append(
                f"{script_path.name}:L{c.lineno}: '{name_arg.value}' 선택자 인자가 "
                "리터럴 dict가 아님(변수 참조) - 코드에 정적 대응이 없어 복원 못 함"
            )
            continue
        shots[name_arg.value] = selectors
    return shots, notes


def _measure_many(page, candidates: list[dict]) -> dict:
    """candidates(각 원소가 최소 'shot'·'el'·'sel' 키를 가짐)의 요소들을 한 번에 잰다.

    같은 요소 이름이 shot마다 겹칠 수 있어("title" 같은 흔한 이름을 여러 하위 캡처가
    각자 쓸 수 있다) `"{shot}::{el}"` 합성키로 묶는다. 측정 로직(JS_MEASURE)은 두
    번 적지 않고 재사용한다.
    """
    sel_map = {f"{c['shot']}::{c['el']}": c["sel"] for c in candidates}
    return page.evaluate(JS_MEASURE, sel_map)


def _verify_candidates(page, base: str, path: str, candidates: list[dict]) -> tuple[list, list]:
    """1차 실측에서 문턱을 넘은 요소만 다시 재서 "값 자체가 흔들리는가"를 가른다.

    근거·설계 전문은 파일 docstring "살아있는 텍스트 자동 판별" 참고 — 요약하면:
    같은 요소를 ① 같은 페이지에서 대기 후, ② 페이지를 다시 열어(N회) 다시 측정해서
    최초 실측과 `LIVE_STABILITY_NOISE_PX`보다 크게 달라지면 "살아있는 텍스트"로
    보고 `live_excluded`로, 그렇지 않으면(재실측해도 값이 그대로) 진짜 회귀 후보로
    보고 `drift`로 나눈다. 이름으로 미리 정해두는 예외 목록이 아니라 **실측으로
    가른다** — 흔들리는 요소 자신뿐 아니라 그 옆에서 흔들림을 옮아 받는 요소(레이아웃
    흐름상 앞 요소 폭이 바뀌면 밀리는 다음 요소)도 값 자체가 달라지므로 이 방식이면
    함께 잡힌다.

    반환: (drift, live_excluded) — 둘 다 기존 `drift` 항목과 같은 모양의 dict 리스트
    (`shot`·`el`·`selector`·`dx`·`dy`·`dw`·`dh`·`recorded`·`live`).
    """
    page.wait_for_timeout(LIVE_RECHECK_WAIT_MS)
    samples = [_measure_many(page, candidates)]
    for _ in range(LIVE_RECHECK_RELOADS):
        page.goto(f"{base}{path}", wait_until="networkidle")
        page.wait_for_timeout(600)
        samples.append(_measure_many(page, candidates))

    drift, live_excluded = [], []
    for c in candidates:
        key = f"{c['shot']}::{c['el']}"
        base_box = c["live"]
        unstable = False
        for sample in samples:
            box = sample.get(key)
            if box is None:
                continue  # 이번 재실측엔 안 보임 - missing과 같은 이유로 판정에 안 쓴다
                          # (동적 요소가 우연히 안 보일 수 있어 오탐 위험이 더 크다)
            if max(abs(box["x"] - base_box["x"]), abs(box["y"] - base_box["y"]),
                   abs(box["width"] - base_box["width"]),
                   abs(box["height"] - base_box["height"])) > LIVE_STABILITY_NOISE_PX:
                unstable = True
                break
        entry = {
            "shot": c["shot"], "el": c["el"], "selector": _console_safe(c["sel"]),
            "dx": c["dx"], "dy": c["dy"], "dw": c["dw"], "dh": c["dh"],
            "recorded": c["recorded"], "live": c["live"],
        }
        (live_excluded if unstable else drift).append(entry)
    return drift, live_excluded


def check_slug(page, base: str, slug: str, threshold: float = PX_THRESHOLD) -> dict:
    """슬러그 하나를 검사한다.

    반환 딕셔너리:
        ok        True(위반 0) / False(위반 있음) / None(비교 대상 0건 - "확인 못 함")
        checked   실제로 값을 비교한 요소 수
        drift     [{shot, el, selector, dx, dy, dw, dh, recorded, live}, ...] - 문턱을
                  넘었고 재실측(`_verify_candidates`)에도 값이 그대로였던 것(진짜
                  회귀 후보 - FAIL 판정·집계에 들어간다)
        live_excluded  drift와 같은 모양이지만 재실측에서 값 자체가 흔들려 "살아있는
                  텍스트"로 분류돼 FAIL 집계에서 빠진 것(로그에는 남는다 - 파일
                  docstring "살아있는 텍스트 자동 판별" 참고)
        missing   [{shot, el, selector}, ...] - 선택자가 지금 화면에서 안 잡힘
                  (판정에는 안 섞는다 - 동적 요소가 우연히 안 보일 수 있어 오탐
                  위험이 더 크다. 다만 보고에는 남긴다 - 지어내지 않는다는 원칙은
                  "안 보인다는 사실도 숨기지 않는다"를 포함한다)
        skip_notes  정적 복원에 실패해 아예 못 본 shoot() 목록(사유 포함)
        note      치명적 사유(좌표 파일 없음 등) - 있으면 ok=None
    """
    coords_path = SHOTS_DIR / f"{slug}-coords.json"
    if not coords_path.exists():
        return {"ok": None, "checked": 0, "drift": [], "live_excluded": [], "missing": [],
                "skip_notes": [], "note": f"좌표 파일 없음: {coords_path}"}
    coords = json.loads(coords_path.read_text(encoding="utf-8"))

    script_path = _slug_to_script(slug)
    if script_path is None:
        return {"ok": None, "checked": 0, "drift": [], "live_excluded": [], "missing": [],
                "skip_notes": [], "note": "캡처 스크립트를 못 찾음(scripts/manual_shots_<slug>.py 없음)"}

    shots_selectors, skip_notes = extract_pre_interaction_shots(script_path)

    meta = coords.get("_meta", {})
    path = meta.get("screen", {}).get("path")
    viewport = meta.get("viewport") or FALLBACK_VIEWPORT
    if not path:
        return {"ok": None, "checked": 0, "drift": [], "live_excluded": [], "missing": [],
                "skip_notes": skip_notes, "note": "coords.json에 _meta.screen.path 없음"}

    page.set_viewport_size({"width": viewport["width"], "height": viewport["height"]})
    page.goto(f"{base}{path}", wait_until="networkidle")
    # 각 캡처 스크립트는 화면마다 다른 wait_for_selector(...)를 쓴다(예: dashboard는
    # ".dash-grid, .dash-empty", price-import는 "#piLayout:not([hidden])"). 화면 16개마다
    # 그 선택자를 또 정적으로 복원하는 대신, networkidle 뒤 넉넉한 공용 유예(원본
    # 스크립트들의 250~400ms wait_for_timeout보다 더 여유 있게)로 대신한다 — 부족하면
    # 요소가 아직 안 그려져 "missing"으로만 나타나지 위치를 잘못 재는 쪽으로 틀리지
    # 않는다(안전 쪽 실패).
    page.wait_for_timeout(600)

    candidates, missing, skip = [], [], list(skip_notes)
    checked = 0
    for shot_name, stored in coords.items():
        if shot_name == "_meta":
            continue
        selectors = shots_selectors.get(shot_name)
        if selectors is None:
            skip.append(f"{shot_name}: 정적 선택자 복원 실패(인터랙션 이후이거나 변수 참조 선택자)")
            continue
        elements = stored.get("elements", {})
        wanted = {k: v for k, v in selectors.items() if k in elements and "px" in elements[k]}
        if not wanted:
            continue
        live = page.evaluate(JS_MEASURE, wanted)
        for ename, sel in wanted.items():
            rec_px = elements[ename]["px"]
            live_box = live.get(ename)
            if live_box is None:
                missing.append({"shot": shot_name, "el": ename, "selector": _console_safe(sel)})
                continue
            checked += 1
            dx = abs(live_box["x"] - rec_px["x"])
            dy = abs(live_box["y"] - rec_px["y"])
            dw = abs(live_box["width"] - rec_px["width"])
            dh = abs(live_box["height"] - rec_px["height"])
            if max(dx, dy, dw, dh) > threshold:
                # 아직 확정 아님 - "매뉴얼과 다르다"만 확인된 상태다. 이 요소가
                # 진짜 회귀인지 살아있는 텍스트인지는 재실측(_verify_candidates)이
                # 가른다. 원본 선택자(sel, console-safe 적용 전)를 들고 있어야
                # 재실측에서 같은 요소를 다시 querySelector 할 수 있다.
                candidates.append({
                    "shot": shot_name, "el": ename, "sel": sel,
                    "dx": round(dx, 1), "dy": round(dy, 1),
                    "dw": round(dw, 1), "dh": round(dh, 1),
                    "recorded": rec_px, "live": live_box,
                })

    if candidates:
        drift, live_excluded = _verify_candidates(page, base, path, candidates)
    else:
        drift, live_excluded = [], []

    ok = None if checked == 0 else (len(drift) == 0)
    return {"ok": ok, "checked": checked, "drift": drift, "live_excluded": live_excluded,
            "missing": missing, "skip_notes": skip, "note": None}


def run_freshness_checks(page, base: str, slugs: list[str], threshold: float = PX_THRESHOLD,
                          verbose: bool = False) -> tuple[int, int, int, int, int]:
    """`manual_check_pins.py`가 자기 `capture_session()` 안에서 부르는 진입점.

    반환: (검사한 화면 수, 위반 화면 수, 위반 요소 총합, 건너뜀 총합, 동적 제외 총합).
    화면별 로그는 이 함수가 `log()`로 직접 찍는다(호출부가 다시 찍지 않아도 되게).

    ⚠ **건너뜀·동적 제외 «개수»는 --verbose 없이도 항상 찍는다** — 사유 전문·요소별
    상세만 verbose 뒤로 미룬다(파일 docstring "살아있는 텍스트 자동 판별"·상단 사용법
    "건너뜀" 문단 참고). 기본 실행에서 0으로 보이면 안 된다 — 실제로 안 봤다는 뜻이
    아니라 "몇 개를 봤는지 자체를 안 보여줬다"는 뜻이었던 것이 2026-08-29 확인자가
    잡은 결함이다.
    """
    screens_checked = 0
    screens_bad = 0
    elements_bad = 0
    skip_total = 0
    live_total = 0
    for slug in slugs:
        result = check_slug(page, base, slug, threshold)
        if result["note"]:
            log(f"[SKIP] {slug} (신선도) - {result['note']}")
            continue
        screens_checked += 1
        n_drift = len(result["drift"])
        n_missing = len(result["missing"])
        n_skip = len(result["skip_notes"])
        n_live = len(result.get("live_excluded", []))
        skip_total += n_skip
        live_total += n_live
        if result["ok"] is None:
            log(f"[WARN] {slug} (신선도) - 비교 가능한 요소가 0건이라 판정 못 함"
                f"(정적 선택자 복원 {n_skip}건 실패)")
            continue
        extras = []
        if n_missing:
            extras.append(f"화면에 안 보이는 요소 {n_missing}건")
        if n_skip:
            extras.append(f"건너뜀 {n_skip}건")
        if n_live:
            extras.append(f"동적 요소 제외 {n_live}건(재실측 시 값이 흔들려 판정에서 뺌)")
        extra_s = f", {', '.join(extras)}" if extras else ""
        if result["ok"]:
            log(f"[OK] {slug} (신선도)  비교 {result['checked']}개  편차>{threshold}px 0건{extra_s}")
        else:
            elements_bad += n_drift
            screens_bad += 1
            log(f"[FAIL] {slug} (신선도)  비교 {result['checked']}개 중 {n_drift}개가 "
                f"매뉴얼 기록과 {threshold}px 넘게 다릅니다(그림이 지금 화면과 다를 수 있음 - 재촬영 검토){extra_s}")
            for v in result["drift"]:
                log(f"    {v['shot']} {v['el']} <{v['selector']}> dx={v['dx']} dy={v['dy']} "
                    f"dw={v['dw']} dh={v['dh']}  기록={v['recorded']}  실측={v['live']}")
        if verbose and n_missing:
            for m in result["missing"]:
                log(f"    [안보임] {m['shot']} {m['el']} <{m['selector']}>")
        if verbose and result["skip_notes"]:
            for note in result["skip_notes"]:
                log(f"    [건너뜀] {note}")
        if verbose and n_live:
            for v in result["live_excluded"]:
                log(f"    [LIVE] {v['shot']} {v['el']} <{v['selector']}> dx={v['dx']} dy={v['dy']} "
                    f"dw={v['dw']} dh={v['dh']}  기록={v['recorded']}  실측={v['live']}  "
                    "- 재실측에서 값이 흔들려 위반 집계에서 제외")
    return screens_checked, screens_bad, elements_bad, skip_total, live_total


def main() -> int:
    base = BASE
    slugs = None
    threshold = PX_THRESHOLD
    verbose = False
    for arg in sys.argv[1:]:
        if arg.startswith("--base="):
            base = arg.split("=", 1)[1]
        elif arg.startswith("--slugs="):
            slugs = [s.strip() for s in arg.split("=", 1)[1].split(",") if s.strip()]
        elif arg.startswith("--threshold="):
            threshold = float(arg.split("=", 1)[1])
        elif arg == "--verbose":
            verbose = True
    slugs = slugs or discover_slugs()

    with capture_session() as page:
        screens_checked, screens_bad, elements_bad, skip_total, live_total = run_freshness_checks(
            page, base, slugs, threshold, verbose)

    log("")
    extras = []
    if skip_total:
        extras.append(f"건너뜀 {skip_total}건")
    if live_total:
        extras.append(f"동적 요소 제외 {live_total}건")
    extra_s = f" · {' · '.join(extras)}" if extras else ""
    log(f"신선도(그림 vs 실화면) - 화면 {screens_checked}개 검사 · 위반 화면 {screens_bad}개 "
        f"· 위반 요소 {elements_bad}개 (0이면 통과){extra_s}")
    return 1 if screens_bad else 0


if __name__ == "__main__":
    sys.exit(main())
