"""admin2 화면 머리말 — 제목 · 쉬운 설명 · 같은 묶음 바로가기 · 작업 순서 (2026-10-11).

■ 왜 있는가
  2026-10-09 Codex 시안을 적용한 「사용·성능 자료」(usage_floors) 화면이 새 틀을 처음
  보였다 — 큰 제목, 설명 한 줄, 관련 화면 바로가기 카드, 「1 → 2 → 3」 작업 순서.
  나머지 화면은 시안이 따로 없어서, 같은 틀을 공통 셸(`_admin2_shell.html.j2`)이 그린다.
  화면 본문(표·서랍·버튼·API)은 건드리지 않는다 — 머리말만 위에 얹는다.

■ 단일 원천
  · 문구는 이 파일 한 곳에만 적는다(화면 템플릿에 다시 적지 않는다).
  · 바로가기 카드는 `admin_nav.NAV` 의 같은 그룹을 순회해서 만든다 — 메뉴 목록을 여기
    다시 적지 않는다(CANON §1 — 메뉴를 복제하면 한쪽만 낡는다).
  · 카드 한 줄 설명은 이 파일의 `short` 를 쓴다(없으면 카드에 이름만).

■ 그리지 않는 화면
  · 이 표에 없는 경로 — 화면이 이미 자기 제목(h1)을 갖고 있는 새 틀 화면들
    (공급처·웹 사양 채움·상품 등록·상품 분류 관리·처리할 일·조립PC 제품군·부품 설명 관리·
    추천 테스트·용도별 최소 사양 등). 거기 또 얹으면 제목이 두 번 나온다.
  · 신 관리자 모드(`new_admin`) — 그 모드는 자기 메뉴와 자기 제목을 쓴다.

■ 문구 규칙(코디네이터 결정 2026-10-10)
  짧은 문장 · 어려운 말·영어·경로 최소 · 「PC 구성」→「PC/컴퓨터」 · 「승인·발행」→
  「고객에게 공개」 · 「review_issues」→「검수 메모」. 1차 문구이고 코덱스(#66)가 다듬는다.
"""
from __future__ import annotations

from .admin_nav import NAV

# path -> {title, desc, short, steps?}
#   title  화면 제목(큰 글씨). 메뉴 이름과 같게 둔다 — 메뉴와 제목이 다르면 사람이 헷갈린다.
#   desc   제목 아래 한두 문장. 이 화면에서 무엇을 하는지.
#   short  바로가기 카드의 한 줄 설명.
#   steps  (선택) 작업 순서 — 순서가 정해진 쓰기 화면만.
#   note   (선택) 순서 옆 한 줄 안내.
INTRO: dict[str, dict] = {
    # ── 대시보드 ──
    "/admin2/": {
        "title": "대시보드",
        "desc": "오늘 처리할 일과 주요 숫자를 한눈에 봅니다. 카드를 누르면 그 일을 하는 화면으로 갑니다.",
        "short": "오늘 할 일과 주요 숫자",
    },

    # ── 상품관리 ──
    "/admin2/products": {
        "title": "상품 관리",
        "desc": "상품을 찾고, 상세를 보고, 고칩니다. 상품 작업은 모두 여기서 시작합니다.",
        "short": "상품 찾기·보기·고치기",
        "steps": ["상품 찾기", "상세 보기", "수정·저장"],
        "note": "상품 이름을 누르면 보기만 하고, 「수정」을 눌러야 고칠 수 있습니다.",
    },
    "/admin2/categories-v2": {"short": "판매 분류 나무 관리"},
    "/admin2/part-explanations": {"short": "부품 설명 검토"},
    "/admin2/customer-bom-gaps": {"short": "고객 화면 빈칸 · 운영자 확인"},
    "/admin2/pc-workspace": {"short": "제품별 할 일과 AI 제안"},
    "/admin2/pc-configurations": {"short": "조립PC 목록과 부품"},
    "/admin2/configuration-consultation": {"short": "추천 결과 미리 시험"},
    "/admin2/product-new": {"short": "새 상품 한 개 등록"},
    "/admin2/category-mapping": {
        "title": "상품 분류 매핑",
        "desc": "분류가 없거나 잘못 붙은 상품을 찾아 바른 분류로 옮깁니다. 추천에 쓰일 분류를 확인하는 작업입니다.",
        "short": "분류 빠진 상품 바로잡기",
        "steps": ["문제 상품 고르기", "분류 고르기", "옮기기"],
    },
    "/admin2/catalog-import": {
        "title": "상품 일괄 등록",
        "desc": "상품 파일을 올려 여러 상품을 한 번에 등록하거나 고칩니다. 적용 전에 무엇이 바뀌는지 먼저 보여 줍니다.",
        "short": "파일로 여러 상품 등록",
        "steps": ["파일 올리기", "바뀌는 내용 확인", "적용"],
        "note": "이 화면에는 적용을 되돌리는 기능이 없습니다. 적용 전에 바뀌는 내용을 꼭 확인해 주세요.",
    },
    "/admin2/product-fit": {
        "title": "판매 상품 용도 매트릭스",
        "desc": "지금 팔고 있는 조립PC가 어떤 용도와 가격대에 맞는지 표로 봅니다. 보기 전용입니다.",
        "short": "판매 PC의 용도별 적합도",
    },
    "/admin2/grid": {
        "title": "상품 매트릭스 관리",
        "desc": "용도와 예산 칸마다 미리 만들어 둔 추천 PC를 봅니다. 보기 전용입니다.",
        "short": "용도·예산 칸별 추천 PC",
    },
    "/admin2/game-matrix": {
        "title": "용도별 상품 매트릭스",
        "desc": "게임이나 AI 작업마다 어떤 칸의 PC가 맞는지 봅니다. 보기 전용입니다.",
        "short": "게임·AI 작업별 맞는 칸",
    },
    "/admin2/deleted-products": {
        "title": "삭제 상품 조회",
        "desc": "삭제 대기·단종 상품과 처리 이유를 봅니다. 되돌릴 때 복원되는 내용을 확인해 주세요. 완전 삭제한 상품은 되살릴 수 없습니다.",
        "short": "삭제 대기·단종 상품 확인",
    },

    # ── 상품사양관리 ──
    "/admin2/build-map": {
        "title": "조립 호환 지도",
        "desc": "어떤 부품끼리 맞는지 판단할 때 필요한 사양을 한 장에 봅니다. 아직 모르는 사양도 함께 보입니다.",
        "short": "부품 호환 판단에 필요한 사양",
    },
    "/admin2/spec-standard": {
        "title": "조립 사양 표준",
        "desc": "부품 종류마다 꼭 있어야 할 사양 항목을 정합니다. 빠진 항목이 위에 먼저 보입니다.",
        "short": "부품 종류별 필요한 사양",
    },
    "/admin2/spec-field-defs": {
        "title": "상품 사양 정의",
        "desc": "새 사양 항목을 만들고, 적용할 부품 종류를 정합니다. 기존 항목의 이름을 바꾸거나 항목을 지우는 기능은 없습니다.",
        "short": "사양 항목 추가·적용 부품 설정",
        "steps": ["항목 확인", "새 항목 입력", "추가"],
    },
    "/admin2/reviews": {
        "title": "상품 사양 검수",
        "desc": "자동으로 찾은 사양 값을 사람이 확인해 반영하거나 돌려보냅니다. 근거를 보고 결정합니다.",
        "short": "찾아온 사양 값 확인",
        "steps": ["대기 항목 고르기", "근거 확인", "반영 또는 반려"],
    },
    "/admin2/compat-rules": {
        "title": "조립 호환 규칙",
        "desc": "부품끼리 맞는지 판단하는 규칙과 검사 결과를 봅니다. 파워는 조립 판정 기준과 고객 안내 기준을 나눠 보여 줍니다. 규칙을 저장하는 기능은 아직 준비 중입니다.",
        "short": "부품 궁합 규칙",
    },
    "/admin2/usage-floors": {"short": "용도별 최소 사양"},
    "/admin2/part-grade": {
        "title": "부품 등급 관리",
        "desc": "CPU·그래픽카드 같은 부품에 성능 등급을 매깁니다. 추천에 연결됐는지는 화면 안내에서 확인해 주세요.",
        "short": "부품 성능 등급 매기기",
    },
    "/admin2/policy-weights": {
        "title": "추천 기준 보기",
        "desc": "알뜰·추천·고성능 구성이 각각 무엇을 기준으로 골라지는지 봅니다. 보기 전용입니다.",
        "short": "추천 구성 고르는 기준",
    },
    "/admin2/candidate-pool": {
        "title": "추천 가능 재고 현황",
        "desc": "지금 추천에 쓸 수 있는 부품이 종류별로 몇 개인지 봅니다. 빠진 이유도 함께 보입니다.",
        "short": "추천에 쓸 수 있는 부품 수",
    },
    "/admin2/consult-sessions": {
        "title": "견적 상담 기록",
        "desc": "고객이 상담에서 무엇을 묻고 어떤 PC를 받았는지 봅니다. 보기 전용입니다.",
        "short": "고객 상담 내용",
    },
    "/admin2/mvp3-consults": {
        "title": "고객 문의 · 보관 견적",
        "desc": "지금 고객 화면에서 들어온 문의와 고객이 보관한 견적을 방문자별로 봅니다. 줄을 누르면 언제 무엇을 묻고 어떤 PC를 보관했는지 나옵니다. 보기 전용입니다.",
        "short": "고객 화면 문의와 보관 견적",
    },
    "/admin2/swap-click-logs": {
        "title": "부품 교체 · 클릭 기록",
        "desc": "고객이 추천 PC에서 어떤 부품을 바꾸고 무엇을 눌렀는지 봅니다. 추천이 맞았는지 살피는 자료입니다.",
        "short": "고객이 바꾼 부품",
    },

    # ── 매입 · 소싱 ──
    "/admin2/suppliers": {"short": "공급처 정보"},
    "/admin2/sourcing": {
        "title": "매입 견적(용산)",
        "desc": "재고가 없거나 모자란 상품의 공급처 가격을 비교하고 매입가를 정합니다. 가격을 확정해도 주문하거나 재고를 늘리지는 않습니다.",
        "short": "공급처 가격 비교·가격 확정",
        "steps": ["상품 고르기", "공급처 가격 비교", "매입가 확정"],
    },
    "/admin2/price-import": {
        "title": "단가표 반영",
        "desc": "공급처가 보낸 가격표를 올려 매입가를 한 번에 바꿉니다. 바뀌는 가격을 먼저 보여 줍니다.",
        "short": "공급처 가격표 올리기",
        "steps": ["가격표 올리기", "바뀌는 가격 확인", "반영"],
    },
    "/admin2/stock-inbound": {
        "title": "재고 입고",
        "desc": "들어온 물건의 수량을 넣어 재고를 늘립니다. 입고 기록은 지워지지 않고 남습니다.",
        "short": "들어온 물건 수량 넣기",
        "steps": ["상품 고르기", "수량 넣기", "입고 확정"],
    },

    # ── 판매가 ──
    "/admin2/sale-price": {
        "title": "판매가 관리",
        "desc": "상품의 판매가를 보고 고칩니다. 판매가가 왜 이렇게 정해졌는지 근거도 함께 봅니다.",
        "short": "판매가 보기·고치기",
    },
    "/admin2/price-review": {
        "title": "가격 검토 대기",
        "desc": "판매가가 아직 없는 상품의 첫 판매가를 정합니다. 제안 가격을 받아들이거나 직접 넣습니다.",
        "short": "첫 판매가 정하기",
        "steps": ["상품 고르기", "제안 가격 확인", "확정"],
    },
    "/admin2/margin-policy": {
        "title": "마진 정책",
        "desc": "카드 수수료와 마진 비율을 정합니다. 여기서 바꾼 값은 판매가 재산정 때 쓰입니다.",
        "short": "수수료·마진 비율",
    },
    "/admin2/price-history": {
        "title": "가격 이력",
        "desc": "상품 가격이 언제, 왜 바뀌었는지 기록을 봅니다. 여기서는 가격을 고치지 않습니다.",
        "short": "가격이 바뀐 기록",
    },
    "/admin2/mall-price": {
        "title": "쇼핑몰 가격 반영",
        "desc": "쇼핑몰 판매가를 고객 카드 판매가에 반영합니다. 바뀌는 가격을 먼저 보여 주고, 실행 단위로 되돌릴 수 있습니다.",
        "short": "쇼핑몰 가격 반영",
        "steps": ["파일 올리기", "바뀌는 가격 확인", "반영"],
    },
    "/admin2/reprice": {
        "title": "판매가 재산정",
        "desc": "바뀐 매입가와 마진 정책으로 판매가를 다시 계산합니다. 실행 전에 바뀌는 상품을 먼저 보여 줍니다.",
        "short": "판매가 다시 계산",
        "steps": ["범위 고르기", "미리 보기", "실행"],
    },

    # ── 인계 · 성과 ──
    "/admin2/mall-sync": {
        "title": "쇼핑몰 동기화",
        "desc": "인계 시점에 확인한 쇼핑몰 가격과 우리 가격을 비교합니다. 전체 상품을 동기화하는 기능은 아직 준비 중이며, 이 화면에서는 값을 고치지 않습니다.",
        "short": "인계 때 확인한 쇼핑몰 가격 비교",
    },
    "/admin2/handoff-log": {
        "title": "인계 기록",
        "desc": "쇼핑몰 인계 기록과 당시 견적을 봅니다. 이 기록으로 장바구니에 상품이 담겼거나 구매가 끝났는지는 알 수 없습니다.",
        "short": "쇼핑몰로 넘긴 기록",
    },
    "/admin2/funnel-performance": {
        "title": "유입 성과",
        "desc": "상담 시작·완료·쇼핑몰 인계까지의 흐름을 봅니다. 숫자마다 세는 기준이 다르니 옆의 기준 설명을 함께 봅니다. 인계 링크 클릭과 구매 결과는 아직 집계하지 않습니다.",
        "short": "상담 시작·완료·쇼핑몰 인계 흐름",
    },
    "/admin2/retention": {
        "title": "보관 기한 · 파기 이력",
        "desc": "고객 개인정보가 보관 기한까지 얼마나 남았는지와 파기 작업이 실제로 무엇을 지웠는지를 나눠 봅니다. 기한이 지나면 화면에서 가리지만, 값을 지웠는지는 실행 기록으로 따로 확인합니다. 보기 전용입니다.",
        "short": "개인정보 보관 기한과 파기 기록",
    },
    "/admin2/purchase-inquiries": {
        "title": "구매 상담 신청",
        "desc": "고객이 상담 화면에서 남긴 여러 대 구매 · 할인 · 세금계산서 · 주문 희망 신청을 봅니다. 연락처를 보고 고객에게 연락한 뒤 처리 상태와 메모를 남깁니다. 신청은 보관 기한이 지나면 지울 대상이 됩니다.",
        "short": "고객 구매 상담 신청 처리",
        "steps": ["대기 신청 고르기", "고객에게 연락", "처리 상태 · 메모 저장"],
    },

    # ── AI 관리 ──
    "/admin2/dash": {
        "title": "작업 현황판",
        "desc": "AI와 작업팀의 작업 상태를 보고 요청 메시지를 남깁니다. 메시지가 실제로 전달됐는지는 화면 안내와 상태를 확인해 주세요.",
        "short": "지금 하고 있는 일",
    },
    "/admin2/spec-fill": {"short": "웹에서 사양 찾아 채우기"},
    "/admin2/talk-review": {
        "title": "AI 답 점검",
        "desc": "고객 문의마다 AI가 낸 말과 고객이 실제로 본 말을 봅니다. 「해 드릴게요」「확인했습니다」 같은 약속하는 말이 붙은 답을 골라 문제 있음 · 확인으로 표시하고 메모를 남깁니다. 같은 질문에 나간 답도 나란히 봅니다. AI에게는 부품 하나하나의 가격을 보내지 않습니다. 답에 금액이 나왔다는 것만으로는 점검 후보이고 위반으로 확정하지 않습니다 — PC 총액과 확인된 가격 차이와 맞는지 대조합니다.",
        "short": "AI 답 확인 · 문제 표시",
        "steps": ["약속하는 말이 붙은 답 고르기", "같은 질문의 답 비교", "문제 있음 · 확인 저장"],
    },
    "/admin2/shop-notices": {
        "title": "판매 안내 자료",
        "desc": "고객이 상담 화면에서 윈도우 설치·배송·A/S·결제·할인·여러 대 구매·모니터 포함을 물으면 AI 대신 여기 적힌 안내가 나갑니다. 비워 두면 「상품마다 달라 쇼핑몰에서 확인」 같은 기본 안내가 나갑니다.",
        "short": "고객 AI가 답할 가게 안내",
    },
    "/admin2/talk-patterns": {
        "title": "팝콘톡 응답 패턴",
        "desc": "고객 질문을 모아 어떤 답을 할지 묶어 둡니다. 묶은 답은 상담에서 다시 씁니다.",
        "short": "질문과 답 묶기",
    },
    "/admin2/game-grades": {
        "title": "게임 사양 등급",
        "desc": "고객이 게임 이름을 말하면 그 게임의 사양 등급으로 견적의 사양 하한을 정합니다. 여기서 게임마다 등급을 바꾸고, 해상도별로 어느 사양 단계가 되는지 함께 봅니다. 바꿀 때는 이유를 적고, 잘못 바꿨으면 기록에서 되돌립니다. 저장은 대표 권한만 할 수 있습니다.",
        "short": "게임별 사양 등급 고치기",
        "steps": ["게임 찾기", "등급과 이유 적기", "저장 · 필요하면 되돌리기"],
    },
    "/admin2/game-copy-review": {
        "title": "게임 견적 근거 검수",
        "desc": "게임마다 고객에게 보여 줄 설명을 읽고 내보내도 되는지 정합니다.",
        "short": "게임 설명 확인",
        "steps": ["게임 고르기", "설명 읽기", "승인 또는 반려"],
    },
    "/admin2/ai-task-settings": {
        "title": "AI 작업 설정",
        "desc": "작업마다 쓸 AI와 실패했을 때 대신 쓸 AI를 정합니다. 저장한 설정은 현재 AI 실행에는 적용되지 않습니다.",
        "short": "작업별 AI 고르기",
    },
    "/admin2/ai-integration": {
        "title": "AI 연동 설정",
        "desc": "서버의 AI 키 등록 여부와 사용 한도를 확인합니다. AI 업체에 요청해 연결을 시험하지는 않으며, 키 값은 화면에 나오지 않습니다.",
        "short": "AI 키 등록 여부와 사용 한도",
    },
    "/admin2/ai-usage-cost": {
        "title": "AI 사용량 · 비용",
        "desc": "AI를 얼마나 쓰고 비용이 얼마나 나왔는지 봅니다. 보기 전용입니다.",
        "short": "AI 사용량과 비용",
    },
    "/admin2/ai-response-log": {
        "title": "AI 응답 기록",
        "desc": "AI가 무엇을 받고 어떻게 답했는지 봅니다. 근거 없는 답이 나갔는지 확인하는 자리입니다.",
        "short": "AI가 한 답 보기",
    },
    "/admin2/ops-assistant": {
        "title": "운영 도우미 설정",
        "desc": "관리자 화면 도우미가 보여 줄 자주 묻는 질문과 바로가기를 정합니다.",
        "short": "화면 도우미 내용",
    },

    # ── 시스템 ──
    "/admin2/ops-settings": {
        "title": "오픈 단계 설정",
        "desc": "주문·결제 같은 기능을 우리 시스템에서 할지, 쇼핑몰에서 할지 정합니다. 바꾸면 고객 화면이 바로 바뀝니다.",
        "short": "기능별 운영 방식",
    },
    "/admin2/operators": {
        "title": "운영자 · 권한",
        "desc": "누가 어떤 등급인지 보고, 가입 신청을 받거나 등급을 바꿉니다.",
        "short": "운영자와 등급",
        "steps": ["사람 고르기", "등급 고르기", "저장"],
    },
    "/admin2/activity-logs": {
        "title": "작업 기록",
        "desc": "관리자 화면에서 누가 언제 무엇을 바꿨는지 봅니다. 되돌린 작업도 함께 보입니다.",
        "short": "누가 무엇을 바꿨나",
    },
    "/admin2/excel-exports": {
        "title": "엑셀 다운로드 관리",
        "desc": "엑셀로 내려받을 자료를 모아 두는 화면입니다. 내려받기 기능은 아직 준비 중입니다.",
        "short": "엑셀 내려받기",
    },
    "/admin2/requests": {
        "title": "요청 · 승인",
        "desc": "작업 요청을 올리고, 승인이 필요한 요청을 처리합니다. 상태별로 나눠 보입니다.",
        "short": "작업 요청과 승인",
        "steps": ["요청 올리기", "검토", "승인 또는 반려"],
    },

    # ── 메뉴 밖 화면 ──
    "/admin2/my-profile": {
        "title": "내 정보",
        "desc": "내 이름·연락처와 비밀번호를 바꾸고, 로그인한 기기를 확인합니다.",
    },
}

# 머리말 제목을 그리지 않는(이미 자기 h1 을 가진) 화면. 위 표에 short 만 둔 항목이 이것이다.
# 이 표는 그 판정을 «title 유무»로 대신한다 — 따로 목록을 두면 둘이 갈라진다.


def _norm(path: str) -> str:
    p = (path or "").split("?")[0]
    if p in ("/admin2", "/admin2/"):
        return "/admin2/"
    return p.rstrip("/")


def intro_for(path: str) -> dict | None:
    """그 경로의 머리말. 제목이 없는 경로(자기 제목을 가진 화면·표에 없는 화면)는 None."""
    key = _norm(path)
    meta = INTRO.get(key)
    if not meta or not meta.get("title"):
        return None
    links: list[dict] = []
    group_title = None
    for title, _icon, items in NAV:
        hrefs = [_norm(h) for _l, h, _n in items if h]
        if key in hrefs:
            group_title = title
            for label, href, _note in items:
                if not href:
                    continue
                k = _norm(href)
                links.append({
                    "label": label, "href": href,
                    "short": (INTRO.get(k) or {}).get("short", ""),
                    "current": k == key,
                })
            break
    if len(links) < 2:  # 혼자인 그룹(대시보드)·메뉴 밖 화면은 바로가기 없이 제목만
        links = []
    return {
        "title": meta["title"],
        "desc": meta.get("desc", ""),
        "steps": meta.get("steps") or [],
        "note": meta.get("note", ""),
        "group": group_title,
        "links": links,
    }


# ── 돌아가기 줄 (2026-10-11 사장님 신고) ─────────────────────────────────────
# 「사용·성능 자료」 화면 위쪽 카드를 누르면 다른 화면으로 가는데, 그 화면에는 원래
# 화면으로 돌아오는 길이 없었다(신 관리자 모드는 머리말을 안 그리고, 구 관리자 모드의
# 머리말은 다른 메뉴 묶음(「AI 관리」 등)의 카드를 보여 준다). 화면 배치 통일은 별도
# 설계를 기다리고, 여기서는 «돌아가는 링크 한 줄»만 셸이 그린다.
#   key   카드가 모여 있는 화면(돌아갈 곳)
#   label 돌아가기 링크 문구 — 이름은 신 관리자 좌측 메뉴 이름과 같게 둔다
#   group 신 관리자 헤더 경로에 쓸 묶음 이름 — 신 관리자 좌측 메뉴 이름과 같다
#   from  그 화면의 카드·같은 메뉴 묶음으로 들어오는 화면들
BACK_LINKS: dict[str, dict] = {
    "/admin2/usage-floors": {
        "label": "사용·성능 자료로 돌아가기",
        "group": "사용·성능 자료",
        "from": ("/admin2/game-copy-review", "/admin2/game-grades", "/admin2/talk-patterns",
                 "/admin2/shop-notices", "/admin2/talk-review", "/admin2/product-fit"),
    },
    # 구 관리자에서 옮긴 「후기 관리」(2026-10-11 사장님 결정). 회원 관리 화면에는 카드가
    # 없으므로 그 화면에 들어가는 링크(`entries`)를 셸이 그린다. 묶음 첫 화면의 경로는
    # 「회원 관리 › 회원 관리」가 되어 겹치므로 그리지 않는다(`crumb_on_hub`).
    "/admin2/members": {
        "label": "회원 관리로 돌아가기",
        "group": "회원 관리",
        "from": ("/admin2/member-reviews",),
        "entries": (("후기 관리", "/admin2/member-reviews"),),
        "crumb_on_hub": False,
    },
    # 결제·정산 기록장(2026-10-11 사장님 「기록장」 확정). 주문 운영 화면에 들어가는 링크를 둔다.
    "/admin2/commerce-orders": {
        "label": "주문 운영으로 돌아가기",
        "group": "주문 운영",
        "from": ("/admin2/payment-records",),
        "entries": (("결제·정산 기록", "/admin2/payment-records"),),
        "crumb_on_hub": False,
    },
}


def back_for(path: str) -> dict | None:
    """그 경로에서 돌아갈 화면 — 없으면 None. {href, label}."""
    key = _norm(path)
    for href, meta in BACK_LINKS.items():
        if key in meta["from"]:
            return {"href": href, "label": meta["label"]}
    return None


def group_crumb(path: str) -> dict | None:
    """신 관리자 헤더 경로의 묶음 칸 — 「사용·성능 자료 › 현재 화면」(코덱스 설계 2026-10-11).

    묶음 안 화면들의 헤더 경로가 구 메뉴 이름(상품사양관리·AI 관리·상품관리)으로 흩어져
    있던 것을 신 관리자 좌측 메뉴 이름 하나로 맞춘다. {href, label}. 묶음 밖이면 None.
    구 관리자 모드는 구 메뉴 묶음을 그대로 쓴다(그쪽 왼쪽 메뉴와 맞아야 하므로).
    """
    key = _norm(path)
    for href, meta in BACK_LINKS.items():
        on_hub = key == _norm(href) and meta.get("crumb_on_hub", True)
        if on_hub or key in meta["from"]:
            return {"href": href, "label": meta["group"]}
    return None


def entries_for(path: str) -> list[dict]:
    """묶음 첫 화면에서 카드 없이 들어갈 화면들 — [{href, label}]. 없으면 빈 목록."""
    key = _norm(path)
    for href, meta in BACK_LINKS.items():
        if key == _norm(href):
            return [{"label": label, "href": h} for label, h in meta.get("entries", ())]
    return []
