# -*- coding: utf-8 -*-
"""게임-칸 매핑 캐시 수리 — ① 죽은 FK 재지정 ② 변종(tier_variant)별 판정.

사장님 확정(2026-09-21): "사다리 밖 가벼운 게임은 «모든 게임 칸에서 돌아간다» 로
판정한다" + "가벼운 게임 처리까지 포함해 한 번에 다 한다".
조사 산출물: `game_matrix_gap.md`(86종 전수) — 이 파일은 그 보고의 ②·⑤ 를 고친다.

■ ① 두 매핑 표의 cell_id FK 가 «죽은 표»를 가리키고 있었다 (실측 2026-09-21)

  0075 는 `grid_cells.cell_id` 를 참조하도록 썼다. 그런데 0092 가 격자 축을
  갈아엎으면서 옛 표를 `grid_cells_legacy_v1` 로 **개명**했고, FK 는 이름이
  아니라 **oid** 를 따라가므로 조용히 옛 표를 계속 가리킨 채 남았다.

    pg_constraint 실측:
      game_cell_map_cell_id_fkey     FOREIGN KEY (cell_id) REFERENCES grid_cells_legacy_v1(cell_id)
      workload_cell_map_cell_id_fkey FOREIGN KEY (cell_id) REFERENCES grid_cells_legacy_v1(cell_id)

    grid_cells_legacy_v1 = 112칸 · grid_cells = 134칸.
    현재 격자의 칸 113~134(22칸) 는 옛 표에 없다.

  결과: 배치가 그 22칸을 넣으려는 순간 **ForeignKeyViolation 으로 죽는다**.
  실증(롤백 트랜잭션):
      INSERT INTO game_cell_map ... cell_id=134
      -> psycopg2.errors.ForeignKeyViolation: Key (cell_id)=(134) is not present
         in table "grid_cells_legacy_v1"

  조사 보고는 이 결함을 못 봤다 — 배치를 실행하지 않고 코드만 읽어 재현했기
  때문이다(보고 머리말이 그렇게 밝힌다). 보고가 예고한 "배치만 돌리면 5,174행"
  은 **이 FK 를 고치기 전에는 0행 + 예외**다. 그래서 «배치가 낡았다»(결함 ⓐ)의
  진짜 이유가 하나 더 있다: 어제 격자를 134칸으로 재생성한 뒤 배치를 돌렸다면
  터졌을 것이다.

  이 마이그레이션은 두 FK 를 **현재 표 `grid_cells`** 로 다시 건다.

■ ② 한 칸에 견적이 3벌인데 판정이 1벌뿐이었다 — PK 에 tier_variant 를 넣는다

  0092 이후 칸 하나가 (가성비·추천·고성능) 현재본을 갖는다(실측 134·134·120 =
  388행). 배치의 `_build_cell_index()` 는 `cell_index[cell_id] = ...` 로 **칸을
  키**로 써서 뒤에 읽힌 1벌이 앞의 2벌을 덮어썼다. 실측: **134칸 중 98칸에서
  변종끼리 GPU 칩셋이 다르다.**

    cell 97 (게임/QHD)  가성비 RTX 3050(21.9) · 추천 RTX 5060(43.4) · 고성능 RTX 5070 TI(76.2)

  어느 변종이 살아남는지는 `SELECT` 의 행 순서에 달려 있었다 — 순서 보장이 없다.
  같은 게임이 어제는 되고 오늘은 안 되는 상태였다.

  ★ 왜 «칸 대표값 고정»이 아니라 표 구조를 바꾸는가 (대안 검토)

    대안 ⓐ 칸 대표값을 «가장 낮은 GPU» 로 고정 — 검토했고 **버렸다**.
      장점: 스키마 무변경, "이 칸에서 확실히 돌아간다"가 보장된다.
      버린 이유: 우리가 실제로 **파는 것**은 칸이 아니라 견적 3벌이다. 가장
      낮은 변종으로 칸을 대표하면 cell 97 은 RTX 3050(21.9)으로 판정돼,
      **고성능 변종(RTX 5070 Ti)으로는 되는 게임이 그 칸에서 «불성립»으로
      보인다.** 실측 98칸이 이 왜곡을 받는다. 사장님이 보는 화면은
      「이 게임 되는 가장 싼 견적」을 묻는 자리인데(정의서 §④), 그 답이
      «실제로 파는 구성보다 비관적인 값»이 된다. 사실을 줄여서 말하는 쪽도
      지어내는 것과 같은 종류의 거짓이다.
    대안 ⓑ 칸 대표값을 «가장 높은 GPU» — 더 나쁘다. 고성능 변종만 되는 게임이
      «이 칸 되면 가성비도 된다»로 읽혀 **과잉 견적**을 만든다.
    대안 ⓒ **변종별로 판정한다** — 고른 쪽. 원천(견적 3벌)의 단위를 그대로
      쓴다. 화면이 칸 단위로 말하고 싶으면 **조회에서 접으면 된다** —
      접는 것은 되돌릴 수 있고, 미리 버린 것은 되살릴 수 없다.

  ★ 화면·API 가 깨지는가 — 먼저 확인했다
    `api/admin_game_matrix.py` 가 이 표를 읽는 자리는 넷이다.
      _meta()            count(*) / count(DISTINCT game_id)  -> 행수가 최대 3배로 는다
      _axes()            DISTINCT match_level                -> 영향 없음
      _games()           count(m.cell_id) AS mapped_cells    -> 칸 수가 아니라 행 수가 된다
      _selection_cells() map JOIN grid_cells                 -> 한 칸이 최대 3행으로 늘어난다
    넷 다 **같은 커밋에서 고친다**(이 표의 단위가 바뀌었으니 세는 쪽도 바뀐다).
    조회는 변종을 **칸 단위로 접어** 내려보내므로 템플릿이 그리는 모양은 그대로다
    — 표의 단위는 여전히 «칸»이고, «어느 변종에서 되는가»가 한 칸 안에 붙는다.

  PK 를 (game_id, cell_id) -> (game_id, cell_id, tier_variant) 로 넓힌다.
  기존 행은 **버린다** — 0075 머리 주석이 이 표를 «파생 캐시(원장 아님)»로
  명시했고, 사람이 손댈 컬럼이 애초에 없다(5컬럼 전부 배치 산출물). 배치가
  돌 때마다 TRUNCATE 후 재계산하는 표라 옛 행에 남길 사실이 없다.

■ 이 파일이 하지 않는 것
  - `grid_cells` · `grid_quotes` 는 건드리지 않는다(칸 134·견적 388은 정상이다).
  - `games` 의 사양 컬럼(rec_gpu 등)은 원천이라 손대지 않는다.
  - `gpu_ladder` 에 행을 더하지 않는다 — 점수 근거가 없는 값은 지어내지 않는다.

Revision ID: 0109
Revises: 0108
"""
import sqlalchemy as sa
from alembic import op

revision = "0109"
down_revision = "0108"
branch_labels = None
depends_on = None

_TABLES = (
    ("game_cell_map", "game_id", "pk_game_cell_map",
     "game_cell_map_cell_id_fkey"),
    ("workload_cell_map", "workload_id", "pk_workload_cell_map",
     "workload_cell_map_cell_id_fkey"),
)


def upgrade() -> None:
    for tbl, key_col, pk_name, fk_name in _TABLES:
        # 파생 캐시다 — 옛 행에 보존할 사실이 없다(0075 머리 주석).
        # 비우고 가야 tier_variant 를 NOT NULL 로 걸 수 있다(지어낸 변종을
        # 채워 넣지 않는다 — 옛 행이 어느 변종의 결과였는지 «알 수 없다»).
        op.execute(f"TRUNCATE TABLE {tbl}")

        # ① 죽은 FK 를 현재 표로 다시 건다.
        op.drop_constraint(fk_name, tbl, type_="foreignkey")
        op.create_foreign_key(fk_name, tbl, "grid_cells",
                              ["cell_id"], ["cell_id"])

        # ② 변종 축 신설 + PK 확장.
        op.add_column(tbl, sa.Column("tier_variant", sa.String(12),
                                     nullable=False))
        op.drop_constraint(pk_name, tbl, type_="primary")
        op.create_primary_key(pk_name, tbl,
                              [key_col, "cell_id", "tier_variant"])

    op.execute(
        "COMMENT ON COLUMN game_cell_map.tier_variant IS "
        "'판정 대상 견적 변종(grid_quotes.tier_variant — 가성비/추천/고성능). "
        "0092 이후 한 칸이 변종마다 다른 GPU 를 갖는다(실측 134칸 중 98칸). "
        "칸 단위로 판정하면 변종 2벌이 조용히 버려진다 — 0109 머리 주석 참조.'"
    )
    op.execute(
        "COMMENT ON COLUMN workload_cell_map.tier_variant IS "
        "'판정 대상 견적 변종 — game_cell_map.tier_variant 와 같은 이유(0109).'"
    )


def downgrade() -> None:
    for tbl, key_col, pk_name, fk_name in _TABLES:
        op.execute(f"TRUNCATE TABLE {tbl}")
        op.drop_constraint(pk_name, tbl, type_="primary")
        op.drop_column(tbl, "tier_variant")
        op.create_primary_key(pk_name, tbl, [key_col, "cell_id"])
        op.drop_constraint(fk_name, tbl, type_="foreignkey")
        op.create_foreign_key(fk_name, tbl, "grid_cells_legacy_v1",
                              ["cell_id"], ["cell_id"])
