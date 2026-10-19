# -*- coding: utf-8 -*-
"""고객 화면 출처 — 상담 신청·견적 보관이 어느 고객 화면(/mvp3 · /mvp4)에서 왔는지 (2026-10-19 사장님 확정).

서버와 관리자단은 한 벌이고 고객 화면만 /mvp3 와 /mvp4 둘로 나눠 쓴다. 관리자는 같은 기록 표에서
어느 화면에서 들어온 신청인지 구분해야 한다(/mvp4 가 자리 잡으면 /mvp3 를 닫는다).

각 화면의 요청 함수가 `X-Popcorn-Surface` 머리글에 자기 이름을 싣는다(mvp3/api-client.js · new-pcs.js ·
mvp4/assets/js/live-checkout.js · service-adapters.js). Referer 는 쓰지 못한다 — nginx 가
`Referrer-Policy: no-referrer` 를 걸어 브라우저가 보내지 않는다(deploy/nginx-popcorn.conf).
표시용 구분이라 판정·권한에 쓰지 않는다. 머리글이 없거나 모르는 값이면 None(「알 수 없음」) — 지어내지 않는다.
"""
from __future__ import annotations

from fastapi import Request

HEADER = "x-popcorn-surface"
SURFACES = ("mvp3", "mvp4")
LABELS = {"mvp3": "기존 화면(mvp3)", "mvp4": "새 메인(mvp4)"}


def surface_of(request: Request) -> str | None:
    v = (request.headers.get(HEADER) or "").strip().lower()
    return v if v in SURFACES else None


def label(surface) -> str:
    return LABELS.get(surface, "알 수 없음")
