# -*- coding: utf-8 -*-
"""AI 용도 GPU 하한을 «전원(W)» 에서 «VRAM(GB)» 으로 바꾼다 — 650W -> VRAM 12GB.

설계 정본: docs/design/usage-rules-rebuild-2026-09-18.md §4(표 셋의 판정 질문)
근거 원천: `software` · `software_community_spec` 실조회(2026-09-20). 한 값도 짓지 않았다.

■ 왜 와트가 아니라 VRAM 인가 — 증상이 «느림» 이 아니라 «안 돌아감» 이다
  CLAUDE.md 명시: 스테이블 디퓨전의 VRAM 부족은 느려지는 것이 아니라 **실행 실패(OOM)**
  다. 와트로 거르면 그 사실을 한 번도 말하지 못한다 — 650W 짜리 8GB 카드를 받은
  고객은 «비싼데 안 돌아가는» PC 를 받는다. 반대로 550W 12GB 카드는 실제로 돌아가는데
  현재 규칙이 탈락시킨다. 실조회가 그 어긋남을 그대로 보여준다:

      재고 GPU 175종(추천 후보) · vram_gb·required_power_watt 둘 다 결측 0건

      조건                통과  최저가          무엇이 걸러지나
      required_power_watt>=650   72  1,080,900   12GB 카드 17종 중 15종만 통과,
                                                 8GB 카드는 73종 «전부» 탈락(옳다),
                                                 그러나 16GB 카드 69종 중 15종도 탈락
      vram_gb>=12                89    514,300   8GB 이하 86종 탈락 · 12GB 이상 전부 통과

  즉 와트 하한은 **같은 일을 더 비싸게, 그리고 부정확하게** 하고 있었다.
  650W 는 `software` 어디에도 근거가 없는 값이다(0090 이 시장 표본 없이 넣었다 —
  0104 가 3D 의 850W 를 같은 이유로 버렸다. 이것이 그 짝이다).

■ 값을 12 로 고른 근거 — `software_community_spec` 실조회 (표본 수 병기)
  기준은 §4 확립분: **하한 = 카테고리 최저 커뮤니티값**, 겨냥 = 무거운 쪽.

  AI 카테고리 4종 중 커뮤니티 VRAM 값이 있는 것은 4종 전부이나,
  **confidence='추정' 2종은 견적 규칙에 직접 투입하지 않는다**(CLAUDE.md 규약):

      프로그램                     confidence  커뮤니티 vram_gb  채택
      스테이블 디퓨전 (WebUI)       확인          12              O
      올라마 (로컬 LLM 구동)        확인          16              O
      컴피UI                        추정          12              X (SD 를 준용한 파생값)
      LLM 파인튜닝 (로컬 학습)      추정          24              X (QLoRA 전제의 해석값)

      => 채택 표본 **n=2**. 최저값 12 · 최고값 16.

  공식값(`software`)은 하한 근거가 되지 못한다 — **AI 4종 중 rec_vram_gb 가 있는 것이
  0종**이고, min_vram_gb 는 스테이블 디퓨전 4 하나뿐이다(n=1). 그 4GB 는 커뮤니티
  note 가 "이번 조사에서 공식과 실사용의 격차가 가장 큰 항목"이라고 직접 지목한 값이라
  그대로 쓰면 못 쓰는 PC 가 나간다. **두 컬럼이 따로 있는 이유가 여기서 드러난다.**

  ⚠ 신뢰도 하향을 이미 반영한 값이다. CLAUDE.md: AI 분야 커뮤니티 출처는 GPU 추천
    상업블로그가 다수라 한 단계 낮게 본다. 두 note 가 스스로 같은 경고를 적고 있고,
    동시에 **둘 다 독립적으로 12 를 「쓸 만한 하한」으로 지목**한다:
      SD    "SDXL 은 8GB 로 가능하나 12GB 가 편안한 하한 · 12GB 가 스위트스팟"
      올라마 "실질 권장은 12GB 부터 쓸만, 16GB 가 스위트스팟"
    그래서 **16(스위트스팟)이 아니라 12(하한)를 쓴다** — 하향 판단이 곧 12 다.
    16 은 하한이 아니라 겨냥이고, 그 자리는 이미 `usage_tier_rules`(ai 550만원 VRAM
    16GB · 800만원 32GB)에 있다. 표를 옮기지 않는다.

■ 어느 표인가 — `usage_floors` (판정 질문 셋을 순서대로)
  ① 다른 슬롯 선택에 달렸는가? **아니다.** 어떤 CPU·RAM 을 골랐든 12GB 는 12GB 다.
     -> part_cond_rules 아님.
  ② 예산이 오르면 값도 오르는가? **오른다. 그런데 그 자리는 이미 차 있다.**
     ai 는 usage_tier_rules 에 150만 8GB · 300만 12GB · 550만 16GB · 800만 32GB 가
     이미 있다. 이 변경은 그 계단의 «맨 아래» 가 아니라 **계단이 시작되기 전의 바닥**을
     다룬다.
  ③ 예산과 무관하게 이 밑으로는 그 용도를 «못 하는가»? **못 한다 — 이것이 결정적이다.**
     VRAM 부족은 성능 저하가 아니라 프로세스가 죽는 일(OOM)이다. 개발 RAM 16GB 가
     「8GB 로는 IDE 가 스왑한다」로 하한이 된 것보다 **더 강한 조건**이다 — 스왑은 느릴
     뿐이지만 OOM 은 아예 실행되지 않는다. 돈이 없어도 내릴 수 없다.
     => **usage_floors**. (기존 행의 field 를 바꾼다 — floor_id 4 의 이력을 끊지 않는다)

■ 고객 부담 — **오른 게 아니라 내려간다** (실측, 2026-09-20)
  하한을 «올렸는데» 견적가가 내려가는 드문 경우다. 와트 하한이 값싼 12GB 카드를
  잘못 떨어뜨리고 있었기 때문이다.

      AI 슬롯별 최저가 합(GPU+RAM32+SSD1000+CPU+MB+CASE+POWER)
        전  required_power_watt>=650  GPU 1,080,900  -> 합 1,822,600
        후  vram_gb>=12               GPU   514,300  -> 합 1,256,000   **-566,600**

  전/후 실견적 비교는 보고서에 싣는다(여러 예산대 · 3티어). 불성립 방향도 개선된다 —
  전에는 150만원 이하 전 티어 불가였다.

■ usage_tier_rules — ai 150만원 «VRAM 8GB 이상» 행을 내린다(active=FALSE)
  하한이 12 가 되면 이 겨냥(8)은 **하한보다 낮다.** 남겨 두면 근거 문구가
  "AI 작업 하한 — 그래픽카드 12GB 이상 … 시장 표준 — 그래픽카드 VRAM 8GB 이상"
  이라고 **한 줄 안에서 서로 다른 말**을 한다(§화면 정직성 「한 행이 두 원천으로
  말하지 않는다」). 삭제가 아니라 비활성이다 — 되돌릴 수 있어야 한다.
  ⚠ ai 300만 12GB 행은 그대로 둔다. 하한과 같은 값이라 무해하고, 예산 계단의
    연속성(12 -> 16 -> 32)을 끊지 않는다.

■ design — **이번에 건드리지 않는다.** 근거가 하한을 지지하지 않는다
  실조회(`software` 카테고리 '사진·디자인' 5종 + `software_community_spec`):

      프로그램        공식 min/rec vram   커뮤니티 vram   confidence
      어도비 포토샵        2 / 2              8            확인
      어도비 일러스트      1 / 4             (없음)         확인
      어도비 라이트룸      2 / 8             16            확인
      어도비 인디자인      1 / 2             (없음)         확인
      피그마              (없음)            (없음)         확인

      공식 rec_vram_gb  n=4  최저 2 · 최고 8
      커뮤니티 vram_gb  n=2  최저 8 · 최고 16   <- 표본이 5종 중 2종뿐이다

  「카테고리 최저 커뮤니티값」을 기계적으로 적용하면 8 이다. 그런데 **넣지 않는다.**
  근거 넷:

    ① **판정 질문 ③ 의 답이 「아니오」다.** 포토샵·일러스트·인디자인의 공식 권장은
       각각 2·4·2GB — 내장그래픽 수준이다. 명함·전단·문서 조판은 지금도 iGPU 로 된다.
       「이 밑으로는 그 용도를 못 한다」가 성립하지 않으므로 하한 표의 대상이 아니다.
       design 의 GPU 겨냥은 **이미 usage_tier_rules 에 있다**(150만원 VRAM 8GB) —
       「GPU 조건이 아예 없다」는 관측은 `usage_floors` 만 본 결과다.

    ② **표본 2건이 둘 다 Puget Systems 유래다.** CLAUDE.md: Puget 수치는 워크스테이션
       판매사 기준이라 방향은 신뢰하되 숫자를 하향한다. 더구나 **포토샵 note 는 스스로
       숫자를 내린다** — 원문 "VRAM은 4K 다중 모니터가 아니면 4GB로 충분이라 하여 오히려
       공식보다 완화". 즉 커뮤니티 8 이라는 저장값보다 그 근거 문장이 더 낮은 수를
       말한다. 이 상태로 하한을 박으면 근거와 값이 어긋난 채 고정된다.

    ③ **고객 부담이 크고, 그 부담이 제일 가벼운 고객에게 간다.** 실측(2026-09-20):
       design 에 GPU 하한이 «있기만 하면» 종류를 불문하고 `allow_igpu_omit` 이 꺼져
       내장그래픽 경로가 통째로 막힌다(api/recommend.py 1775-1780).
         지금  design 가성비 448,500원 (내장그래픽, 전 예산대 공통)
         VRAM 8 하한 시  최저 GPU 390,100원이 강제 추가 -> 85만원선
                         (같은 하한을 가진 cad 의 150만원 가성비 실측 851,600원)
       **+40만원이 명함 만드는 고객에게 그대로 간다.** 사무용 RAM 16GB 건과 같은 모양이다.

    ④ **불성립이 생긴다.** cad 실측: 80만원에서 가성비·추천 두 티어가 불가(고성능만
       119만원으로 초과 표기). design 도 같은 하한을 받으면 60·80만원대가 무너진다 —
       게임 40만원 전례와 같은 사고다.

  ⇒ **표본이 없으면 없다고 하고 하한을 안 건드린다.** 대신 하네스를 통해 사장님께
     **design 분할**을 제안한다(실행하지 않는다 — 사무·사무복합 분할과 같은 자리).
     제안 내용은 보고서에 있다. 분할이 확정되면 그때 무거운 쪽에만 커뮤니티 8/16 을
     쓸 수 있다 — 지금은 한 키에 두 고객이 섞여 있어 어느 값도 옳지 않다.

Revision ID: 0107
Revises: 0106
"""
import sqlalchemy as sa
from alembic import op

revision = "0107"
down_revision = "0106"
branch_labels = None
depends_on = None


AI_KEY = "ai"

# ── 신규(VRAM) ────────────────────────────────────────────────────────────────
# ⚠ 근거 문구에 **숫자가 있어야 한다**(CLAUDE.md: "고사양 GPU 등급"이 아니라
#   "VRAM 12GB 이상"). 그리고 AI 는 «안 돌아감» 을 말해야 한다 — 고객이 모르고
#   사면 못 쓴다. detail_fmt 가 그 두 가지를 한 문장에 담는다.
NEW_FIELD, NEW_VALUE = "vram_gb", 12
NEW_LABEL = "AI 작업 그래픽 메모리(VRAM)"
NEW_FMT = (
    "VRAM {v}GB — 스테이블 디퓨전 커뮤니티 권장 {r}GB(올라마 로컬 LLM 은 16GB)."
    " AI 작업은 VRAM 이 모자라면 느려지는 것이 아니라 실행 자체가 실패합니다(메모리 부족)."
    " 로컬 LLM 을 크게 쓰시면 24GB 이상으로 올립니다")

# ── 기존(전원 W) — downgrade 복원용. 0090 이 넣은 값 그대로 실조회해 적었다 ────
OLD_FIELD, OLD_VALUE = "required_power_watt", 650
OLD_LABEL = "AI 작업 GPU 등급"
OLD_FMT = "권장 전원 {v}W 이상 (기준 {r}W 이상)"


def upgrade() -> None:
    conn = op.get_bind()

    # ① usage_floors — ai · GPU 슬롯의 field/value/문구를 바꾼다(행은 그대로).
    #    slot='GPU' 로 좁힌다 — 같은 usage_key 의 RAM/SSD 행은 손대지 않는다.
    conn.execute(sa.text(
        "UPDATE usage_floors SET field=:f, value=:v, label=:l, detail_fmt=:d"
        " WHERE usage_key=:k AND slot='GPU'"),
        {"f": NEW_FIELD, "v": NEW_VALUE, "l": NEW_LABEL, "d": NEW_FMT, "k": AI_KEY})

    # ② usage_tier_rules — 하한(12)보다 낮아진 겨냥(150만원 VRAM 8GB)을 내린다.
    #    삭제가 아니라 active=FALSE (되돌릴 수 있어야 한다).
    conn.execute(sa.text(
        "UPDATE usage_tier_rules SET active=FALSE, note = COALESCE(note,'') ||"
        " ' [0107 비활성] usage_floors 의 ai GPU 하한이 VRAM 12GB 가 되어 이 겨냥(8GB)이"
        " 하한보다 낮아졌다. 남겨 두면 근거 한 줄이 12 와 8 을 동시에 말한다.'"
        " WHERE usage_key=:k AND slot='GPU' AND field='vram_gb' AND op='gte'"
        "   AND budget_min=1500000 AND active"),
        {"k": AI_KEY})


def downgrade() -> None:
    conn = op.get_bind()

    conn.execute(sa.text(
        "UPDATE usage_tier_rules SET active=TRUE"
        " WHERE usage_key=:k AND slot='GPU' AND field='vram_gb' AND op='gte'"
        "   AND budget_min=1500000"),
        {"k": AI_KEY})

    conn.execute(sa.text(
        "UPDATE usage_floors SET field=:f, value=:v, label=:l, detail_fmt=:d"
        " WHERE usage_key=:k AND slot='GPU'"),
        {"f": OLD_FIELD, "v": OLD_VALUE, "l": OLD_LABEL, "d": OLD_FMT, "k": AI_KEY})
