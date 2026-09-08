# -*- coding: utf-8 -*-
"""GPU 성능 서열표 — gpu_ladder 레거시(구세대) GPU 확장

■ 왜 확장이 필요했는가
  `docs/design/game-quote-mapping-2026-09-07.md` §1 판정 로직으로 드라이런을
  돌린 실측: games(23종) 중 **21종**이 `rec_gpu_parse_failed`로 스킵됐다.
  게임 공식 요구사양은 GTX 970·GTX 1060 같은 구세대 카드를 기준으로 적혀
  있는데(예: "권장: GTX 1060 6GB 이상"), 0074가 심은 gpu_ladder는 재고
  실측 신세대 GPU 16종뿐이라 그 이름을 하나도 못 찾았다. 표를 못 찾으면
  판정이 "성립"도 "불성립"도 못 내리고 조용히 스킵되므로(§화면 정직성과
  같은 원칙 — 판정 못 하는 것을 지어내지 않는다), 서열표 자체를 넓히는
  것 말고는 해소할 방법이 없다.

■ 정본 척도 — RTX3090=100 표를 메인표(RTX5090=100)로 이었다
  구세대 GPU 상당수는 Tom's Hardware 메인표(RTX5090=100 기준, 0074가 쓴
  `4388.html`)에 없고, 같은 사이트의 구간 표(`4388-3.html`, RTX3090=100
  기준)에만 있다. 두 표는 겹치는 카드(RTX 3090)가 있어 환산계수를 계산할
  수 있다: 메인표의 RTX 3090 값 60.3(100 만점 중) ÷ 구간표의 RTX 3090 값
  100 = **0.603**. 구간표 값에 0.603을 곱하면 메인표(RTX5090=100) 척도로
  환산된다 — 이 마이그레이션의 정본 A 값(13.3·16.0·17.2 등)은 이미 그
  환산을 마친 결과값이고, note에 그 사실과 계수를 남긴다(값 자체를 다시
  계산할 필요는 없다 — 지어내지 않기 위해 계산식을 밝히는 것뿐이다).

  정본에 없는 2종(GTX 960·RX 470)은 인접 카드 대비 실측 비율로 2차
  추정했다 — 0074가 RX 9060·GTX 1660 SUPER에 쓴 것과 같은 방식(추정값임을
  숨기지 않는다, note에 계산식·출처 URL 명시).

■ gpu_chipset_key() 검증
  이번 세션은 Bash 실행이 승인 대기로 막혀 함수를 직접 호출하지 못했다
  (`.venv/Scripts/python -c "..."` 세 번 모두 승인 거부). 대신
  `api/catalog_map.py`의 정규식 원문을 직접 읽어 수동으로 대조했다:

      GPU_MODEL = re.compile(r"(RTX|GTX|GT|RX)\s?(\d{3,4})\s?(Ti|SUPER|XT|XTX)?", re.I)
      return f"{group1.upper()} {group2}{' '+group3.upper() if group3 else ''}"

  이 규칙으로 아래 표의 각 상품명이 어떤 chipset 키가 되는지 도출했다(수를
  지어내지 않기 위해, 이 마이그레이션의 chipset 값은 전부 이 정규식을
  손으로 대조한 결과다 — 함수를 실제로 실행해 재확인이 필요하다, 하네스
  실행 시 확인 바람):

      GTX 970                 -> "GTX 970"
      GeForce GTX 1060 6GB    -> "GTX 1060"   (VRAM 표기 "6GB"는 접미사
                                                Ti|SUPER|XT|XTX 어디에도
                                                안 걸려 버려진다)
      GTX 1650 Super          -> "GTX 1650 SUPER"
      GTX 1050 Ti             -> "GTX 1050 TI"
      Radeon RX 580           -> "RX 580"
      RX 5700 XT              -> "RX 5700 XT"
      RX 6600 / RX 6600 XT    -> "RX 6600" / "RX 6600 XT"
      RX 6700 XT              -> "RX 6700 XT"
      RX 6800                 -> "RX 6800"
      RTX 2060 / RTX 2060 SUPER -> "RTX 2060" / "RTX 2060 SUPER"
      RTX 2080                -> "RTX 2080"
      RTX 3080                -> "RTX 3080"
      GTX 1080                -> "GTX 1080"
      RX 560                  -> "RX 560"
      GTX 960                 -> "GTX 960"
      RX 470                  -> "RX 470"

■ ⚠ RTX 3060 은 이 마이그레이션에 넣지 않는다 — 0074와 충돌
  정본 A 표에 "RTX 3060 33.0 12"가 있었으나, 0074가 이미 같은 chipset
  키("RTX 3060")로 `ladder_score=30.2, vram_gb=12`를 심어 두었다
  (0074 note: "Tom's Hardware 표는 'RTX 3060 12GB' 단일 항목 — 우리
  재고와 일치"). `chipset`은 UNIQUE라 그대로 넣으면 UniqueViolation으로
  마이그레이션이 실패한다. 두 값(30.2 vs 33.0)이 다른 이유는 확인되지
  않았다(메인표 페이지와 이번 구간표 페이지가 서로 다른 조사 시점/페이지를
  가리킬 가능성) — **값을 지어내 덮어쓰지 않고 이 갈등을 기록만 한다.**
  0074의 기존 값을 바꿀지는 별도 판단(DBA/사장님)이 필요하다. 그래서
  아래 시드에는 정본 A의 17건 중 RTX 3060을 뺀 16건 + 2차 추정 2건 =
  **18건**만 넣는다.

Revision ID: 0076
Revises: 0075
"""
import sqlalchemy as sa
from alembic import op

revision = "0076"
down_revision = "0075"
branch_labels = None
depends_on = None


TOMS_URL_MAIN = "https://www.tomshardware.com/reviews/gpu-hierarchy,4388-3.html"
CONV_NOTE = "RTX3090=100 척도를 메인표(RTX5090=100) 환산계수 0.603 적용"

# (chipset, ladder_score, vram_gb, source_url, checked_date, note)
# chipset 은 api/catalog_map.gpu_chipset_key() 정규형과 같은 표기(위 머리 주석 표 참조).
GPU_LADDER_LEGACY = [
    ("GTX 970", "13.3", 4, TOMS_URL_MAIN, "2026-09-07", CONV_NOTE),
    ("GTX 1060", "16.0", 6, TOMS_URL_MAIN, "2026-09-07", CONV_NOTE),
    ("GTX 1650 SUPER", "17.2", 4, TOMS_URL_MAIN, "2026-09-07", CONV_NOTE),
    ("GTX 1050 TI", "9.7", 4, TOMS_URL_MAIN, "2026-09-07", CONV_NOTE),
    ("RX 580", "18.6", 8, TOMS_URL_MAIN, "2026-09-07", CONV_NOTE),
    ("RX 5700 XT", "34.4", 8, TOMS_URL_MAIN, "2026-09-07", CONV_NOTE),
    ("RX 6600", "29.7", 8, TOMS_URL_MAIN, "2026-09-07", CONV_NOTE),
    ("RX 6600 XT", "34.8", 8, TOMS_URL_MAIN, "2026-09-07", CONV_NOTE),
    ("RX 6700 XT", "44.2", 12, TOMS_URL_MAIN, "2026-09-07", CONV_NOTE),
    ("RX 6800", "51.7", 16, TOMS_URL_MAIN, "2026-09-07", CONV_NOTE),
    ("RTX 2060", "27.1", 6, TOMS_URL_MAIN, "2026-09-07", CONV_NOTE),
    ("RTX 2060 SUPER", "30.5", 8, TOMS_URL_MAIN, "2026-09-07", CONV_NOTE),
    ("RTX 2080", "37.7", 8, TOMS_URL_MAIN, "2026-09-07", CONV_NOTE),
    # RTX 3060 은 0074와 충돌해 뺐다 — 위 머리 주석 "⚠ RTX 3060" 참조.
    ("RTX 3080", "56.2", 10, TOMS_URL_MAIN, "2026-09-07", CONV_NOTE),
    ("GTX 1080", "27.3", 8, TOMS_URL_MAIN, "2026-09-07", CONV_NOTE),
    ("RX 560", "7.5", 4, TOMS_URL_MAIN, "2026-09-07", CONV_NOTE),
    ("GTX 960", "8.5", 2,
     "https://technical.city/en/gpu/GeForce-GTX-970-vs-GeForce-GTX-960",
     "2026-09-07",
     "GTX 970(13.3) 대비 GTX960 이 약 1.57배 느림(technical.city 실측 "
     "\"GTX 970 outperforms GTX 960 by 57%\") -> 13.3/1.57=8.5"),
    ("RX 470", "15.6", 4,
     "https://gpu.userbenchmark.com/Compare/AMD-RX-580-vs-AMD-RX-470/3923vs3640",
     "2026-09-07",
     "RX 580(18.6) 대비 약 84%(RX570이 RX470보다 ~10% 빠르고 RX580이 "
     "RX570보다 ~20% 빠름 — userbenchmark 체인 추정) -> 18.6*0.84=15.6"),
]


def upgrade() -> None:
    conn = op.get_bind()
    for chipset, score, vram, source_url, checked_date, note in GPU_LADDER_LEGACY:
        conn.execute(sa.text(
            "INSERT INTO gpu_ladder "
            "(chipset, ladder_score, vram_gb, source_url, checked_date, note) "
            "VALUES (:chipset, :score, :vram, :source_url, :checked_date, :note)"
        ), {
            "chipset": chipset,
            "score": score,
            "vram": vram,
            "source_url": source_url,
            "checked_date": checked_date,
            "note": note,
        })
    print(f"[0076] gpu_ladder 레거시 시드: {len(GPU_LADDER_LEGACY)}건 "
          f"(RTX 3060은 0074와 충돌해 제외 — 머리 주석 참조)")


def downgrade() -> None:
    conn = op.get_bind()
    chipsets = [row[0] for row in GPU_LADDER_LEGACY]
    conn.execute(
        sa.text("DELETE FROM gpu_ladder WHERE chipset = ANY(:chipsets)"),
        {"chipsets": chipsets},
    )
