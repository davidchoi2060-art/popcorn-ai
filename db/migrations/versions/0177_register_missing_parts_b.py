"""0177 — 판매 PC 구성 부품 중 부품 설명이 없던 것 등록 · 설명 승인 · 사진 승인 2차분 (2026-10-21 남은 10개 중 몰 상세 페이지로 채울 수 있는 5개).

실제 일은 tools/register_missing_parts.run_safely("apply", "b") 가 한다 — 데이터 db/migrations/data/missing_parts_20261021b.json.
상품 행 3개 신설(127201·127203·130506, ai_candidate_yn 기본 false 라 추천 후보 밖) · 122413 상품명 기준 사양 보충 · 119448 gif 사진.
연습 실행: 5개 모두 성공. 내장 그래픽·기본 쿨러 5개는 몰에도 사양이 없는 0원 표시용이라 뺐다.
결과는 .cache/missing-parts/report-applyb.json(러너 report batch=b 로 읽는다).
"""
import sys
from pathlib import Path

revision = "0177"
down_revision = "0176"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from tools.register_missing_parts import run_safely   # noqa: E402
    report = run_safely("apply", "b")
    print('[0177] missing parts apply b', (report or {}).get('summary'), (report or {}).get('fatal'))


def downgrade() -> None:
    # 승인은 이벤트 원장이라 지우지 않는다 — 되돌리려면 관리자 부품 설명 화면에서 승인 철회.
    pass
