"""주변기기 필수 사양 해제 — 근거 없이 제안을 막고 있었다 (슬라이스 84).

발단: 필수인데 **어떤 규칙도 읽지 않는 사양 20건**을 정리하다가, 그중 11건이
주변기기(모니터 4 · 키보드 3 · 마우스 · 헤드셋 · 스피커 · 웹캠)임을 확인했다.

주변기기는 견적 8슬롯에 들어가지 않는다. 쓰이는 곳은 `v_companion_candidates`
(함께 쓰면 좋은 것 제안)뿐이고, 그 뷰도 `review_required_yn = false`를 요구한다.
그런데 제안을 그리는 `_companion()`은 **이미 NULL을 견디게 짜여 있다** —
"없는 값은 지어내지 않고 그 자리를 비운다"(슬라이스 52). 값이 없어도 제안에는
아무 문제가 없다는 뜻이다.

그런데도 필수로 걸려 있어서, 판정이 실제로 적용되면 이렇게 된다(실측):

    모니터  resolution   29/585  →  556개가 제안에서 빠진다
            panel       115/585  →  470개
    키보드   switch_type   1/198  →  197개
    마우스·헤드셋·스피커·웹캠 connection  거의 전부

지금 585개가 모두 제안 풀에 남아 있는 것은 **판정 원천이 둘로 갈려 있었기 때문**이다:
적재는 상수(주변기기 항목 없음)를, 검수·수정은 메타(주변기기 필수 있음)를 봤다.
그래서 모니터를 상세에서 한 번 고치면 그 순간 제안 풀에서 사라진다 — 운영자에게는
"고쳤더니 없어졌다"로만 보인다. 같은 슬라이스에서 원천을 메타로 통일했으므로,
이 정리를 함께 하지 않으면 다음 적재가 주변기기 제안을 통째로 비운다.

**코어 부품은 손대지 않는다.** 상수와 메타가 이미 정확히 같고(10종 전부 일치),
SSD form_factor·interface나 POWER form_factor처럼 "규칙은 아직 못 만들지만
조립에 실제로 필요한 값"은 사람이 판단할 몫이다.

Revision ID: 0024
Revises: 0023
"""
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

PERIPHERALS = ("MONITOR", "KEYBOARD", "MOUSE", "HEADSET", "SPEAKER", "WEBCAM")


def upgrade() -> None:
    # required_for에서 주변기기만 걷어낸다 — 같은 필드가 코어 부품에도 걸려 있을 수 있으므로
    # 배열을 통째로 비우지 않는다(지금은 겹치지 않지만, 나중에 겹치면 조용히 망가진다).
    op.execute("""
        UPDATE spec_field_defs
           SET required_for = COALESCE((
                 SELECT jsonb_agg(v) FROM jsonb_array_elements_text(required_for) AS v
                  WHERE v NOT IN ('MONITOR','KEYBOARD','MOUSE','HEADSET','SPEAKER','WEBCAM')
               ), '[]'::jsonb)
         WHERE required_for ?| array['MONITOR','KEYBOARD','MOUSE','HEADSET','SPEAKER','WEBCAM']
    """)


def downgrade() -> None:
    """되돌리면 그 부품들이 다시 검수 대기가 된다 — 값이 없으므로 제안에서 빠진다."""
    for f, pts in (("size_inch", ["MONITOR"]), ("resolution", ["MONITOR"]),
                   ("refresh_hz", ["MONITOR"]), ("panel", ["MONITOR"]),
                   ("switch_type", ["KEYBOARD"]), ("key_layout", ["KEYBOARD"]),
                   ("connection", ["KEYBOARD", "MOUSE", "HEADSET", "SPEAKER", "WEBCAM"])):
        vals = ",".join(f"'{p}'" for p in pts)
        op.execute(f"""
            UPDATE spec_field_defs
               SET required_for = required_for || jsonb_build_array({vals})
             WHERE field_key = '{f}'
        """)
