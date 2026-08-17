# -*- coding: utf-8 -*-
"""환율 수집 — 하루 한 번 USD->KRW 를 가져와 `fx_rates` 에 쌓는다 (2026-08-17 신설).

실행:
  .venv/Scripts/python tools/fx_fetch.py --dry          # 가져와 보기만 한다(DB 안 건드림)
  .venv/Scripts/python tools/fx_fetch.py                # 가져와서 넣는다(중복이면 건너뜀)
  .venv/Scripts/python tools/fx_fetch.py --stale-days 5 # 기준일이 N일보다 낡으면 경고

■ ⚠ 「외부 의존 0건」 원칙과 부딪히지 않는다 — 다음 사람이 여기서 멈추지 않게 적어 둔다
  그 원칙은 **화면이 로드될 때 바깥을 부르지 않는다**는 뜻이다(폰트·아이콘 CDN 금지 —
  남의 서버가 죽으면 우리 화면이 죽고, 방문자 정보가 남의 로그에 남는다).
  **서버가 배치로 바깥 자료를 가져오는 것은 이미 하고 있다**(`tools/danawa_fetch.py`).
  이 도구도 그쪽이다: 사람이(또는 타이머가) 돌리고, 결과는 우리 DB 에 남으며,
  **화면은 우리 DB 만 읽는다.** 화면이 환율 API 를 직접 부르면 그때 원칙 위반이다.

■ 접근 규범 — `tools/danawa_fetch.py` 와 같은 결 (CLAUDE.md §데이터)
  robots 허용 경로만 · 요청 간격 · 연속 실패면 중단 · 원문은 `.cache/`(gitignore).
  robots 실측(2026-08-17):
      frankfurter.app          User-agent: *  Allow: /          -> 전면 허용
      exchangerate-api.com     User-agent: *  Disallow:         -> 전면 허용(빈 Disallow)

■ 출처 — 1차 frankfurter.dev(ECB 공시), 2차 open.er-api.com
  1차를 고른 이유:
    · **ECB 공시 환율**이라 공공기관 수치다 — 「이 수가 어디서 왔나」에 가장 분명히 답한다.
    · 응답이 **기준일(`date`)을 스스로 말한다.** 우리가 「오늘」로 지어내지 않아도 된다.
    · API 키가 없다(비밀값 관리 대상이 늘지 않는다).
    · **과거 기준일 조회가 된다**(실측 `/v1/2026-08-10` -> 1416.62) — 빠진 날을 메울 수 있다.
    · 약점: ECB 는 평일 오후에만 공시한다. 주말·휴일에는 **직전 영업일자가 그대로 온다** —
      그래서 `rate_date` 를 반드시 함께 저장한다(아래 「실패해도 조용하지 않다」).
  2차(폴백)로 둔 이유:
    · 매일 갱신되지만 **무료 등급은 과거 조회가 404** 이고(실측),
      문서가 **"Attribution Required"** 를 명시한다(실측). 우리 화면은 `source` 를 그대로
      표시하므로 그 요구를 자연히 만족하지만, 조건이 붙은 쪽을 1차로 두지 않는다.
  ⚠ 더 권위 있는 것은 **한국은행 ECOS · 한국수출입은행** 공시다. 둘 다 **API 키가 필요해**
    `.env` 비밀값 관리가 따라온다 — 이번 범위 밖으로 남긴다(보고에 적었다).

■ ★ 실패하면 무엇을 하나 — **옛 값을 그대로 둔다. 다만 조용히 낡지 않는다.**
  · 새 행을 만들지 않고 **기존 행을 건드리지 않는다**(비우지 않는다). 값을 비우면 환산이
    사라져 사장님이 원한 정보가 통째로 없어진다.
  · **「조용히 낡은 값을 최신인 척」은 스키마가 구조적으로 막는다** — `fx_rates.rate_date`
    가 NOT NULL 이라 어떤 행도 «언제 기준인지» 없이는 존재할 수 없다. 화면은 환산 옆에
    그 날짜를 함께 적으면 된다(화면 담당).
  · 이 도구는 실패를 **삼키지 않는다**: 사유를 출력하고 **종료코드 2** 로 끝난다.
    타이머가 붙으면 그 실패가 로그에 남는다.
  · `--stale-days`(기본 3) 보다 기준일이 낡으면 성공해도 경고를 낸다.

■ ★ 하루 한 번을 무엇이 돌리나 — **지금은 아무것도 없다(실측). 수동 실행이다.**
  저장소에 정기 실행 장치가 없다: `.timer` 파일 **0건**, `deploy/` 에는 `popcorn-api.service`
  하나뿐이고 cron 설정도 없다(certbot 타이머는 인증서 갱신용이라 우리 것이 아니다).
  **없는 것을 있는 척하지 않는다** — 붙일 때 쓰라고 예시만 남긴다(배포 담당 몫):

      # /etc/systemd/system/popcorn-fx.service   (Type=oneshot)
      #   ExecStart=/srv/projects/popcorn-ai/.venv/bin/python tools/fx_fetch.py
      # /etc/systemd/system/popcorn-fx.timer
      #   OnCalendar=*-*-* 09:30:00   Persistent=true
      #   (ECB 공시가 유럽 오후라 한국 아침이면 전날치가 확정돼 있다)

■ ⚠ 마이그레이션 0059 가 적용되기 전에는 쓰지 않는다
  표가 없으면 **넣지 않고 이유를 말하고 멈춘다**(조용한 실패 금지).
"""
import argparse
import datetime as dt
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
from email.utils import parsedate_to_datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools._console import ensure_utf8_console       # noqa: E402
ensure_utf8_console()

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.environ.get("FX_CACHE") or os.path.join(ROOT, ".cache", "fx")
UA = "popcorn-ai/1.0 fx_fetch (internal daily batch)"
TIMEOUT = 15
DELAY = 1.5              # 출처를 갈아탈 때의 간격(초) — danawa_fetch 와 같은 값
MAX_FAIL = 2             # 출처 수와 같다. 전부 실패하면 더 시도하지 않는다
BASE, QUOTE = "USD", "KRW"


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read().decode("utf-8")


def _cache(name: str, body: str) -> str:
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, name)
    with io.open(p, "w", encoding="utf-8") as f:
        f.write(body)
    return p


# ── 출처 ─────────────────────────────────────────────────────────────────────
# 파서는 «원문이 말하는 기준일»을 반드시 돌려준다. 없으면 그 출처는 쓰지 않는다 —
# 오늘 날짜로 채우면 주말에 받은 금요일 값이 오늘 것으로 둔갑한다.
def _parse_frankfurter(raw: str):
    d = json.loads(raw)
    if d.get("base") != BASE or QUOTE not in (d.get("rates") or {}):
        raise ValueError(f"예상과 다른 응답 형식: {raw[:120]}")
    return float(d["rates"][QUOTE]), dt.date.fromisoformat(d["date"])


def _parse_er_api(raw: str):
    d = json.loads(raw)
    if d.get("result") != "success" or QUOTE not in (d.get("rates") or {}):
        raise ValueError(f"예상과 다른 응답 형식: {raw[:120]}")
    return (float(d["rates"][QUOTE]),
            parsedate_to_datetime(d["time_last_update_utc"]).date())


SOURCES = [
    ("frankfurter.dev",
     f"https://api.frankfurter.dev/v1/latest?base={BASE}&symbols={QUOTE}",
     _parse_frankfurter),
    ("open.er-api.com",
     f"https://open.er-api.com/v6/latest/{BASE}",
     _parse_er_api),
]


def collect() -> tuple:
    """(source, url, rate, rate_date) 또는 전부 실패면 None. 실패 사유는 그때그때 출력한다."""
    fails = 0
    for i, (name, url, parse) in enumerate(SOURCES):
        if i:
            time.sleep(DELAY)
        try:
            raw = _get(url)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
            fails += 1
            print(f"  [실패] {name}: 가져오지 못했습니다 - {e}")
            if fails >= MAX_FAIL:
                break
            continue
        try:
            rate, rate_date = parse(raw)
        except (ValueError, KeyError, TypeError) as e:
            fails += 1
            print(f"  [실패] {name}: 응답을 읽지 못했습니다 - {e}")
            if fails >= MAX_FAIL:
                break
            continue
        p = _cache(f"{name}-{rate_date.isoformat()}.json", raw)
        print(f"  [성공] {name}: 1 {BASE} = {rate:,.6f} {QUOTE}"
              f" (기준일 {rate_date}) · 원문 캐시 {os.path.relpath(p, ROOT)}")
        return name, url, rate, rate_date
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true",
                    help="가져와 보기만 한다 - DB 를 건드리지 않는다")
    ap.add_argument("--stale-days", type=int, default=3,
                    help="기준일이 이보다 낡으면 경고한다(기본 3)")
    args = ap.parse_args()

    print(f"환율 수집 {BASE}->{QUOTE} · 출처 {len(SOURCES)}곳")
    got = collect()
    if got is None:
        # 실패를 삼키지 않는다. 기존 행은 그대로 둔다(비우지 않는다).
        print("[중단] 모든 출처에서 환율을 가져오지 못했습니다."
              " 기존 값은 그대로 두었습니다 - 화면은 마지막 기준일을 계속 표시합니다.")
        return 2
    name, url, rate, rate_date = got

    age = (dt.date.today() - rate_date).days
    if age > args.stale_days:
        print(f"[경고] 기준일이 {age}일 지났습니다({rate_date})."
              f" 출처가 갱신을 멈췄는지 확인하십시오.")

    if args.dry:
        print("[확인만] --dry 라 DB 에 넣지 않았습니다. 넣을 값:")
        print(f"    base={BASE} quote={QUOTE} rate={rate} rate_date={rate_date}")
        print(f"    source={name} source_url={url}")
        return 0

    from dotenv import load_dotenv
    from sqlalchemy import create_engine, text
    load_dotenv(os.path.join(ROOT, ".env"))
    eng = create_engine(os.environ["DATABASE_URL"], future=True)
    with eng.begin() as conn:
        exists = conn.execute(text(
            "SELECT to_regclass('public.fx_rates')")).scalar()
        if not exists:
            # 조용히 넘어가지 않는다 - 무엇을 해야 하는지까지 말한다.
            print("[중단] fx_rates 표가 없습니다."
                  " 마이그레이션 0059 를 먼저 적용해야 합니다(DBA 소관).")
            return 3
        n = conn.execute(text(
            "INSERT INTO fx_rates (base_code, quote_code, rate, rate_date,"
            " source, source_url) VALUES (:b, :q, :r, :d, :s, :u)"
            " ON CONFLICT (base_code, quote_code, rate_date, source) DO NOTHING"),
            {"b": BASE, "q": QUOTE, "r": rate, "d": rate_date,
             "s": name, "u": url}).rowcount
    print(f"[완료] {'새 행 1건 기록' if n else '같은 기준일·출처가 이미 있어 건너뜀'}"
          f" (기준일 {rate_date} · 출처 {name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
