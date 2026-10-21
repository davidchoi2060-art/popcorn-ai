"""(0176 — 0173 은 서버에서 번호가 겹쳐 «이미 적용»으로 건너뛰어졌다. 같은 일을 다시 부른다.
이미 바뀐 구성은 쿨러가 121846 이라 그 구성만 실패로 건너뛴다 — 두 번 바꾸지 않는다.)

기존 승인 25개 쿨러 교체·새 사진·재승인 실제 반영 (2026-10-21 사장님 「허락..」).

스키마 변경 없음 — 데이터만 바꾼다. 일은 tools/remake25_cooler.run_safely('apply') 가 하고,
상품(구성)마다 자기 트랜잭션에서 «쿨러 줄·몰 원문·검토 승인·새 사진·공개 승인»을 한 번에 커밋한다.
그래서 고객 화면에는 «옛 승인 그대로» 아니면 «새 승인» 둘 중 하나만 보인다(사이 공백 없음).
실패한 구성은 그 구성만 되돌아가 옛 승인이 그대로 남고, 결과는 .cache/remake25/report-apply.json.
배포를 멈추지 않도록 예외를 올리지 않는다.
"""
import sys
from pathlib import Path

revision = "0176"
down_revision = "0175"
branch_labels = None
depends_on = None


def upgrade():
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from tools.remake25_cooler import run_safely   # noqa: E402
    report = run_safely('apply')
    print('[0176] remake25 apply', (report or {}).get('summary'))


def downgrade():
    # 되돌림은 역방향 승인 이력으로 한다(원장 규약) — 마이그레이션 downgrade 로 지우지 않는다.
    pass
