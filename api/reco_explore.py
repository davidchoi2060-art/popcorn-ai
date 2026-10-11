# -*- coding: utf-8 -*-
"""상담 주고받기 — 고객 말의 «추가 조건»과 «더 싸게 / 더 좋게»를 판매 PC 고르기에 반영한다
(2026-10-11 중헌 님 지적: 「무슨 말을 해도 가장 표준적인 PC 하나로 결론 난다 — 티키타카가 없다」).

■ 왜 따로 두나
  TalkState(talk_schema)는 «격자 좌표»라 램·저장공간·그래픽카드 모델·케이스 색 같은 조건을 담을
  자리가 없다. 그래서 고객이 「램 64GB」·「흰색 케이스」라고 해도 AI 답은 「맞춰드리겠습니다」인데
  카드는 그대로였다(2026-10-11 고객 역할 점검). 이 모듈은 그 조건을 **고객 문장에서 규칙으로**
  읽어(LLM 을 다시 부르지 않는다) 판매 PC 후보를 실제로 거르고, 거를 수 없으면 «못 맞춘다»고
  밝힌다. 상태는 화면이 `wants` 로 들고 다니며 다음 요청에 돌려보낸다(서버 세션 없음 — talk 와 같은 규약).

■ 지어내지 않는 것
  · 판정 재료는 판매 PC 의 평가 사양(product_fit_products.spec)과 구성 부품의 선호 태그
    (product_specs.tag_white · tag_silent) 뿐이다. 상품명 글자로 색·소음을 추측하지 않는다.
  · 그래픽카드 «급» 은 같은 모델이 든 판매 PC 의 그래픽 지수로만 정한다. 그 모델이 든 PC 가
    하나도 없으면 기준을 만들지 않고 «못 맞춘다»고 말한다.
  · 내부 지수는 고객 문장에 싣지 않는다(협업 6번) — 문장은 조건 이름과 용량만 말한다.
"""
import logging
import re

from sqlalchemy import text

from .db import engine

log = logging.getLogger("reco_explore")

CHEAPER, BETTER = "cheaper", "better"
WANT_KEYS = ("min_ram_gb", "min_ssd_gb", "gpu_model", "white", "silent", "monitor", "uhd")
MAX_TEXT = 300

# ── 고객 문장 읽기 ──────────────────────────────────────────────────────
_NUMBER_BUDGET = re.compile(r"\d+\s*(만|원|천)|[일이삼사오육칠팔구십백천]+\s*만")
_CHEAPER = re.compile(r"(더|좀|조금|많이)\s*(싼|싸|저렴)|싸게|저렴하게|저렴한|가격.{0,4}(낮|내려|줄)|"
                      r"최저가|제일\s*싼|가장\s*싼|싼\s*(걸|거|것)|예산.{0,4}(낮|줄|내려)")
# 「가장·제일·최대한 싸게 / 최저가」 -- 지금 보던 카드보다 «더» 싼 것이 아니라 조건 안의 최저가를 뜻한다
# (코덱스 #155 검수 P2-1: 앞 추천이 있으면 상대 이동으로 읽혀 두 장이 다시 나왔다).
_CHEAPEST = re.compile(r"(가장|제일|젤|최대한|최저)\s*(싼|싸|저렴)|최저\s*가|최소\s*(비용|가격|금액|예산)")
_BETTER = re.compile(r"(더|좀|조금|훨씬)\s*(좋은|좋게|높은|나은|센|빠른|고급|비싼)|업그레이드|고사양|상위|"
                     r"한\s*단계\s*위|최고\s*사양|최고사양|최고로|풀옵|제일\s*좋은|가장\s*좋은|높은\s*사양|좋은\s*(걸|거|것)\s*으?로")
_SPEC_NUMBER = re.compile(r"(rtx|gtx|rx)?\s*\d+(?:\.\d+)?\s*(gb|기가|g|tb|테라|t|hz|헤르츠|인치|fps|프레임|ti|super|xt)(?![a-z])|(rtx|gtx|rx)\s*\d{3,4}", re.I)
_RAM = re.compile(r"(램|ram|메모리)\s*(?:은|는|을|를|도)?\s*(\d{1,3})\s*(?:gb|기가|g)?", re.I)
_RAM_MORE = re.compile(r"(램|ram|메모리)\s*(?:을|를|은|는|도)?\s*(?:좀|조금|많이)?\s*(더|늘|업|크게|넉넉)", re.I)
_SSD = re.compile(r"(ssd|저장\s*공간|저장\s*장치|용량|하드)\s*(?:은|는|을|를|도)?\s*(\d+(?:\.\d+)?)\s*(tb|테라|t|gb|기가|g)", re.I)
_TB = re.compile(r"(\d+(?:\.\d+)?)\s*(tb|테라)", re.I)
_SSD_MORE = re.compile(r"(ssd|저장\s*공간|저장\s*장치|용량)\s*(?:을|를|은|는|도)?\s*(?:좀|조금|많이)?\s*(더|늘|업|크게|넉넉)", re.I)
_GPU = re.compile(r"(rtx|gtx|rx)?\s*(?<!\d)(\d{4})(?!\d)\s*(ti|super|슈퍼|xt)?", re.I)
_GPU_CONTEXT = re.compile(r"rtx|gtx|rx\s*\d|그래픽|글카|vga|지포스|라데온", re.I)
_WHITE = re.compile(r"흰색|화이트|하얀|하양|white", re.I)
_SILENT = re.compile(r"조용|저소음|무소음|소음.{0,3}(적|없|작)|silent", re.I)
_MONITOR = re.compile(r"모니터.{0,6}(포함|같이|까지|도\s|도$|함께|세트|추가)")
_MONITOR_OWNED = re.compile(r"모니터.{0,6}(있|보유|가지)")
_MULTI = re.compile(r"(\d{1,3})\s*대")
_MULTI_WORD = re.compile(r"여러\s*대|대량|단체")
_UHD = re.compile(r"4\s*k|uhd|4천", re.I)


def _ssd_gb(num: str, unit: str) -> int | None:
    try:
        v = float(num)
    except ValueError:
        return None
    gb = int(v * 1000) if unit.lower() in ("tb", "테라", "t") else int(v)
    return gb if 120 <= gb <= 16000 else None


def extract(raw: str | None) -> dict:
    """고객 문장 하나 -> {wants 일부, nav, more, multi}. 못 읽은 것은 넣지 않는다.

    예산·게임·해상도는 읽지 않는다 — talk(파서)가 state 로 준다(같은 것을 두 곳에서 읽지 않는다).
    """
    s = (raw or "")[:MAX_TEXT]
    out: dict = {}
    if not s.strip():
        return out
    has_budget_number = bool(_NUMBER_BUDGET.search(s))
    # 「더 싸게 150으로」처럼 숫자가 있으면 예산 변경이다 — 해석(talk)이 예산을 바꾸므로 방향은 걸지 않는다.
    # 사양 숫자(램 64GB · SSD 1TB · RTX 5060 · 144Hz)는 예산 변경이 아니다 -- 지우고 본다(코덱스 #161 검수 경계:
    # 「램 64GB로 최대한 싸게」가 최저가를 못 읽었다).
    if not has_budget_number and not re.search(r"\d{2,}", _SPEC_NUMBER.sub(" ", s)):
        if _CHEAPER.search(s):
            out["nav"] = CHEAPER
            if _CHEAPEST.search(s):
                out["cheapest"] = True
        elif _BETTER.search(s):
            out["nav"] = BETTER
    m = _RAM.search(s)
    if m and 4 <= int(m.group(2)) <= 256:
        out["min_ram_gb"] = int(m.group(2))
    elif _RAM_MORE.search(s):
        out.setdefault("more", []).append("ram")
    m = _SSD.search(s) or None
    gb = _ssd_gb(m.group(2), m.group(3)) if m else None
    if gb is None:
        t = _TB.search(s)
        gb = _ssd_gb(t.group(1), t.group(2)) if t else None
    if gb is not None:
        out["min_ssd_gb"] = gb
    elif _SSD_MORE.search(s):
        out.setdefault("more", []).append("ssd")
    if _GPU_CONTEXT.search(s):
        for g in _GPU.finditer(s):
            n = int(g.group(2))
            if n % 10 or not 1000 <= n <= 9999:
                continue
            prefix = (g.group(1) or ("RX" if re.search(r"rx|라데온", s, re.I)
                                     else "GTX" if n < 2000 else "RTX")).upper()
            suffix = {"ti": " Ti", "super": " SUPER", "슈퍼": " SUPER", "xt": " XT"}.get((g.group(3) or "").lower(), "")
            out["gpu_model"] = f"{prefix} {n}{suffix}"
            break
    if _WHITE.search(s):
        out["white"] = True
    if _SILENT.search(s):
        out["silent"] = True
    if _MONITOR.search(s) and not _MONITOR_OWNED.search(s):
        out["monitor"] = True
    m = _MULTI.search(s)
    if (m and 2 <= int(m.group(1)) <= 500) or _MULTI_WORD.search(s):
        out["multi"] = True
    if _UHD.search(s):
        out["uhd"] = True
    return out


def clean_wants(raw) -> dict:
    """화면이 돌려보낸 wants — 모양이 맞는 값만 받는다(공개 경로라 그대로 믿지 않는다)."""
    out: dict = {}
    if not isinstance(raw, dict):
        return out
    for k in ("min_ram_gb", "min_ssd_gb"):
        v = raw.get(k)
        if type(v) is int and 1 <= v <= 16000:
            out[k] = v
    g = raw.get("gpu_model")
    if isinstance(g, str) and re.fullmatch(r"(RTX|GTX|RX) \d{4}( Ti| SUPER| XT)?", g):
        out["gpu_model"] = g
    for k in ("white", "silent", "monitor", "uhd"):
        if raw.get(k) is True:
            out[k] = True
    return out


def merge(prev: dict, new: dict) -> dict:
    out = dict(prev)
    for k in WANT_KEYS:
        if k in new:
            out[k] = new[k]
    return out


# ── 성능 비교값 (서버 내부 · 고객 응답에 싣지 않는다) ─────────────────────
GPU_HEAVY = {"게임", "영상편집", "3D 렌더링", "방송·스트리밍", "로컬 AI"}


def perf(p: dict, usage: str) -> float:
    """같은 용도 안에서 «더 높은 사양»을 가르는 값. 평가 사양 지수만 쓴다(값이 없으면 0)."""
    sp = p.get("spec") or {}
    if not isinstance(sp, dict):
        return 0.0
    num = lambda k: sp.get(k) if type(sp.get(k)) in (int, float) else 0  # noqa: E731
    gpu, cpu, ram = num("gpu_idx") / 100, num("cpu_mt") / 20000, num("ram_gb") / 32
    if usage in GPU_HEAVY:
        return gpu * 0.7 + cpu * 0.25 + ram * 0.05
    return cpu * 0.75 + gpu * 0.1 + ram * 0.15


def _gb_label(gb: int) -> str:
    return f"{gb // 1000}TB" if gb >= 1000 and gb % 1000 == 0 else f"{gb}GB"


def _gpu_has(spec_gpu, model: str) -> bool:
    """판매 PC 의 그래픽카드 이름에 그 모델 번호(와 Ti·SUPER·XT 를 말했으면 그것까지)가 있는가."""
    if not isinstance(spec_gpu, str):
        return False
    g = spec_gpu.upper().replace(" ", "")
    want = model.upper().split(" ", 1)[1].replace(" ", "")      # "4070TI" · "4070"
    return want in g


# ── 부품 선호 태그 (케이스 색 · 저소음) ──────────────────────────────────
TAG_SQL = """
    SELECT CAST(substr(o.offer_id, 2) AS bigint) AS product_code,
           bool_or(cp.slot = 'CASE' AND COALESCE(ps.tag_white, false)) AS white,
           bool_and(COALESCE(ps.tag_silent, false))
             FILTER (WHERE cp.slot IN ('GPU', 'POWER', 'PSU', 'CASE', 'COOLER')) AS silent
      FROM pc_configuration_offers o
      JOIN pc_configuration_parts cp ON cp.configuration_id = o.configuration_id AND NOT cp.pseudo
      LEFT JOIN product_specs ps ON ps.product_code = cp.explanation_code
     WHERE o.offer_id ~ '^P[1-9][0-9]{0,17}$'
     GROUP BY o.offer_id
"""


def part_tags() -> dict:
    """판매 상품코드 -> {white, silent}. 구성 부품 기록이 없는 상품은 들어 있지 않다(=모름)."""
    try:
        with engine.connect() as conn:
            return {int(r.product_code): {"white": bool(r.white), "silent": bool(r.silent)}
                    for r in conn.execute(text(TAG_SQL))}
    except Exception:  # noqa: BLE001 - 못 읽으면 그 조건은 «못 맞춘다»로 정직하게 떨어진다
        log.exception("[reco_explore] part tags unavailable")
        return {}


# ── 거르기 ───────────────────────────────────────────────────────────────
def _spec(p, k):
    sp = p.get("spec") if isinstance(p.get("spec"), dict) else {}
    v = sp.get(k)
    return v if type(v) in (int, float) else None


def build_filters(wants: dict, products: dict, tags_loader=None) -> list[tuple[str, str, object]]:
    """wants -> [(key, 고객 이름표, 판정 함수 | 못 정한 사유 str)]. 순서가 우선순위다."""
    out = []
    if wants.get("min_ram_gb"):
        n = wants["min_ram_gb"]
        out.append(("min_ram_gb", f"램 {n}GB 이상", lambda p, n=n: (_spec(p, "ram_gb") or 0) >= n))
    if wants.get("min_ssd_gb"):
        n = wants["min_ssd_gb"]
        # 「1TB」라고 하면 판매 PC 의 960GB·1,000GB 도 1TB 다(표기 차이) — 90% 까지 같은 용량으로 본다.
        out.append(("min_ssd_gb", f"저장공간 {_gb_label(n)} 이상",
                    lambda p, n=n: (_spec(p, "ssd_gb") or 0) >= n * 0.9))
    if wants.get("gpu_model"):
        model = wants["gpu_model"]
        idx = [(_spec(p, "gpu_idx")) for p in products.values()
               if _gpu_has((p.get("spec") or {}).get("gpu") if isinstance(p.get("spec"), dict) else None, model)]
        idx = [i for i in idx if i]
        label = f"그래픽카드 {model}급 이상"
        if idx:
            floor = min(idx)
            out.append(("gpu_model", label, lambda p, f=floor: (_spec(p, "gpu_idx") or 0) >= f))
        else:
            out.append(("gpu_model", label, f"{model}이(가) 든 판매 PC가 없어 비교 기준을 정하지 못했어요."))
    tags = None
    for key, label in (("white", "흰색 케이스"), ("silent", "저소음 부품")):
        if wants.get(key):
            tags = tags if tags is not None else (tags_loader or part_tags)()
            out.append((key, label, lambda p, k=key, t=tags: bool(t.get(p["code"], {}).get(k))))
    if wants.get("monitor"):
        out.append(("monitor", "모니터 포함",
                    lambda p: isinstance(p.get("includes"), str) and "모니터" in p["includes"]))
    return out


def apply_filters(pool: list, filters, min_ok) -> tuple[list, list[str], list[tuple[str, str]]]:
    """pool 에 조건을 차례로 건다. 걸었을 때 조건을 채우는 PC 가 0 이면 그 조건은 «못 맞춤».

    min_ok(p) 는 그 용도의 최소 수준을 넘는지 — 수준 미달 상품만 남는 조건도 못 맞춘 것이다.
    반환: (거른 pool, 반영한 이름표[], 못 맞춘 [(이름표, 사유)])
    """
    applied, unmet = [], []
    for key, label, fn in filters:
        if isinstance(fn, str):
            unmet.append((label, fn))
            continue
        kept = [p for p in pool if fn(p)]
        if any(min_ok(p) for p in kept):
            pool = kept
            applied.append(label)
        else:
            unmet.append((label, "판매 중인 PC 중에 이 조건을 맞추는 것이 없어요."))
    return pool, applied, unmet


# ── 고객 문장 ────────────────────────────────────────────────────────────
def unmet_sentence(label: str, why: str) -> str:
    return f"「{label}」 조건은 지금 못 맞춥니다. {why}"


def applied_sentence(labels: list[str]) -> str:
    return "「" + "」 「".join(labels) + "」 조건에 맞는 PC만 골랐어요."


NOTE_MULTI = "여러 대를 한 번에 맞추는 견적은 지금 못 맞춥니다. 한 대 기준으로 보여 드려요."
NOTE_CHEAPER = "지금 보신 추천 구성보다 싼 PC를 보여 드려요."
NOTE_CHEAPER_NONE = "지금 조건에서는 더 싼 PC가 없어요. 같은 목록을 다시 보여 드려요."
NOTE_CHEAPEST = "조건에 맞는 PC를 가장 싼 것부터 보여 드려요."
NOTE_BETTER = "지금 보신 추천 구성보다 사양이 높은 PC를 보여 드려요."
NOTE_BETTER_NONE = "지금 조건에서는 더 높은 사양의 판매 PC가 없어요. 같은 목록을 다시 보여 드려요."
NOTE_MORE_NO_ANCHOR = "어느 PC보다 크게 할지 몰라서 이번에는 반영하지 못했어요. 원하는 용량을 숫자로 말씀해 주세요."
ASK_NEXT = "더 싼 PC나 더 높은 사양도 보여 드릴까요? 아래에서 골라 주세요."
# 2026-10-11 개발 서버 확인 후속: 되묻는 말은 실제로 누를 수 있는 단추만 말한다.
ASK_CHEAPER_ONLY = "더 싼 PC도 보여 드릴까요? 아래에서 골라 주세요."
ASK_BETTER_ONLY = "더 높은 사양을 보거나 조건을 바꿀 수 있어요. 아래에서 골라 주세요."


def over_budget_sentence(budget_won: int) -> str:
    """예산 안에 맞는 판매 PC가 없어 예산을 넘는 가장 싼 PC만 보일 때 — 카드 상태와 같은 말."""
    man = budget_won // 10000
    amount = f"{man:,}만원" if budget_won % 10000 == 0 else f"{budget_won:,}원"
    return f"{amount} 안에는 맞는 PC가 없어서 가장 가까운 PC를 보여 드려요."


def ask_next(has_cheaper: bool, has_better: bool) -> str | None:
    """켜진 빠른 선택에 맞는 되묻기. 둘 다 꺼져 있으면 말하지 않는다."""
    if has_cheaper and has_better:
        return ASK_NEXT
    if has_cheaper:
        return ASK_CHEAPER_ONLY
    if has_better:
        return ASK_BETTER_ONLY
    return None
