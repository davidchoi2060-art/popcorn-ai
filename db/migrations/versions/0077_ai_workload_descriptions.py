# -*- coding: utf-8 -*-
"""AI 작업에 쉬운 설명을 단다 — ai_workloads.description

■ 왜
  "LLM 로컬 추론 7B-8B" 같은 표기는 아는 사람만 읽는다(2026-09-09 사장님 지적).
  "이 컴퓨터로 뭐가 되는데?"에 답하려면 ①뭘 설치해서 어떻게 쓰는지 ②속도
  기대치(VRAM 부족 PC에서 답변이 몇 분씩 걸리는 것과의 차이)가 문장으로
  붙어야 한다. 사장님 실경험(Ollama에서 답변 2~3분 = VRAM 부족 CPU 폴백)이
  이 문안의 근거다 — min_vram 판정이 걸러주는 것이 바로 그 증상이다.

■ 왜 note가 아니라 새 컬럼인가
  note는 varchar(200)이고 출처·계산 근거를 적는 자리다(수치의 근거).
  설명은 고객 문안이라 성격이 다르고 200자를 넘는다 — 섞으면 한 컬럼이
  두 얼굴을 갖는다. TEXT로 새로 둔다.

■ 문안 확정 경위
  2026-09-09 사장님 승인 — "속도 기대치 + 뭘 설치해서 어떻게 쓰는지" 포함
  방향으로 하네스 초안을 다듬은 것. 수치(VRAM·토큰 속도)는 ai_workloads의
  실측 열이 원천이고, 이 문안은 그 수치를 사람 말로 옮긴 것뿐이다 —
  새 수치를 지어내지 않는다.

Revision ID: 0077
Revises: 0076
"""
import sqlalchemy as sa
from alembic import op

revision = "0077"
down_revision = "0076"
branch_labels = None
depends_on = None

DESCRIPTIONS = {
    ("LLM 로컬 추론", "7B-8B"):
        "Ollama·LM Studio 같은 무료 프로그램을 설치하고 공개 모델(라마·Qwen 등)을 "
        "내려받아, 인터넷 없이 내 PC에서 AI 챗봇을 쓴다. 이 구성의 그래픽카드면 "
        "질문에 몇 초 안에 답이 온다 — VRAM이 부족한 PC에선 같은 모델도 답변에 "
        "몇 분씩 걸린다(그 차이가 그래픽카드 메모리다). 일상 질문·문서 요약·"
        "간단한 코딩 보조가 가능한 크기.",
    ("LLM 로컬 추론", "13B-14B"):
        "7B급보다 한 단계 똑똑한 로컬 챗봇. 긴 문서 분석, 더 자연스러운 대화, "
        "중급 코딩 보조까지 간다. 개인 PC 로컬 AI의 실용 상한선으로 통하는 "
        "크기다. 쓰는 법은 같다 — Ollama·LM Studio에 모델만 큰 것을 받으면 된다.",
    ("LLM 로컬 추론", "30B-34B"):
        "전문 작업용 크기. 복잡한 추론과 정확한 코딩 보조가 가능하지만 "
        "VRAM 24GB급 고급 그래픽카드가 있어야 몇 초 안에 답이 온다. "
        "그 아래 카드에선 CPU로 넘어가 답변이 분 단위로 느려진다.",
    ("LLM 로컬 추론", "70B"):
        "ChatGPT급에 근접한 성능을 로컬에서 내는 크기 — 다만 일반 PC 한 대의 "
        "그래픽카드로는 VRAM이 부족하다(48GB 필요). 현재 판매 구성 중 이 작업이 "
        "가능한 것이 없는 이유다.",
    ("LLM 파인튜닝 (LoRA)", "7B"):
        "AI를 내 데이터로 추가 학습시키는 작업(입문 크기). 회사 말투·전문용어·"
        "우리 문서 스타일을 모델에 가르치는 용도다. Unsloth 같은 무료 도구로 "
        "몇 시간이면 한 번 학습이 돈다.",
    ("LLM 파인튜닝 (LoRA)", "14B"):
        "중형 모델을 내 데이터로 추가 학습시킨다. 7B보다 결과 품질이 좋은 만큼 "
        "VRAM 요구가 올라간다 — 학습 설정(양자화)에 따라 필요 사양 폭이 넓다.",
    ("LLM 파인튜닝 (LoRA)", "32B"):
        "대형 모델 추가 학습. VRAM 26GB 이상이 필요해 일반 소비자 그래픽카드 "
        "한 장으로는 빠듯하거나 불가능하다.",
    ("LLM 파인튜닝 (LoRA)", "70B"):
        "최대급 모델 추가 학습 — VRAM 41GB 이상. 일반 PC 한 대 범위를 넘는 "
        "작업이라 현재 판매 구성으로는 불가능하다.",
    ("이미지 생성 (SDXL)", "SDXL 1.0 (2.6B)"):
        "문장을 입력하면 그림을 만들어주는 AI(무료 공개 모델). ComfyUI·"
        "WebUI 같은 무료 프로그램으로 돌린다. 일러스트·컨셉아트·상품 이미지 "
        "제작에 쓰이고, 이 구성이면 장당 수 초~수십 초에 나온다.",
    ("이미지 생성 (Flux)", "FLUX.1 dev (12B)"):
        "최신 세대 이미지 생성 AI. SDXL보다 정교하고 사실적인 결과물을 내는 "
        "대신 VRAM 요구가 높다 — 12GB부터 돌고 24GB면 원활하다.",
    ("영상 생성", "Wan2.2 TI2V-5B (720p/24fps)"):
        "문장이나 사진 한 장으로 짧은 영상(720p·24프레임)을 만드는 AI. "
        "VRAM 24GB급 최신 고급 그래픽카드가 필요하다.",
    ("영상 생성", "Wan2.2 T2V/I2V-A14B"):
        "고품질 영상 생성 — VRAM 80GB급이 필요해 일반 소비자 장비 범위를 "
        "넘는다(데이터센터급 장비의 영역). 현재 판매 구성으로는 불가능하다.",
    ("AI 개발환경", "NVIDIA AI Workbench"):
        "NVIDIA가 무료로 제공하는 AI 개발 통합 환경. 모델 실험·학습 환경을 "
        "클릭 몇 번으로 구성해 주며, RTX 그래픽카드가 있는 PC에서 로컬 AI "
        "개발을 시작하는 표준 경로다.",
    ("AI 개발환경", "Unsloth 로컬 학습 환경"):
        "공개 LLM을 적은 VRAM으로 빠르게 추가 학습시키는 무료 도구. "
        "VRAM 4GB부터 입문할 수 있어 로컬 AI 학습의 첫 실습 환경으로 알맞다.",
}


def upgrade() -> None:
    op.add_column("ai_workloads", sa.Column("description", sa.Text(), nullable=True))
    conn = op.get_bind()
    for (task, size), desc in DESCRIPTIONS.items():
        conn.execute(sa.text(
            "UPDATE ai_workloads SET description = :d "
            "WHERE task = :t AND model_size = :s"
        ), {"d": desc, "t": task, "s": size})
    n = conn.execute(sa.text(
        "SELECT count(*) FROM ai_workloads WHERE description IS NOT NULL"
    )).scalar()
    print(f"[0077] ai_workloads.description 채움: {n}건")


def downgrade() -> None:
    op.drop_column("ai_workloads", "description")
