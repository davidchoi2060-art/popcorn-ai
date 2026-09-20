# -*- coding: utf-8 -*-
"""디자인 용도 2분할 — `design` -> «디자인·조판»(design_edit) · «사진·후보정»(design_photo).

설계 정본: docs/design/usage-rules-rebuild-2026-09-18.md §2 · §4
사장님 확정(2026-09-20): "design 2분할 해" + "격자 재생성 하고"
선례: 0102(사무 분할) · 0104(3D 분할) — **같은 방식**(개명 + 신설)을 그대로 따랐다.

■ 왜 나누는가 — `software.bottleneck` 컬럼 자체가 근거다 (2026-09-20 실조회)

    프로그램            bottleneck  공식 min/rec RAM  공식 min/rec VRAM
    피그마              balanced    - / -             - / -
    어도비 포토샵        ram         8 / 16            2 / 2
    어도비 인디자인      ram         8 / 16            1 / 2
    어도비 일러스트레이터 cpu         8 / 16            1 / 4
    어도비 라이트룸      vram        8 / 16            2 / **8**   <- 5종 중 유일

  `design` 한 키가 이 다섯을 묶고 있다. 그런데 **넷은 GPU 를 거의 안 쓴다** —
  note 원문이 그렇게 적는다:
    인디자인  "공식 GPU 요구가 VRAM 1~2GB로 매우 낮아 그래픽카드 투자 실익이 거의 없다"
    일러스트  "공식 문서가 'VRAM 1GB(권장 4GB)'로 GPU 요구가 낮고 ... GPU보다 CPU 단일 성능·RAM"
    포토샵    "GPU는 일정 수준(VRAM 2~4GB) 이상이면 성능 차가 거의 없고 ... 돈을 더 써야 할 곳은 RAM"
    피그마    "WebGL 기반이라 그래픽 요구가 매우 낮아 대부분의 브라우저에서 잘 돌아간다"
  하나만 반대다:
    라이트룸  "공식 문서가 직접 'AI 기능 풀가속에는 전용 GPU 메모리 8GB'라고 적은 것이 결정적"

  즉 한 키 안에 **명함 찍는 사람**과 **RAW 5천장 돌리는 사진관**이 섞여 있다.
  나누면 둘 다 맞는다 — 0102·0104 가 각각 사무·3D 에서 확인한 것과 같은 모양이다.

■ ★ 판정 ⓐ/ⓑ/ⓒ — **ⓑ(design 을 design_edit 로 개명 + design_photo 신설)**
  ⓐ design 을 남기고 둘을 추가 — 버린다. 세 키가 되면 「디자인」이 어디로 갈지 다시
     모호해진다. 사장님 구분의 요점은 «둘 중 하나로 갈라라»다(0102·0104 와 같은 이유).
  ⓒ design 을 지우고 둘 다 신설 — 버린다. 회귀 [52]① 이
     「활성 usage_alloc.usage_key ⊆ usage_floors.usage_key」를 불변식으로 검사하는데
     `usage_alloc` 에 usage_key='design' 2행(GPU 30~45% · CPU 8~20%)이 **있다**.
     지우는 순간 깨진다. floor_id 의 이력도 끊긴다.
  ⓑ **개명** — 고른 쪽.

  ★ 어느 쪽을 개명하는가 — **design -> design_edit(디자인·조판)**. 근거 둘(0104 와 같은 질문):
    ① **값이 편집 쪽이다.** 지금 design 의 하한은 RAM 16 · SSD 500 이고 **GPU 하한이
       없다**. 라이트룸의 VRAM 8 을 한 번도 담은 적이 없는 값이다. 그 성격을 물려받을
       자리는 GPU 를 안 쓰는 넷(인디자인·일러스트·피그마·가벼운 포토샵)이 있는 편집이다.
    ② **라벨의 이력이 편집 쪽이다.** 실조회: `grid_cells.usage='디자인'` 6행 ·
       `consult_sessions.constraints` 251건(real 114 · test 137) · `grid_quotes.payload`
       36건이 문자열 「디자인」을 들고 있다. 그 6칸의 현재 견적을 열어 보면
       **가성비·추천·고성능 18장 전부가 내장그래픽(omitted GPU: cpu_has_igpu) 구성**이다
       (실측: 448,500 ~ 3,953,600). 「디자인」이라는 말이 지금까지 받아 온 것은
       GPU 없는 견적 — 즉 그 이력은 편집 쪽 것이다.
    ⚠ 그래서 design_edit 의 낱말에 **「디자인」을 그대로 남긴다**(아래 EDIT_TERMS).
      0102 에서 확립된 «모호한 말은 싼 쪽에» 원칙과도 방향이 같다.

■ ★ 사진·후보정에 GPU 하한을 «건다» — 그 결과를 실측했고, 그래서 건다
  ⚠ `api/recommend.py` 1775-1780: 용도에 **GPU 하한이 있기만 하면** 종류 불문
    `allow_igpu_omit` 이 False 가 되어 내장그래픽 경로가 통째로 막힌다.
    실측(2026-09-20, 로컬 :8000):
        디자인(분할 전) 190만 AMD 가성비  448,500   GPU 생략(cpu_has_igpu)
        캐드(VRAM 8 하한) 190만 AMD 가성비  851,600   RTX 3050 8GB
    사진·후보정도 같은 크기로 오른다. **그게 맞다** — 라이트룸 note 가
    "AI 노이즈 제거·렌즈 블러가 GPU 연산으로 들어오면서 성격이 바뀌었다"고 적고,
    공식이 직접 8GB 를 요구한다. 내장그래픽으로 AI Denoise 를 돌리는 견적을
    «사진관 고객»에게 내미는 것은 «싸게 준 것»이 아니라 **못 쓰는 것을 준 것**이다
    (0107 이 AI 에서 내린 판단과 같은 성격 — 증상이 느림이 아니라 안 됨이다).
    ⇒ 대신 «모호한 말은 싼 쪽»을 낱말로 철저히 지킨다(아래 ★ 낱말). 「디자인」·
      「포토샵」 단독은 **전부 편집으로** 떨어져 이 하한을 받지 않는다.
  ⚠ 편집·조판은 **한 값도 바뀌지 않는다**(하한·겨냥·배분 전부 design 그대로 개명).
    가장 가벼운 고객이 분할 때문에 비싸지면 안 된다는 요구를 구조로 보장한다.

■ 하한 값 — 전부 `software` / `software_community_spec` 실조회다. 한 값도 짓지 않았다
  기준은 §4 확립분: **하한 = 카테고리 최저 커뮤니티값**, 겨냥 = 무거운 쪽.
  ⚠ confidence='추정' 제외 · Puget 유래는 신뢰도 한 단계 낮게 · 표본 수 병기.

  design_photo(사진·후보정)
    GPU VRAM **8**  ← 이번 분할이 새로 거는 유일한 하한
        근거 ① 라이트룸 `software.rec_vram_gb=8` · confidence='확인' · **공식값**
              (note 원문: "공식 문서가 직접 'AI 기능 풀가속에는 전용 GPU 메모리 8GB'라고
               적은 것이 결정적이다 — 최소사양 2GB와 4배 차이다"). 표본 n=1(공식).
        근거 ② 포토샵 `software_community_spec.vram_gb=8` — **카테고리 최저 커뮤니티
              VRAM 값**. 표본 note 원문 "(표본: reddit 상위 게시물 6건 + Puget 1건)"
              => n=7, 그중 Puget 1건 포함이라 한 단계 낮춰 보되 **방향이 공식값과 같다**.
        ⚠ **라이트룸 커뮤니티 vram_gb=16 은 하한으로 쓰지 않았다.** note 가
          "(표본: Puget 1건 + reddit 2건)" n=3 이고 **Puget 유래**이며, 그 note 스스로
          "Adobe가 AI 가속에 VRAM 8GB를 권장하지만, 실사용자는 라이트룸만 켜두지
          않으므로 16GB VRAM 중급 GPU를 «권장»"이라고 적는다 — 해석이지 요구가 아니다.
          0104 가 스케치업 PBR 32GB 를 같은 이유로 버린 것과 같은 판단이다.
          16 은 겨냥이지 하한이 아니고, **겨냥을 새로 짓지도 않았다**(표본 n=3 · Puget
          유래로는 새 계단을 세울 근거가 얇다 — 지어내지 않는다).
    RAM 16   포토샵·라이트룸 `software.rec_ram_gb=16` 둘 다 · confidence='확인' (n=2 공식).
        ⚠ 커뮤니티 aggregate 는 둘 다 32 이지만 **하한으로 올리지 않았다.** 포토샵 note
          원문이 스스로 "'문서 크기 500MB 이하 16GB / 500MB~1GB 32GB'", "'32GB 이상은
          포토샵·라이트룸만 볼 때 거의 무의미' 등 의견이 갈린다 — 즉 16GB로 충분한
          사람과 64GB가 필요한 사람이 동시에 존재한다"고 적는다. 둘 다 Puget 유래를
          포함한다. 32 는 겨냥이고 그 자리는 **이미 차 있다**(design 300만원 RAM 32 —
          아래 ④ 가 두 갈래에 그대로 물려준다).
    SSD 500  옛 design 값 그대로. 포토샵 `rec_storage_gb=100`(스크래치 디스크 때문에
        min 10 -> rec 100 으로 벌어진다는 note) + RAW 원본 보관. 올릴 근거도 내릴
        근거도 `software` 에 없어 **건드리지 않는다**.

  design_edit(디자인·조판)
    RAM 16 · SSD 500 · **GPU 하한 없음** — 전부 옛 design 값 그대로다.
        RAM 16 은 인디자인·일러스트·포토샵 `rec_ram_gb=16`(n=3 공식·확인)이 같은 선을
        말한다. 피그마는 수치를 아예 공개하지 않는다(전 컬럼 null) — 표본이 없으므로
        올리지도 내리지도 않는다.
        GPU 하한을 **일부러 넣지 않는다**: 넷 중 셋의 note 가 "GPU 투자 실익이 없다"고
        직접 적고(위 ■), 넣는 순간 allow_igpu_omit 이 꺼져 명함 고객이 39만원짜리
        GPU 를 강제로 받는다.

■ ★ 낱말 — 여기서 과거에 사고가 났다(0104 'CAD' 만 넣어 「캐드」가 안 걸린 건)
  ① `match()` 는 **대소문자를 구분한다**(`t in value`) — 영문은 양쪽 표기를 다 넣는다.
  ② **모호한 말은 싼 쪽**(0102 확립) — 「디자인」 단독은 design_edit 이다.
  ③ **구체적 신호가 이긴다** — sort 로 정한다:
        design_photo  sort 15, 16, 17   (앞)
        design_edit   sort 18, 19       (뒤)
     photo 의 낱말은 전부 «특정 신호»다(사진·RAW·라이트룸·후보정·리터칭). 모호어가
     하나도 없다. 모호어(「디자인」·「포토샵」·「일러」)는 **design_edit 만** 갖는다.
     따라서 "포토샵만 써요" -> photo 에 안 걸리고 -> **design_edit**(싼 쪽).
     "포토샵으로 4K 합성" -> 「4K 합성」이 photo 에 있어 **photo 가 이긴다**.
  ⚠ design 이 쓰던 15·16 을 그대로 photo 에 주고 edit 을 18·19 로 민다. 17~19 는
    비어 있던 자리다(다음이 trading 21) — trading·dev·stream·music·office·cad·
    render_3d 의 상대 순서를 한 줄도 건드리지 않는다.

  ★ 판정 — **「포토샵」·「포샵」은 design_edit 이다** (판단이 갈릴 수 있는 자리)
    포토샵은 양쪽 공용어다. 그런데 `software` 가 포토샵을 어디에 두는지는 분명하다:
    bottleneck='ram' · 공식 rec_vram_gb=**2** · 커뮤니티 note "VRAM은 '4K 다중
    모니터가 아니면 4GB로 충분'이라 하여 오히려 공식보다 완화".
    **포토샵이라는 말 자체에는 GPU 하한의 근거가 없다.** 그래서 싼 쪽에 둔다.
    무거운 포토샵 고객은 자기 입으로 다른 말을 같이 한다 — 「사진」·「RAW」·「보정」·
    「합성」·「누끼」·「사진관」. 그 말들이 photo 에 있고 photo 가 앞선다.
    싼 걸 내밀고 되묻는 편이 비싼 걸 내미는 것보다 낫다(0102 §★ 판정과 같은 문장).

  ★ 판정 — **「그래픽 작업」 바 그대로는 넣지 않는다** (판단이 갈린 자리, 명시한다)
    조사 실측대로 국내 입말에서 「그래픽 작업」은 2D(포샵·일러)를 뜻한다. 그런데
    design_edit(18)이 render_3d(103)보다 **앞이라**, 「그래픽 작업」을 넣으면
    「3D 그래픽 작업」이 render_3d 에서 design_edit 으로 **샌다**. 0104 가 「그래픽」을
    넣지 않은 이유(render_3d 가 물려받은 옛 라벨 「3D 그래픽」)와 같은 자리다.
    ⇒ 대신 **3D 와 붙을 수 없는 형태만** 넣는다: 「2D 그래픽」·「그래픽 디자인」.
      실제 고객 문장 "그래픽 작업(포샵, 일러)" 은 「포샵」·「일러」로 이미 잡힌다
      (아래 검증표로 확인). 바 「그래픽 작업」 단독은 여전히 미매칭으로 남는다 —
      그것이 3D 를 훔치는 것보다 낫다고 판단했다.

  ⚠ 넣지 않은 말과 그 이유(전부 «다른 용도를 훔치기 때문»이다. 실측으로 골랐다):
      ★ 이 목록은 **손으로 고른 것이 아니라 전수 검사로 찾았다.** 두 갈래의 낱말
        하나하나를 다른 모든 용도의 낱말과 부분문자열 대조하고, design 쪽이
        sort 에서 «앞설 때만» 훔친다는 조건으로 걸렀다. 그 검사가 실제로 하나를
        잡았다 — 아래 「BI」다(처음 판에 들어 있었고, 검사가 없었으면 못 봤다).
      「BI」 단독  cad 의 「BIM」(100)을 훔친다 — edit(18)이 앞이라
                「BIM 설계합니다」·「레빗 BIM 모델링」이 **design_edit 으로 샜다**(실측).
                => 「BI 디자인」·「CI·BI」로 좁힌다. 「CI」도 두 글자 영문이라 같은
                   위험이 있어 함께 좁혔다(선제 조치 — 지금 훔치는 것은 없다).
      「스케치」   cad 의 「스케치업」(100)을 훔친다 — edit(18)이 앞이다
      「그래픽」   render_3d 의 옛 라벨 「3D 그래픽」(103)을 훔친다
      「편집」     video(9)가 이미 갖고 있다. edit 이 넣어도 video 가 앞이라 무의미하다
                (그래서 라벨을 「편집·조판」이 아니라 **「디자인·조판」**으로 지었다 —
                 라벨 문자열이 엔진에 되먹여질 때 video 로 새면 격자가 통째로 끊긴다)
      「보정」 단독 video 색보정을 훔친다("색보정 작업" ⊃ "보정 작업") — 「후보정」·
                「사진 보정」·「이미지 보정」처럼 **앞말을 붙여서만** 넣는다
      「스튜디오」 dev 의 「안드로이드 스튜디오」(23) · music 의 「FL 스튜디오」(27)를 훔친다
      「촬영」 단독 video 쪽 문장을 훔칠 수 있다 — 「사진 촬영」·「스냅 촬영」으로 좁힌다
      「합성」 단독 "영상 합성"을 훔친다 — 「사진 합성」·「이미지 합성」·「4K 합성」·
                「포토샵 합성」으로 좁힌다
      「웨딩」 단독 "웨딩 영상"을 훔친다 — 「웨딩 사진」·「웨딩 스냅」으로 좁힌다
      「UI」 단독  영문 대문자 부분일치 사고가 나기 쉽다 — 「UI 디자인」·「UI 작업」·「UX」로 좁힌다
  ⚠ **다른 용도가 design 을 훔치는 쪽도 검사했다**(양방향). 하나 남아 있고, 이것은
    **분할 이전부터 있던 것이라 고치지 않는다**(내 담당 밖 행이다):
      video 의 「편집」(sort 9)이 「사진 편집」·「편집디자인」을 부분일치로 먼저 잡는다.
      실측으로 분할 전에도 "사진 편집" -> video 였다(0107 상태 재현 대조 확인).
      즉 **이 분할이 만든 회귀가 아니다.** video 의 낱말 행은 이 작업의 소유가
      아니므로 건드리지 않았다 — 담당자에게 남긴다.
      ⇒ 대신 photo 가 「사진 보정」·「사진 작업」·「후보정」·「사진」을 갖고 있어
        같은 고객의 다른 표현은 전부 잡힌다(검증표 참조).

■ usage_alloc — **값을 짓지 않는다**(0102 와 같은 원칙)
  0086 의 design 표본("디자인 7 100%(n=14)" 계열)은 «나누기 전의 디자인 전체» 표본이라
  두 갈래 어느 쪽의 값도 아니다. 표본을 갈라 다시 잴 근거가 없으므로 design 2행을
  design_edit 으로 개명하고 **같은 값을** design_photo 에 복제한다. note 에 명시한다.

■ usage_tier_rules — design 4행을 개명 + 복제. **값을 새로 짓지 않는다**
  design 150만 GPU vram>=8 / 300만 RAM 32 / 300만 CPU 12코어 / 800만 RAM lte 64.
  ⚠ 편집이 «지금보다 비싸지지 않는다»를 구조로 보장하려면 편집 쪽 규칙이
    **바이트 단위로 같아야** 한다 — 그래서 개명이고, photo 는 그 복제다.
    (photo 의 150만 GPU vram>=8 은 하한과 같은 값이라 중복이지만, 지우면 «분할 전과
     같다»는 보장이 흐려진다. 중복은 무해하다 — 같은 값을 두 번 거를 뿐이다.)

■ 격자 — `grid_cells` 6칸을 개명하고 6칸을 신설한다 (사장님 "격자 재생성 하고")
  디자인 6칸(NB_L2·NB_L3·NB_L4 × 인텔·AMD)의 usage 를 「디자인·조판」으로 바꾸고,
  같은 예산대 구성으로 「사진·후보정」 6칸을 신설한다. **예산대를 새로 고르지 않는다** —
  갈래별 예산대를 다시 재려면 시장 표본이 필요한데 없다. 분할 전 구간을 그대로 상속한다.
  ⚠ `api/grid_public.py USAGE_TO_GRID` 에 **두 키를 반드시 추가**한다(0102 때 이걸
    빠뜨려 격자 카드가 0장이 될 뻔했다). 옛 리터럴 「디자인」 -> 「디자인·조판」 호환도 둔다.
  ⚠ `budget_min/max` 는 NULL 로 비운다 — 새 칸의 가격은 배치가 실측해 채운다.
    옛 6칸의 관측값도 비운다(라벨이 바뀌었으니 그 값은 다시 재야 한다).

Revision ID: 0108
Revises: 0107
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0108"
down_revision = "0107"
branch_labels = None
depends_on = None


EDIT_KEY, EDIT_LABEL = "design_edit", "디자인·조판"
PHOTO_KEY, PHOTO_LABEL = "design_photo", "사진·후보정"

OLD_LABEL = "디자인"          # grid_cells.usage 옛 리터럴

# ⚠ 전부 «특정 신호»만 — 모호어(디자인·포토샵·일러)를 넣으면 위 ★ 판정이 무너진다.
#   대소문자 양쪽 표기를 다 넣는다(match 가 대소문자를 구분한다).
PHOTO_TERMS = [
    # ── 자기호명 ──
    "사진관", "사진 스튜디오", "포토스튜디오", "포토 스튜디오", "포토그래퍼",
    "사진 촬영", "스냅 촬영", "웨딩 사진", "웨딩 스냅", "돌스냅",
    "프로필 사진", "인물 사진", "제품 사진", "상품 사진",
    "사진 보정", "이미지 보정", "인물 보정", "후보정", "리터칭", "리터치",
    "사진 편집", "사진 작업", "사진 현상",
    "사진",                       # ★ 이 갈래의 핵심 자기호명어 — 마지막에 둔다
    # ── 프로그램 ──
    "라이트룸", "라이트룸 클래식", "Lightroom", "lightroom", "LIGHTROOM", "LrC",
    "캡쳐원", "캡처원", "Capture One", "capture one", "CaptureOne", "captureone",
    "DxO", "dxo", "포토샵 합성", "포토샵 대용량",
    # ── 파일·작업 신호 ──
    # ⚠ 바 「RAW」 를 쓰지 않는다 — **「CorelDRAW」가 RAW 를 품는다**(전수 검사가 잡았다).
    #   photo(15)가 edit(18)보다 앞이라 "CorelDRAW 씁니다" 가 design_photo 로 샜다
    #   (실측). 그러면 코렐 쓰는 조판 고객이 쓰지도 않을 VRAM 8GB 하한을 받는다 —
    #   «싼 쪽으로» 원칙의 정반대 방향이라 더 나쁘다. 그래서 뒷말을 붙여서만 넣는다.
    "RAW 파일", "RAW 현상", "RAW 보정", "RAW 사진", "RAW 작업", "RAW 편집",
    "raw 파일", "raw 현상", "raw 보정", "raw 사진",
    "Raw 파일", "Raw 현상", "로우파일", "로우 파일",
    "사진 합성", "이미지 합성", "4K 합성", "누끼",
    "대용량 이미지", "고해상도 이미지", "고화소", "화소",
    "AI 노이즈", "디노이즈", "Denoise", "denoise", "노이즈 제거",
    "DSLR", "dslr", "미러리스", "고해상도 사진",
]

# ⚠ 모호어(「디자인」·「포토샵」·「일러」)는 **여기에만** 있다. photo 가 앞서므로
#   구체적 신호가 함께 나오면 photo 가 이긴다.
EDIT_TERMS = [
    # ── 프로그램(2D) ──
    "인디자인", "InDesign", "indesign", "INDESIGN",
    "일러스트레이터", "일러스트", "일러", "Illustrator", "illustrator", "ILLUSTRATOR",
    "피그마", "Figma", "figma", "FIGMA",
    "코렐드로우", "CorelDRAW", "coreldraw", "어피니티", "Affinity", "affinity",
    "캔바", "Canva", "canva",
    "포토샵", "포샵", "Photoshop", "photoshop", "PHOTOSHOP",   # ★ 싼 쪽에 둔다(위 판정)
    # ── 편집·조판 산출물 ──
    "명함", "전단", "전단지", "리플렛", "리플릿", "브로슈어", "팜플렛", "팜플릿",
    "포스터", "현수막", "배너", "카탈로그", "카달로그", "잡지", "사보", "도록",
    "조판", "편집디자인", "인쇄", "인쇄물", "출력물", "제본", "표지 디자인",
    "타이포", "폰트", "서체", "레이아웃",
    "로고", "로고 디자인", "CI 디자인", "BI 디자인", "CI·BI", "패키지 디자인", "굿즈",
    # ── 화면 디자인 ──
    "UI 디자인", "UI 작업", "UX", "ui 디자인", "웹디자인", "웹 디자인",
    "상세페이지", "상세 페이지", "썸네일", "배너 디자인",
    "2D 그래픽", "그래픽 디자인", "벡터", "일러스트레이션", "드로잉",
    # ── 모호어 — 마지막 보루 ──
    "디자인",
]

# (slot, field, op, value, label, detail_fmt)
PHOTO_RULES = [
    ("GPU", "vram_gb", "gte", 8, "사진 후보정 그래픽 메모리",
     "VRAM {v}GB — 라이트룸 공식 권장 {r}GB."
     " AI 노이즈 제거·렌즈 블러가 GPU 연산이라 VRAM 이 모자라면 그 기능이 돌지 않습니다"),
    ("RAM", "capacity_gb", "gte", 16, "사진 후보정 메모리",
     "{v}GB — 포토샵·라이트룸 공식 권장 {r}GB."
     " RAW 원본을 여러 장 한 번에 다루면 32GB 로 올립니다"),
    ("SSD", "capacity_gb", "gte", 500, "사진 후보정 저장 용량",
     "{v}GB (포토샵 공식 권장 설치 100GB — 스크래치 디스크 + RAW 원본 보관 기준)"),
]
EDIT_RULES = [
    # ⚠ 옛 design 값 그대로다 — 한 값도 바꾸지 않는다(위 ★ 참조).
    ("RAM", "capacity_gb", "gte", 16, "디자인 메모리",
     "{v}GB — 인디자인·일러스트레이터·포토샵 공식 권장 {r}GB."
     " 수백 페이지 문서·고해상도 링크 이미지를 다루면 32GB 로 올립니다"),
    ("SSD", "capacity_gb", "gte", 500, "디자인 저장 용량",
     "{v}GB (인쇄용 원고·링크 이미지·폰트 보관 기준)"),
]

PHOTO_ORDER = {"GPU": 15, "RAM": 16, "SSD": 17}    # design 이 쓰던 자리(앞)
EDIT_ORDER = {"RAM": 18, "SSD": 19}                # 비어 있던 자리(다음이 trading 21)

# 0104 가 남긴 design 의 상태(downgrade 복원용) — 실조회값 그대로
_DESIGN_LABEL = "디자인"
_DESIGN_TERMS = ["디자인", "포토샵", "포샵", "일러스트", "일러",
                 "인디자인", "라이트룸", "피그마"]
_DESIGN_RULES = {
    "RAM": ("capacity_gb", 16, "디자인 메모리", "{v}GB (기준 {r}GB 이상)", 15),
    "SSD": ("capacity_gb", 500, "디자인 저장 용량", "{v}GB (기준 {r}GB 이상)", 16),
}

_ALLOC_NOTE_SUFFIX = " [0108: 분할 전 «디자인» 표본 공용 — 갈래별 재측정 전까지 동일]"
_TIER_NOTE_SUFFIX = " [0108: 분할 전 «디자인» 규칙 그대로 — 편집이 비싸지지 않게 값을 바꾸지 않았다]"

# 신설 격자 칸 — 분할 전 design 의 예산대를 그대로 상속한다(새로 고르지 않는다)
_PHOTO_CELLS = [
    ("NB_L2", "인텔"), ("NB_L2", "AMD"),
    ("NB_L3", "인텔"), ("NB_L3", "AMD"),
    ("NB_L4", "인텔"), ("NB_L4", "AMD"),
]
_PHOTO_BAND_NOTE = {
    "NB_L2": "usage_floors design_photo 하한 VRAM 8GB·RAM 16GB·SSD 500GB 를 담는 최저 구간"
             " (라이트룸 공식 'AI 기능 풀가속에 전용 GPU 메모리 8GB').",
    "NB_L3": "usage_tier_rules design_photo budget_min=3,000,000 에서 RAM 32GB·CPU 12코어 겨냥"
             " — 분할 전 «디자인» 규칙 그대로.",
    "NB_L4": "분할 전 «디자인» NB_L4 구간을 그대로 상속. 갈래별 예산대 재설계는 시장 표본이"
             " 없어 하지 않았다(0108).",
}
_EDIT_BAND_NOTE_SUFFIX = " [0108: 분할 후 «디자인·조판» — 하한·겨냥·배분 모두 분할 전과 동일]"


_INS_FLOOR = sa.text(
    "INSERT INTO usage_floors (usage_key, usage_label, match_terms, slot,"
    " field, op, value, label, detail_fmt, sort_order)"
    " VALUES (:k, :ul, CAST(:t AS JSONB), :s, :f, :o, :v, :l, :d, :so)")


def upgrade() -> None:
    conn = op.get_bind()

    # ── ① design -> design_edit 개명 (floor_id 유지 · 값은 그대로) ─────────────
    edit_blob = json.dumps(EDIT_TERMS, ensure_ascii=False)
    for slot, field, oper, val, rlabel, fmt in EDIT_RULES:
        conn.execute(sa.text(
            "UPDATE usage_floors SET usage_key=:k, usage_label=:ul,"
            " match_terms=CAST(:t AS JSONB), field=:f, op=:o, value=:v,"
            " label=:l, detail_fmt=:d, sort_order=:so"
            " WHERE usage_key='design' AND slot=:s"),
            {"k": EDIT_KEY, "ul": EDIT_LABEL, "t": edit_blob, "f": field,
             "o": oper, "v": val, "l": rlabel, "d": fmt,
             "so": EDIT_ORDER[slot], "s": slot})

    # ── ② design_photo 신설 — 재실행 안전 ─────────────────────────────────────
    have = {r[0] for r in conn.execute(sa.text(
        "SELECT DISTINCT usage_key FROM usage_floors")).all()}
    if PHOTO_KEY not in have:
        photo_blob = json.dumps(PHOTO_TERMS, ensure_ascii=False)
        for slot, field, oper, val, rlabel, fmt in PHOTO_RULES:
            conn.execute(_INS_FLOOR, {
                "k": PHOTO_KEY, "ul": PHOTO_LABEL, "t": photo_blob, "s": slot,
                "f": field, "o": oper, "v": val, "l": rlabel, "d": fmt,
                "so": PHOTO_ORDER[slot]})

    # ── ③ usage_alloc — 개명 + 복제(값은 그대로) ──────────────────────────────
    conn.execute(sa.text(
        "UPDATE usage_alloc SET usage_key=:k,"
        " note = CASE WHEN note LIKE :mark THEN note"
        "             ELSE COALESCE(note, '') || :suf END"
        " WHERE usage_key='design'"),
        {"k": EDIT_KEY, "mark": "%0108:%", "suf": _ALLOC_NOTE_SUFFIX})
    exists = conn.execute(sa.text(
        "SELECT 1 FROM usage_alloc WHERE usage_key=:k LIMIT 1"),
        {"k": PHOTO_KEY}).first()
    if not exists:
        conn.execute(sa.text(
            "INSERT INTO usage_alloc (usage_key, slot, pct_min, pct_max, note,"
            " active, sort_order)"
            " SELECT :new, slot, pct_min, pct_max, note, active, sort_order + 30"
            " FROM usage_alloc WHERE usage_key=:old"),
            {"new": PHOTO_KEY, "old": EDIT_KEY})

    # ── ④ usage_tier_rules — 개명 + 복제(값은 그대로) ─────────────────────────
    conn.execute(sa.text(
        "UPDATE usage_tier_rules SET usage_key=:k,"
        " note = CASE WHEN note LIKE :mark THEN note"
        "             ELSE COALESCE(note, '') || :suf END"
        " WHERE usage_key='design'"),
        {"k": EDIT_KEY, "mark": "%0108:%", "suf": _TIER_NOTE_SUFFIX})
    exists = conn.execute(sa.text(
        "SELECT 1 FROM usage_tier_rules WHERE usage_key=:k LIMIT 1"),
        {"k": PHOTO_KEY}).first()
    if not exists:
        conn.execute(sa.text(
            "INSERT INTO usage_tier_rules (usage_key, budget_min, slot, field,"
            " op, value, label, active, note, sort_order)"
            " SELECT :new, budget_min, slot, field, op, value, label, active,"
            " note, sort_order + 30"
            " FROM usage_tier_rules WHERE usage_key=:old"),
            {"new": PHOTO_KEY, "old": EDIT_KEY})

    # ── ⑤ grid_cells — 6칸 개명 + 6칸 신설 ────────────────────────────────────
    conn.execute(sa.text(
        "UPDATE grid_cells SET usage=:new, budget_min=NULL, budget_max=NULL,"
        " band_note = CASE WHEN band_note LIKE :mark THEN band_note"
        "                  ELSE COALESCE(band_note, '') || :suf END"
        " WHERE usage=:old"),
        {"new": EDIT_LABEL, "old": OLD_LABEL, "mark": "%0108:%",
         "suf": _EDIT_BAND_NOTE_SUFFIX})
    have_photo = conn.execute(sa.text(
        "SELECT 1 FROM grid_cells WHERE usage=:u LIMIT 1"),
        {"u": PHOTO_LABEL}).first()
    if not have_photo:
        for band, plat in _PHOTO_CELLS:
            conn.execute(sa.text(
                "INSERT INTO grid_cells (usage, budget_band_key, game_grade,"
                " game_resolution, platform, budget_min, budget_max, band_note,"
                " intended_empty)"
                " VALUES (:u, :b, NULL, NULL, :p, NULL, NULL, :n, FALSE)"),
                {"u": PHOTO_LABEL, "b": band, "p": plat,
                 "n": _PHOTO_BAND_NOTE[band]})


def downgrade() -> None:
    conn = op.get_bind()

    conn.execute(sa.text("DELETE FROM grid_quotes WHERE cell_id IN"
                         " (SELECT cell_id FROM grid_cells WHERE usage=:u)"),
                 {"u": PHOTO_LABEL})
    conn.execute(sa.text("DELETE FROM grid_cells WHERE usage=:u"),
                 {"u": PHOTO_LABEL})
    conn.execute(sa.text(
        "UPDATE grid_cells SET usage=:old, budget_min=NULL, budget_max=NULL,"
        " band_note = replace(band_note, :suf, '') WHERE usage=:new"),
        {"old": OLD_LABEL, "new": EDIT_LABEL, "suf": _EDIT_BAND_NOTE_SUFFIX})

    conn.execute(sa.text("DELETE FROM usage_tier_rules WHERE usage_key=:k"),
                 {"k": PHOTO_KEY})
    conn.execute(sa.text(
        "UPDATE usage_tier_rules SET usage_key='design',"
        " note = replace(note, :suf, '') WHERE usage_key=:k"),
        {"k": EDIT_KEY, "suf": _TIER_NOTE_SUFFIX})

    conn.execute(sa.text("DELETE FROM usage_alloc WHERE usage_key=:k"),
                 {"k": PHOTO_KEY})
    conn.execute(sa.text(
        "UPDATE usage_alloc SET usage_key='design',"
        " note = replace(note, :suf, '') WHERE usage_key=:k"),
        {"k": EDIT_KEY, "suf": _ALLOC_NOTE_SUFFIX})

    conn.execute(sa.text("DELETE FROM usage_floors WHERE usage_key=:k"),
                 {"k": PHOTO_KEY})

    design_blob = json.dumps(_DESIGN_TERMS, ensure_ascii=False)
    for slot, (field, val, rlabel, fmt, so) in _DESIGN_RULES.items():
        conn.execute(sa.text(
            "UPDATE usage_floors SET usage_key='design', usage_label=:ul,"
            " match_terms=CAST(:t AS JSONB), field=:f, value=:v, label=:l,"
            " detail_fmt=:d, sort_order=:so WHERE usage_key=:k AND slot=:s"),
            {"ul": _DESIGN_LABEL, "t": design_blob, "f": field, "v": val,
             "l": rlabel, "d": fmt, "so": so, "k": EDIT_KEY, "s": slot})
