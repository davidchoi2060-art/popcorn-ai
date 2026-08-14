# -*- coding: utf-8 -*-
"""ai_task_assignments — AI 작업 종류 <-> 프로바이더 배정 (ADM-AI-030, A-35).

■ 왜 필요한가
  AI 작업 설정 화면(`/admin2/ai-task-settings`)이 "어느 작업에 어느 모델을 쓰고, 실패하면
  무엇으로 대체하는지"를 저장할 테이블이 없었다(실측: api_cost_logs·cost_thresholds·
  rate_limit_policies·ops_settings_history 어디에도 이 배정을 담는 컬럼이 없다 —
  docs/design/req/req-ai-task-settings.md ④, 조사자 데이터맵 2026-08-13). 이 마이그레이션이
  그 배정의 **현재값**을 담는 테이블 하나를 신설한다.

■ 변경 이력(원장)은 새 테이블을 만들지 않는다 — 기존 admin_operator_activity_logs를
  target_kind='ai_task'로 재사용한다.
  근거: `ops_settings_history`가 "현재값 테이블 + 전용 이력 테이블" 쌍의 선례이지만,
  실측 결과 그 이력 테이블에는 **라이브 writer가 없다**(admin_ops.py의 UPDATE 두 곳
  모두 이 표에 INSERT하지 않는다 — 2행은 시드 기원, 조사자 확인). 반면
  admin_operator_activity_logs는 5,118행의 실제 쓰기 경로가 있고(admin_orders._log 공용
  헬퍼), 같은 급의 정책 화면인 운영 전환 설정(ADM-SYS-010, api/admin_ops.py)이 **바로 이
  표를 이력으로 실사용 중이다**(target_kind='ops', ref_log_id 되돌림 규약 포함). 전용
  이력 테이블을 하나 더 만들면 ops_settings_history와 같은 "만들었지만 안 쓰는 원장"을
  반복할 위험이 있어, 이미 살아 있는 원장에 새 target_kind만 얹는 쪽을 택했다
  (`.claude/CANON.md` §1 "같은 것을 두 벌 두지 않는다"). 이 판단은 조사자가 제작자에게
  위임한 것이다("새 테이블을 만들지, 기존 활동 로그에 얹을지는 제작자 판단" —
  scratchpad/ai-screens-datamap.md §0-4).
  → 이력 조회: `api/admin_ai_tasks.py`의 `GET /api/admin/ai-task-settings/history`
    (WHERE target_kind='ai_task').

■ task_key는 A-35(decision-log.md, 2026-08-13 사장님 확정)가 못박은 닫힌 4종이다.
  CHECK 제약으로 **DB 단에서도** 막는다 — 요구사항 문서 ③이 우려한 "이 화면이 작업
  목록을 임의로 열어두면 A-02·A-03(엔진↔AI 경계) 위반"을 화면 코드가 아니라 스키마가
  지키게 하기 위해서다(더 강한 보장).

■ providers·fallback_order는 JSONB 배열로 둔다(정규화 자식 테이블 대신). 이 화면은
  아직 "휴면"이고(2026-07-21 LLM 연동 보류, 실행 없음) 조회·수정 단위가 항상 "작업 하나
  전체"이며 하위 행 단위 조회가 필요 없다 — 정규화 이득보다 단일 행 원자적 갱신의
  단순함이 이 규모에서 더 크다.

■ prompt_version은 NULLable이다. 이 저장소에는 프롬프트 "본문"을 관리하는 실제 파일도
  DB도 없다(조사자 실측: `PROMPTS`/`PROMPT_BODY`는 원안 dc-ai-task-settings.html의 순수
  JS 상수일 뿐 — 실체 파일 없음). 이 화면은 "휴면"이라 저장한 값이 연동 재개 시 그대로
  살아난다(요구사항 ①) — 그 순간 지어낸 버전 문자열이 실제 프롬프트 참조로 둔갑하면
  안 되므로, 채워지지 않은 상태를 NULL(미지정)로 정직하게 남긴다. 실제 버전 이력은
  admin_operator_activity_logs에 남는 변경 diff에서 파생한다(API가 계산 — 지어낸 카탈로그
  아님).

Revision ID: 0046
Revises: 0045
"""
from alembic import op

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE ai_task_assignments (
          task_key        VARCHAR(50) PRIMARY KEY
                            CHECK (task_key IN (
                              'task.s1_parse', 'task.s2_explain',
                              'task.ops_assist', 'task.spec_fill')),
          mode            VARCHAR(20) NOT NULL DEFAULT 'single'
                            CHECK (mode IN ('concurrent', 'single')),
          -- [{"vendor":"Codex","model":"gpt-5-codex","role":"주"}, ...] 1개 이상(검증은 API)
          providers       JSONB NOT NULL,
          -- ["Claude","Codex",...] 벤더명 순서 — providers 안의 벤더만 담을 수 있다(검증은 API)
          fallback_order  JSONB NOT NULL DEFAULT '[]'::jsonb,
          -- NULL = 아직 지정 안 함 — 지어낸 버전 문자열을 기본값으로 넣지 않는다
          prompt_version  VARCHAR(100),
          updated_by      VARCHAR(100),   -- 표시용 사본(감사 근거는 activity_logs.operator_id)
          updated_at      TIMESTAMP NOT NULL DEFAULT now(),
          created_at      TIMESTAMP NOT NULL DEFAULT now()
        );
    """)


def downgrade() -> None:
    # admin_operator_activity_logs(target_kind='ai_task')는 공유 원장이라 이 마이그레이션이
    # 만들지 않았다 — downgrade도 그 행을 지우지 않는다(원장은 삭제하지 않는다).
    op.execute("DROP TABLE IF EXISTS ai_task_assignments")
