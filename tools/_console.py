# -*- coding: utf-8 -*-
"""tools/ 스크립트 공용 — Windows 콘솔(cp949) 안전 출력 (2026-08-16).

■ 왜 있나
  이 폴더의 CLI 도구는 사람이 읽는 한글 보고를 표준출력에 낸다. Windows 콘솔의 기본
  stdout 인코딩은 로케일에 따라 cp949이고, 그 코드페이지에 없는 문자(— · – · « » ·
  ⚠ · ⓪ · • · ✓ · ✗ 등)를 print()하면 UnicodeEncodeError로 죽는다. **`--dry`(드라이런)
  조차 마지막 줄 "--dry 모드 — DB를 바꾸지 않았습니다."에서 죽는 사고가 있었다** —
  드라이런은 카탈로그·사양 변경 전에 CLAUDE.md가 강제하는 안전장치인데, 그 도구 자체가
  안 돌면 규정을 지킬 방법이 없어진다(2026-08-16 실사고).

  PYTHONIOENCODING·PYTHONUTF8 환경변수에 기대지 않고, 프로세스 안에서 표준출력·표준에러를
  UTF-8로 재포장해 방어한다 — 콘솔이 그 바이트를 못 그리면(코드페이지가 여전히 cp949면)
  글자가 깨져 «보일» 수는 있어도 **프로세스가 죽지는 않는다.** 실측: 이 재포장이 있는
  파일은 cp949 콘솔에서 em-dash가 섞인 문장을 그대로 출력하고 종료코드 0으로 끝난다
  (`catalog_dryrun.py`·`approve_suggestions.py --dry` 등 2026-08-16 재확인).

■ 이건 `CLAUDE.md` §데이터의 "로그 문자열은 ASCII 기호만"과 범위가 다르다
  그 규칙(슬라이스 40)은 **상시 구동 중인 API 서버**가 요청 처리 중 내는 로그 얘기다 —
  em-dash 하나가 실제 HTTP 요청을 500으로 만들었다. 여기 tools/는 운영자가 터미널에서
  직접 실행해 눈으로 읽는 1회성 CLI 보고문이라 문맥이 다르다. 그래서 문자를 깎지 않고
  스트림 인코딩을 맞추는 쪽을 택했다 — 이 저장소의 보고문은 어디서나 em-dash로 부연을
  단다(이 파일도 그렇다). 그 표기를 CLI 보고에서만 깎으면 같은 정보를 두 문체로 적게 된다.
  ASCII만 쓰는 서버 로그와 이 헬퍼는 **같은 병(cp949)의 다른 처방**이지, 서로 대체하지 않는다.

■ 단일 원천으로 모은 이유
  이 두 줄짜리 재포장은 원래 `tools/*.py` 10개 파일(`approve_suggestions`·`backfill_tags`·
  `catalog_dryrun`·`catalog_import`·`danawa_fetch`·`prune_reviews`·`reclassify`·`respec`·
  `set_admin_password`·`spec_fill_apply`)에 토씨 하나 안 틀리고 복제돼 있었다(2026-07-27
  최초 커밋부터 — git blame 확인). 그런데 **나머지 5개(`std_import_public`·`std_parse`·
  `std_validate`·`std_vendor_fix`·`ui_check_account`)는 이 재포장이 아예 없어** 그 파일들의
  거의 모든 실행이 첫 출력 근처에서 죽고 있었다(2026-08-16 실행해 확인 — 아래 참조).
  15곳에 또 복붙하는 대신 여기 하나로 모은다 — CANON.md 1항 "같은 것을 두 벌 두지 않는다".

■ 실측 (2026-08-16, cp949 콘솔)
  이 재포장이 없던 상태에서 그대로 실행하면:
    std_validate.py        UnicodeEncodeError: line 225 (main() 진입 직후, 사실상 무조건)
    std_import_public.py   UnicodeEncodeError: line  99 (run() 진입 직후, 사실상 무조건)
    std_parse.py            UnicodeEncodeError: line 284 (run() 진입 직후, 사실상 무조건)
    std_vendor_fix.py       UnicodeEncodeError: line  79 (run() 진입 직후, 사실상 무조건)
  이 재포장이 이미 있던 10개 파일은 같은 cp949 콘솔에서 em-dash를 포함해도 종료코드 0 —
  즉 이 재포장 자체는 유효한 처방이었고, 문제는 5개 파일에 **누락**된 것이었다.

■ 쓰는 법 (다른 로컬 import보다 먼저 — `sys.path.insert` 바로 뒤)

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from tools._console import ensure_utf8_console      # noqa: E402
    ensure_utf8_console()

    from dotenv import load_dotenv                      # noqa: E402
    ...

  이 파일 자체는 `tools/` 안에 있어 프로젝트 루트가 이미 `sys.path`에 들어간 뒤에만
  `tools.*`로 임포트된다 — 그래서 반드시 `sys.path.insert(...)` **다음**에 와야 한다.
  `tools/`에는 `__init__.py`가 없지만 파이썬 3의 네임스페이스 패키지로 임포트된다(실측 확인).
"""
import io
import sys


def ensure_utf8_console() -> None:
    """stdout·stderr를 UTF-8 TextIOWrapper로 재포장한다(인코딩 실패는 대체문자로 넘긴다).

    `buffer` 속성이 없는 스트림(이미 캡처·치환된 stdout 등)은 건드리지 않는다 — 원래
    10개 파일이 stdout에 쓰던 것과 같은 가드다. **stderr까지 감싸는 것은 이번에 새로
    더했다** — 잡히지 않은 예외의 한글 메시지가 traceback 출력에서 같은 방식으로 죽는
    것을 막는다(예: 캐치되지 않고 새어나간 `RuntimeError(f"... {e.code} — ...")`).
    stderr는 예외 직전에 죽는 상황에서도 보이도록 줄단위로 즉시 내보낸다.
    """
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace",
                                       line_buffering=True)
