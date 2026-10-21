"""0175 — 판매 PC 구성 부품 중 부품 설명이 없던 것 등록 · 설명 승인 · 사진 승인 (2026-10-21 사장님 「신규 부품 추가된거 확인하고 넣으라고 했잖아」).

실제 일은 tools/register_missing_parts.run_safely('apply') 가 한다(부품마다 한 트랜잭션 · 실패한 부품만 되돌림 ·
예외를 올리지 않아 배포를 멈추지 않는다). 2026-10-21 연습 실행: 105종 등록 가능 · 품절 42 · 상품 행 없음 8 · 사진/사양 없음 2.
결과는 .cache/missing-parts/report-apply.json(러너 «빠진 부품 등록 점검» report 로 읽는다).
"""
import sys
from pathlib import Path

revision = "0175"
down_revision = "0174"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from tools.register_missing_parts import run_safely   # noqa: E402
    report = run_safely('apply')
    print('[0175] missing parts apply', (report or {}).get('summary'), (report or {}).get('fatal'))


def downgrade() -> None:
    # 승인은 이벤트 원장이라 지우지 않는다 — 되돌리려면 관리자 부품 설명 화면에서 승인 철회.
    pass
