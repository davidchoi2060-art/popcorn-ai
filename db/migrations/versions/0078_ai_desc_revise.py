# -*- coding: utf-8 -*-
"""AI 작업 설명 문안 개정 — 사장님 예시 톤(2026-09-09 두 번째 지시)

■ 무엇이 바뀌나
  0077이 채운 description 14건의 문안을 전면 개정한다.
  사장님 예시 그대로의 흐름 — "PC에 직접 설치 → 인터넷 없이 구동 →
  ChatGPT처럼 질문하면 답변" + 걸리는 시간·초당 처리 속도를 구체 수치로.

■ 속도 수치의 근거 (지어내지 않는다 — 전부 공개 실측 벤치마크)
  8B Q4  : RTX 4060급에서 40+ tokens/s (databasemart.com Ollama 벤치마크,
           2026-08 확인 — "models under 5.0GB can achieve 40+ tokens/s")
  14B Q4 : RTX 4060 Ti 16GB에서 21~40 tokens/s (modelfit.io ~21 ·
           autolearningagents.com 25~40 · hardware-corner.net 22.4)
  32B Q4 : VRAM 안착 시 15~30 tokens/s (autolearningagents.com)
  체감 환산: 초당 30~50토큰 ≈ 짧은 답 몇 초, 긴 답(문서 요약 등) 수십 초.
  토큰≈한국어 기준 반 단어 안팎의 근사임을 문안에서 "단어" 대신
  "글자가 흘러나오는 속도"류 표현으로 피해 간다.

Revision ID: 0078
Revises: 0077
"""
import sqlalchemy as sa
from alembic import op

revision = "0078"
down_revision = "0077"
branch_labels = None
depends_on = None

DESCRIPTIONS = {
    ("LLM 로컬 추론", "7B-8B"):
        "PC에 무료 프로그램(Ollama·LM Studio)을 설치하고 공개 LLM 모델(라마·Qwen 등)을 "
        "내려받으면, 인터넷 연결 없이 내 PC에서 ChatGPT를 쓰듯 질문하고 답변을 받는다. "
        "이 구성이면 짧은 질문은 몇 초, 긴 문서 요약도 수십 초 안에 답이 나온다"
        "(초당 40토큰 이상 — 화면에 글자가 실시간으로 흘러나오는 속도). "
        "VRAM이 부족한 PC에서는 같은 모델도 답변 하나에 몇 분씩 걸린다 — "
        "그 차이를 만드는 것이 그래픽카드 메모리다.",
    ("LLM 로컬 추론", "13B-14B"):
        "설치·사용법은 7B급과 같고(Ollama·LM Studio에서 더 큰 모델을 받기만 하면 된다) "
        "답변 품질이 한 단계 좋아진다 — 긴 문서 분석, 더 자연스러운 대화, 중급 코딩 보조. "
        "이 구성이면 초당 20~40토큰, 짧은 질문 몇 초·긴 답변 30초~1분 수준이다. "
        "개인 PC 로컬 AI의 실용 상한선으로 통하는 크기.",
    ("LLM 로컬 추론", "30B-34B"):
        "전문 작업용 크기 — 복잡한 추론과 정확한 코딩 보조까지 간다. "
        "VRAM 24GB급 그래픽카드에 모델이 온전히 올라가야 초당 15~30토큰"
        "(짧은 답 십몇 초·긴 답 1~2분)이 나오고, 그보다 작은 카드에서는 "
        "CPU로 넘어가 같은 질문에 몇 분씩 걸린다.",
    ("LLM 로컬 추론", "70B"):
        "ChatGPT급에 근접한 성능을 내 PC에서 내는 크기 — 다만 그래픽카드 한 장의 "
        "VRAM(최대 32GB)으로는 부족하다(48GB 필요). 현재 판매 구성 중 이 작업이 "
        "가능한 것이 없는 이유다. 무리해서 돌리면 답변 하나에 수 분~수십 분이 걸린다.",
    ("LLM 파인튜닝 (LoRA)", "7B"):
        "AI를 내 데이터로 추가 학습시키는 작업(입문 크기). 회사 말투·전문용어·"
        "우리 문서 스타일을 모델에 가르치는 용도다. 무료 도구(Unsloth)로 "
        "학습 한 번에 몇 시간 수준 — 학습 중에는 PC가 풀가동된다.",
    ("LLM 파인튜닝 (LoRA)", "14B"):
        "중형 모델을 내 데이터로 추가 학습시킨다. 7B보다 결과 품질이 좋은 만큼 "
        "VRAM 요구가 올라가고 학습 시간도 길어진다 — 학습 설정(양자화)에 따라 "
        "필요 사양 폭이 넓다.",
    ("LLM 파인튜닝 (LoRA)", "32B"):
        "대형 모델 추가 학습. VRAM 26GB 이상이 필요해 일반 소비자 그래픽카드 "
        "한 장으로는 빠듯하거나 불가능하다.",
    ("LLM 파인튜닝 (LoRA)", "70B"):
        "최대급 모델 추가 학습 — VRAM 41GB 이상. 일반 PC 한 대 범위를 넘는 "
        "작업이라 현재 판매 구성으로는 불가능하다.",
    ("이미지 생성 (SDXL)", "SDXL 1.0 (2.6B)"):
        "PC에 무료 프로그램(ComfyUI·WebUI)을 설치하고 공개 모델(SDXL)을 받으면, "
        "문장을 입력해 그림을 만든다 — 일러스트·컨셉아트·상품 이미지. "
        "이 구성이면 한 장에 수 초~수십 초. 인터넷 연결도, 장당 요금도 없다.",
    ("이미지 생성 (Flux)", "FLUX.1 dev (12B)"):
        "최신 세대 이미지 생성 AI — SDXL보다 정교하고 사실적인 결과물. "
        "설치·사용법은 같고(ComfyUI) VRAM 요구만 높다: 12GB부터 돌고 24GB면 "
        "원활하다. 한 장에 수십 초 수준.",
    ("영상 생성", "Wan2.2 TI2V-5B (720p/24fps)"):
        "문장이나 사진 한 장으로 짧은 영상(720p·24프레임)을 만드는 공개 AI 모델. "
        "ComfyUI로 돌리며 VRAM 24GB급 최신 고급 그래픽카드가 필요하다. "
        "영상 몇 초 분량을 만드는 데 수 분이 걸린다 — 이미지보다 훨씬 무거운 작업이다.",
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
    conn = op.get_bind()
    for (task, size), desc in DESCRIPTIONS.items():
        conn.execute(sa.text(
            "UPDATE ai_workloads SET description = :d "
            "WHERE task = :t AND model_size = :s"
        ), {"d": desc, "t": task, "s": size})
    n = conn.execute(sa.text(
        "SELECT count(*) FROM ai_workloads WHERE description IS NOT NULL"
    )).scalar()
    print(f"[0078] 문안 개정: {n}건 (0077 초안 -> 사장님 예시 톤)")


def downgrade() -> None:
    # 0077의 초안 문안으로 되돌리려면 0077을 다시 적용해야 한다 — 문안 이력은
    # 마이그레이션 파일 자체가 보존하므로 여기서는 아무것도 하지 않는다.
    pass
