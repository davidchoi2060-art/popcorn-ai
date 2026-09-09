# -*- coding: utf-8 -*-
"""게임·AI 작업 매핑 판정 스킵 사유 — 사람이 읽는 문구의 단일 원천.

tools/game_cell_mapper.py(배치, DB에 저장)와 api/admin_game_matrix.py(화면
API, 그 값을 그대로 노출)가 이 사전을 같이 참조한다 — 문구를 두 곳에 따로
적지 않는다(CLAUDE.md §단일 원천). 2026-09-09 신설, 배경은 이 파일과 같은
날짜의 0080 마이그레이션 머리 주석 참조.

키는 tools/game_cell_mapper.py의 skip_reasons 카운터 키와 정확히 같아야
한다 — 다르면 배치가 저장한 값을 이 사전이 못 찾아 화면에 원문 키가
그대로 노출된다(REASON_LABELS.get(key, key)로 안전망은 있으나 문구가
어색해진다).
"""

REASON_LABELS = {
    # 게임(games) 매핑 스킵 — tools/game_cell_mapper.py _map_games()
    "rec_gpu_missing":
        "게임사가 권장 사양을 공개하지 않았습니다 — 원천에 값이 없어 판정할 수 없습니다",
    "rec_gpu_parse_failed":
        "권장 사양 그래픽카드가 서열표에 없는 구형 모델입니다 — 대부분의 PC에서"
        " 충분히 돌아갈 것으로 보이나, 서열표 확장 전까지는 판정할 수 없습니다",
    "zero_matching_cells":
        "권장 사양을 충족하는 격자 칸이 현재 재고에 없습니다",
    # AI 작업(ai_workloads) 매핑 스킵 — tools/game_cell_mapper.py _map_workloads()
    "min_vram_gb_missing":
        "이 작업의 최소 VRAM 요구량이 아직 확인되지 않았습니다",
}


def label_of(reason):
    """스킵 사유 키를 사람이 읽는 한국어 문장으로 바꾼다. 없으면 원문 그대로."""
    if not reason:
        return None
    return REASON_LABELS.get(reason, reason)
