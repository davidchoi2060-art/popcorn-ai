# -*- coding: utf-8 -*-
"""승인 구성이 없는 판매 PC 의 상세 소개(「ABOUT THIS PC」) — 2026-10-21 대표 「진행해」 「다른 있는 설명들 참고해서 · DB화」.

■ 왜
  /mvp4 상세 하단 소개는 승인 구성(pc_configurations.content)이 있는 82대에만 있었다. 나머지 240대(몰 등록 구성만
  있는 PC)는 소개 자료가 없어 그 구획이 통째로 빠졌다.

■ 무엇으로 쓰나 — 새 사실을 만들지 않는다
  몰 상품명의 [CPU/메모리/SSD/그래픽](대표 2026-10-21 「제목이 틀리긴 힘드니까 그걸 기준으로」) · 없으면 용도 평가 사양
  용도 평가(product_usage_fit · product_fit_levels.work — 관리자 매트릭스·추천과 같은 원천)
  형식·말투는 승인 구성 소개(제목 · 소개 · 특징 3개 · 사용 상황)를 따른다.

■ 어디에 두나
  pc_registered_about(0172) 에 저장하고 상세(/api/customer/pc-registered/{code})가 읽는다. 관리자가 고친 행(origin='admin')은
  다시 만들지 않는다. 표에 없는 새 상품은 읽을 때 같은 함수로 만들어 보인다(저장은 하지 않는다).
이 모듈은 DB 를 부르지 않는다(마이그레이션 0172 이 같은 함수를 쓴다).
"""
from __future__ import annotations

import re

_TITLE = re.compile(r"\[\s*([^\[\]/]+?)\s*/\s*(\d+)\s*G(?:B)?\s*/\s*([^/\]]+?)\s*/\s*([^\]]+?)\s*(?:\]|$)", re.I)
_EA = re.compile(r"\s*\*\s*\d+\s*EA\s*$", re.I)
_CAP = re.compile(r"(\d+(?:\.\d+)?)\s*(TB|GB|G)(?![A-Za-z0-9])", re.I)


def title_spec(name):
    """몰 상품명 [CPU/메모리/SSD/그래픽] -> {cpu, ram_gb, ssd, ssd_gb, gpu}. 없으면 None."""
    m = _TITLE.search(name or "")
    if not m:
        return None
    ssd = m.group(3).split("+")[0].strip()
    ssd = re.sub(r"(?i)(\d)\s*G$", r"\1GB", ssd)
    return {"cpu": m.group(1).strip(), "ram_gb": int(m.group(2)), "ssd": ssd, "ssd_gb": gb(ssd),
            "gpu": _EA.sub("", m.group(4)).strip()}


def gb(text):
    m = _CAP.search(str(text or ""))
    if not m:
        return None
    return round(float(m.group(1)) * (1000 if m.group(2).upper() == "TB" else 1))


def _size(n):
    return f"{n // 1000}TB" if n >= 1000 and n % 1000 == 0 else f"{n}GB"


def facts(name, fit_spec):
    """상품명이 기준, 상품명에 없으면 용도 평가 사양. 모르는 칸은 None."""
    t = title_spec(name)
    if t:
        return t
    s = fit_spec if isinstance(fit_spec, dict) else {}
    ram, ssd = s.get("ram_gb"), s.get("ssd_gb")
    ok = lambda v: isinstance(v, int) and v > 0  # noqa: E731
    return {"cpu": s.get("cpu") or None, "ram_gb": ram if ok(ram) else None,
            "ssd": _size(ssd) if ok(ssd) else None, "ssd_gb": ssd if ok(ssd) else None, "gpu": s.get("gpu") or None}


_IGPU = re.compile(r"내장|UHD|Iris|Radeon\s*(Graphics|Vega|\d{3}M)|Vega|\bXe\b", re.I)


def integrated(gpu):
    return not gpu or bool(_IGPU.search(gpu)) or not re.search(r"\d", gpu)


def _rank(fits, usage):
    return next((f for f in fits if f["usage"] == usage and f.get("rank")), None)


def headline(fits):
    """승인 구성 소개의 제목처럼 «무엇을 하는 PC 인가» 한 줄. 가장 무거운 용도부터 본다."""
    r = lambda u: (_rank(fits, u) or {}).get("rank", 0)  # noqa: E731
    game = (_rank(fits, "게임") or {}).get("level")
    if r("로컬 AI") >= 2:
        return "로컬 AI 작업까지 생각한 고성능 PC"
    if r("3D 렌더링") >= 2:
        return "3D 렌더링까지 고려한 작업용 PC"
    if r("영상편집") >= 2:
        return "4K 영상 편집까지 생각한 PC"
    if game == "4K":
        return "4K 게임까지 노리는 PC"
    if game == "QHD":
        return "QHD 게임을 즐기는 PC"
    if game == "FHD":
        return "최신 게임을 FHD로 즐기는 PC"
    if r("영상편집") >= 1:
        return "FHD 영상 편집도 해 볼 수 있는 PC"
    if game == "캐주얼":
        return "가벼운 게임과 일상 작업을 함께 하는 PC"
    if r("사무용") >= 2:
        return "업무와 멀티태스킹을 여유 있게 하는 PC"
    return "문서와 인터넷, 기본 작업부터 시작하는 PC"


# 소개에 먼저 내세울 용도 — 무거운 작업부터. 단계 번호는 용도마다 뜻이 달라(게임 FHD 2 · 사무용 쾌적 2) 서로 비교하지 않는다.
PRIORITY = ("로컬 AI", "3D 렌더링", "영상편집", "게임", "방송·스트리밍", "캐드·설계", "디자인·조판", "개발", "음악 작업",
            "사무용", "주식·트레이딩")


def _top(fits, n):
    """첫 단계를 넘은 용도(rank 2 이상)를 먼저, 그 안에서는 무거운 작업부터."""
    seen = [f for f in fits if f.get("rank") and f.get("level")]
    pri = lambda u: PRIORITY.index(u) if u in PRIORITY else len(PRIORITY)  # noqa: E731
    return sorted(seen, key=lambda f: (f["rank"] < 2, pri(f["usage"])))[:n]


def _gpu_benefit(f, fits):
    if integrated(f["gpu"]):
        return ["일상 작업을 중심으로 담았어요",
                "별도 그래픽카드를 추가하지 않고 CPU의 내장 그래픽을 활용합니다. "
                "게임보다 문서·인터넷 사용이 중심인 분이 먼저 비교할 구성입니다."]
    game = _rank(fits, "게임")
    if game:
        text = f"팝콘AI 용도 평가에서 게임은 「{game['level']}」 단계로 봤습니다"
        text += f"({game['work']})." if game.get("work") else "."
        if game["level"] != "4K":
            text += " 더 높은 해상도나 옵션을 원하면 상위 그래픽카드 구성과 비교해 주세요."
        return [f"{f['gpu']}, 게임은 {game['level']} 수준이에요", text]
    return [f"{f['gpu']} 그래픽카드를 담았어요", "화면 출력과 그래픽 처리를 맡는 부품입니다. 쓰려는 프로그램의 권장 사양과 함께 비교해 주세요."]


def _ram_benefit(n):
    if n <= 8:
        return [f"{n}GB, 기본 사용부터 살펴보세요",
                "웹페이지나 프로그램을 여러 개 열 때 메모리가 부족할 수 있습니다. "
                "필요한 프로그램을 중심으로 쓰는 경우에 살펴보고, 동시 작업이 많다면 더 큰 메모리 구성을 비교해 주세요."]
    if n <= 16:
        return [f"{n}GB, 일반 작업과 게임에 알맞아요",
                "웹·업무 프로그램과 게임을 함께 쓰는 정도에 맞춘 용량입니다. "
                "대형 작업 파일이나 가상머신을 많이 쓴다면 32GB 이상 구성과 비교해 주세요."]
    if n <= 32:
        return [f"{n}GB, 여러 작업을 함께 해도 여유 있어요",
                "프로그램 여러 개와 브라우저 탭을 함께 띄워도 여유가 있는 용량입니다. "
                "대형 영상·3D 작업이 많다면 64GB 이상 구성도 살펴보세요."]
    return [f"{n}GB, 큰 작업 파일도 여유 있게",
            "대형 프로젝트·영상·3D 장면처럼 메모리를 많이 쓰는 작업을 고려한 용량입니다."]


def _ssd_benefit(label, n):
    if n <= 256:
        return [f"{label} SSD, 보관할 파일부터 확인해요",
                "운영체제와 프로그램을 설치하면 남는 공간이 줄어듭니다. "
                "게임이나 영상 파일을 많이 보관한다면 500GB·1TB 이상 구성과 비교해 주세요."]
    if n < 1000:
        return [f"{label} SSD, 기본 저장 공간이에요",
                "운영체제와 자주 쓰는 프로그램을 담기에 알맞습니다. "
                "게임이나 영상 자료를 많이 보관한다면 1TB 이상 구성과 비교해 주세요."]
    if n < 2000:
        return [f"{label} SSD, 프로그램과 자료를 넉넉히",
                "운영체제·프로그램과 함께 게임이나 작업 자료를 담기에 여유가 있습니다. "
                "자료가 아주 많다면 추가 저장장치를 함께 살펴보세요."]
    return [f"{label} SSD, 큰 자료도 여유 있게",
            "용량이 큰 게임이나 영상·프로젝트 파일을 많이 보관해도 여유가 있는 구성입니다."]


def build(name, fit_spec, fits):
    """소개 dict(title·intro·benefits·scene) 또는 None(쓸 근거가 없을 때).

    fits = [{usage, level, rank, work}] — 기준표 순서. rank 0/None 은 그 용도에 못 미친다는 뜻이라 쓰지 않는다.
    """
    f = facts(name, fit_spec)
    fits = [dict(x) for x in (fits or [])]
    # 용도 평가가 상품명과 다른 메모리·SSD 로 매겨졌으면(몰 구성 오기 · 123380 「16GB * 2개」) 그 평가의 높은 단계는
    # 믿지 않는다 — 게임(그래픽카드가 정한다)만 두고 나머지는 첫 단계까지만 쓴다.
    s = fit_spec if isinstance(fit_spec, dict) else {}
    if title_spec(name) and ((s.get("ram_gb") and f["ram_gb"] and s["ram_gb"] != f["ram_gb"])
                             or (s.get("ssd_gb") and f["ssd_gb"] and abs(s["ssd_gb"] - f["ssd_gb"]) > f["ssd_gb"] * 0.1)):
        fits = [x for x in fits if x.get("usage") == "게임" or (x.get("rank") or 0) < 2]
    if not (f["cpu"] or f["gpu"] or f["ram_gb"] or f["ssd_gb"]) and not _top(fits, 1):
        return None
    if f["cpu"] and integrated(f["gpu"]):
        first = f"CPU {f['cpu']}의 내장 그래픽을 사용하는 구성입니다."
    elif f["cpu"] or f["gpu"]:
        first = " · ".join(x for x in (f"CPU {f['cpu']}" if f["cpu"] else None,
                                       f"그래픽 {f['gpu']}" if f["gpu"] else None) if x) + " 구성입니다."
    else:
        first = ""
    store = [x for x in (f"{f['ram_gb']}GB 메모리" if f["ram_gb"] else None, f"{f['ssd']} SSD" if f["ssd"] else None) if x]
    uses = [x["usage"] for x in _top(fits, 3)]
    second = ""
    if store and uses:
        second = f"{'와 '.join(store)}를 담아 {', '.join(uses)} 같은 사용을 고려했습니다."
    elif store:
        second = f"{'와 '.join(store)}를 담았습니다."
    elif uses:
        second = f"{', '.join(uses)} 같은 사용을 고려했습니다."
    benefits = []
    if f["cpu"] or f["gpu"]:
        benefits.append(_gpu_benefit(f, fits))
    if f["ram_gb"]:
        benefits.append(_ram_benefit(f["ram_gb"]))
    if f["ssd_gb"]:
        benefits.append(_ssd_benefit(f["ssd"], f["ssd_gb"]))
    works = [x["work"] for x in _top(fits, 2) if x.get("work")]
    return {"title": headline(fits), "intro": " ".join(x for x in (first, second) if x),
            "benefits": benefits, "scene": (", ".join(works) + " 같은 사용.") if works else "",
            "basis": "mall-title-and-usage-fit"}
