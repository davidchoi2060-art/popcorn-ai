# -*- coding: utf-8 -*-
"""팝콘PC AI API 서버측 클라이언트 (2026-11-09). 라우터 없는 라이브러리다.

원격 주소는 «운영» 쇼핑몰이다. 개발 팝콘AI에서 불러도 쓰기 대상은 운영이다.

  price    읽기. 실제 호출은 LivePriceTransport 로만 나간다.
  basket   api_id=basket 는 GET 이어도 실제 쓰기이고 같은 키의 기존 목록을 지우고 교체한다.
           실제 서버로 나가는 transport 는 이 저장소에 없다. basket_write_allowed 가 True 인
           가짜 transport 에서만 동작한다. 샌드박스 확인 전 이 값을 켠 transport 를 만들지 않는다.

제한값의 근거를 나눈다.
  DOC_*        팝콘PC 가이드 문서가 적은 값(해시 86cf99b2...).
  INTERNAL_*   우리 방어 설정. API 공식 보장이 아니다.

문서에 없어 확정하지 않는 것: 오류 상태코드, HTTP 메서드 제한, 중복 상품 병합, 통화, 세금,
재고, 응답 상한, 키 문자 집합, 링크 접근 권한. 그래서 판매 가능 여부와 재고를 판정하지 않는다.
"""
from __future__ import annotations

import json
import logging
import re
import secrets
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Any, Iterable, Mapping, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

log = logging.getLogger("popcorn.mall_ai_api")

ORIGIN = "https://popcornpc.co.kr"
API_PATH = "/shop/ai_api.php"
API_URL = ORIGIN + API_PATH
API_HOST = "popcornpc.co.kr"
BASKET_LINK_PATH = "/shop/order_basket_list.html"

DOC_MAX_ITEMS = 50
DOC_KEY_LENGTH = 20
DOC_KEY_LENGTH_ERROR = "The API key must be exactly 20 characters long."

INTERNAL_TIMEOUT_SECONDS = 6.0
INTERNAL_MAX_RESPONSE_BYTES = 2_000_000
INTERNAL_MAX_QTY = 99
INTERNAL_MAX_AMOUNT = Decimal(10) ** 12
INTERNAL_MAX_TEXT = 2000
INTERNAL_MAX_SPEC_TEXT = 20000
INTERNAL_LIVE_MAX_CALLS = 3
INTERNAL_LIVE_MIN_INTERVAL_SECONDS = 1.0

_PD_NO_RE = re.compile(r"[1-9][0-9]{0,11}")
_QTY_RE = re.compile(r"[1-9][0-9]{0,3}")
_KEY_RE = re.compile(r"[A-Za-z0-9]{%d}" % DOC_KEY_LENGTH)   # 받는 쪽 내부 규칙이다(문서 미확정, API-008)
_AMOUNT_RE = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")
_PRICE_QUERY_RE = re.compile(r"[1-9][0-9]{0,11}(?:,[1-9][0-9]{0,11}){0,%d}" % (DOC_MAX_ITEMS - 1))

_ALLOWED_FIELDS = ("pd_no", "pd_name", "price", "mileage", "made", "pd_spec",
                   "pd_image_basic", "pd_delivery_price")
_OBSERVE_PATTERNS = {
    "stock_like": re.compile(r"stock|qty|soldout|sold_out|inventory|jaego", re.I),
    "currency_like": re.compile(r"currency|curr", re.I),
    "tax_like": re.compile(r"\btax\b|_tax|tax_|vat", re.I),
}
_IMAGE_HOSTS = {"popcornpc.co.kr", "www.popcornpc.co.kr"}
_IMAGE_PATH_RE = re.compile(r"/?[A-Za-z0-9_\-./%]+\.(?:jpe?g|png|gif|webp)", re.I)


class MallApiError(Exception):
    """메시지에 URL·키·서버 원문을 싣지 않는다. 코드만 싣는다."""

    def __init__(self, code: str, *, http_status: Optional[int] = None, outcome_unknown: bool = False,
                 detail: Optional[str] = None):
        self.code = code
        self.http_status = http_status
        self.outcome_unknown = outcome_unknown      # 쓰기가 나갔는데 결과를 확정하지 못한 상태
        self.detail = detail                        # 진단용 고정 문구와 위치. 응답 내용을 싣지 않는다
        super().__init__("mall_ai_api:%s" % code)


class TransportTimeout(Exception):
    pass


class TransportTooLarge(Exception):
    pass


@dataclass(frozen=True)
class TransportResponse:
    status: int
    body: bytes = b""
    content_type: str = ""


@dataclass(frozen=True)
class Limits:
    timeout_seconds: float = INTERNAL_TIMEOUT_SECONDS
    max_response_bytes: int = INTERNAL_MAX_RESPONSE_BYTES


DEFAULT_LIMITS = Limits()


class OfflineTransport:
    """기본 transport. 아무것도 내보내지 않는다."""

    basket_write_allowed = False

    def get(self, url: str, *, timeout: float, max_bytes: int) -> TransportResponse:
        raise MallApiError("offline_blocked")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None     # 따라가지 않는다. 3xx 는 HTTPError 로 올라와 redirect 오류가 된다


def _build_live_opener():
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _NoRedirect(),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
    )


def assert_price_only_url(url: str) -> None:
    """네트워크 전에 price 조회 주소인지 확정한다. 아니면 어떤 경우에도 내보내지 않는다."""
    if not isinstance(url, str) or not url.startswith(API_URL + "?"):
        raise MallApiError("url_not_allowed")
    query = url[len(API_URL) + 1:]
    if "#" in query:
        raise MallApiError("url_not_allowed")
    pairs = parse_qsl(query, keep_blank_values=True, strict_parsing=False)
    names = [k for k, _ in pairs]
    if "basket" in [v for k, v in pairs if k == "api_id"] or "api_key" in names:
        raise MallApiError("basket_write_blocked")
    if sorted(names) != ["api_id", "pd_no"] or dict(pairs)["api_id"] != "price":
        raise MallApiError("url_not_allowed")
    if not _PRICE_QUERY_RE.fullmatch(dict(pairs)["pd_no"]) or query != urlencode(pairs, safe=","):
        raise MallApiError("url_not_allowed")


# 요청 조건에 따른 응답 차이를 가르는 진단용. 둘 다 같은 price GET 이다.
REQUEST_PROFILES = {
    "default": {"User-Agent": "popcorn-ai/1.0 (+price read)", "Accept": "application/json", "Cache-Control": "no-cache"},
    "no_custom_headers": {},    # 위장이 아니다. urllib 기본 헤더만 나간다
}


class LivePriceTransport:
    """실제 price GET 전용. basket 경로가 없고 호출 수와 간격을 강제한다."""

    basket_write_allowed = False

    def __init__(self, *, max_calls: int = INTERNAL_LIVE_MAX_CALLS,
                 min_interval: float = INTERNAL_LIVE_MIN_INTERVAL_SECONDS,
                 opener: Any = None, clock=time.monotonic, sleep=time.sleep, request_profile: str = "default"):
        if not 1 <= max_calls <= INTERNAL_LIVE_MAX_CALLS:
            raise ValueError("max_calls")
        self._headers = dict(REQUEST_PROFILES[request_profile])
        self._max_calls = max_calls
        self._min_interval = max(float(min_interval), INTERNAL_LIVE_MIN_INTERVAL_SECONDS)
        self._opener = opener
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._calls = 0
        self._last: Optional[float] = None

    @property
    def calls(self) -> int:
        return self._calls

    def get(self, url: str, *, timeout: float, max_bytes: int) -> TransportResponse:
        assert_price_only_url(url)
        if not self._lock.acquire(blocking=False):
            raise MallApiError("concurrent_blocked")
        try:
            if self._calls >= self._max_calls:
                raise MallApiError("live_budget_exhausted")
            if self._last is not None:
                wait = self._min_interval - (self._clock() - self._last)
                if wait > 0:
                    self._sleep(wait)
            self._calls += 1
            self._last = self._clock()
            return self._send(url, timeout, max_bytes)
        finally:
            self._lock.release()

    def _send(self, url: str, timeout: float, max_bytes: int) -> TransportResponse:
        opener = self._opener or _build_live_opener()
        request = urllib.request.Request(url, method="GET", headers=self._headers)
        deadline = self._clock() + timeout
        try:
            with opener.open(request, timeout=timeout) as response:
                status = response.status
                ctype = response.headers.get("Content-Type", "") if response.headers else ""
                body = self._read(response, max_bytes, deadline)
        except urllib.error.HTTPError as exc:
            status, ctype = exc.code, ""
            body = b""
            exc.close()
        except (TransportTimeout, TransportTooLarge):
            raise
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (socket.timeout, TimeoutError)):
                raise TransportTimeout() from None
            raise MallApiError("network") from None
        except (socket.timeout, TimeoutError):
            raise TransportTimeout() from None
        except OSError:
            raise MallApiError("network") from None
        return TransportResponse(status=status, body=body, content_type=ctype.split(";")[0].strip()[:80])

    def _read(self, response: Any, max_bytes: int, deadline: float) -> bytes:
        chunks: list[bytes] = []
        size = 0
        while True:
            if self._clock() > deadline:
                raise TransportTimeout()
            chunk = response.read(65536)
            if not chunk:
                return b"".join(chunks)
            size += len(chunk)
            if size > max_bytes:
                raise TransportTooLarge()
            chunks.append(chunk)


# ---------------------------------------------------------------- 마스킹

def mask_key(_key: Any) -> str:
    return "***"


def mask_url(url: Any) -> str:
    """api_id 만 남기고 쿼리 값을 가린다. 계정 정보와 프래그먼트는 지운다."""
    try:
        parts = urlsplit(str(url))
        host = parts.hostname or ""
        pairs = parse_qsl(parts.query, keep_blank_values=True)
    except ValueError:
        return "<invalid-url>"
    query = "&".join("%s=%s" % (k if k.isascii() and k.isidentifier() else "?", v if k == "api_id" and v.isalpha() else "***")
                     for k, v in pairs)
    return urlunsplit((parts.scheme, host, parts.path, query, ""))


# ---------------------------------------------------------------- 요청값

def normalize_pd_no(value: Any) -> str:
    """양의 정수의 정규 표기만 받는다. 쉼표·콜론·공백·음수·지수·앞자리 0·전각 숫자는 거부한다."""
    if isinstance(value, bool):
        raise MallApiError("invalid_pd_no")
    if isinstance(value, int):
        value = str(value)
    if not isinstance(value, str) or not _PD_NO_RE.fullmatch(value):
        raise MallApiError("invalid_pd_no")
    return value


def normalize_price_request(values: Iterable[Any]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Iterable):
        raise MallApiError("invalid_pd_no")     # "1,2" 를 글자 단위로 쪼개 보내지 않는다
    ordered: dict[str, None] = {}
    for value in values:
        ordered[normalize_pd_no(value)] = None
    if not ordered:
        raise MallApiError("empty_request")
    if len(ordered) > DOC_MAX_ITEMS:
        raise MallApiError("too_many_items")    # 자르거나 나눠 보내지 않는다
    return tuple(ordered)


def build_price_url(pd_nos: Iterable[str]) -> str:
    return API_URL + "?" + urlencode([("api_id", "price"), ("pd_no", ",".join(pd_nos))], safe=",")


# ---------------------------------------------------------------- 응답 봉투

def _reject_constant(_name: str):
    raise ValueError("constant")


def _no_duplicate_keys(pairs):
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError("duplicate key")
        seen[key] = value
    return seen


def _parse_float(text: str) -> Decimal:
    try:
        return Decimal(text)
    except InvalidOperation:
        raise ValueError("number") from None


def _send(transport: Any, url: str, limits: Limits, *, write: bool) -> TransportResponse:
    try:
        response = transport.get(url, timeout=limits.timeout_seconds, max_bytes=limits.max_response_bytes)
    except MallApiError as exc:
        raise MallApiError(exc.code, outcome_unknown=write and exc.code == "network") from None
    except TransportTimeout:
        raise MallApiError("timeout", outcome_unknown=write) from None
    except TransportTooLarge:
        raise MallApiError("response_too_large", outcome_unknown=write) from None
    except Exception:       # noqa: BLE001 - 주입된 transport 의 예외 원문에 URL 이 있을 수 있다
        raise MallApiError("network", outcome_unknown=write) from None
    if not isinstance(response, TransportResponse):
        raise MallApiError("network", outcome_unknown=write)
    return response


# 2026-11-09 실서버 관측(API-010). 가이드에 없는 응답이다. 성공으로 해석하지 않고 원인만 구분한다. IP 값은 버린다.
IP_ERROR_BODY_RE = re.compile(r"\s*\d{1,3}(?:\.\d{1,3}){3} IP ERROR!\s*")


def _decode_envelope(response: TransportResponse, limits: Limits, *, write: bool) -> dict:
    def fail(code: str, **kwargs):
        return MallApiError(code, outcome_unknown=write, **kwargs)

    status = response.status
    if 300 <= status < 400:
        raise fail("redirect", http_status=status)
    if status == 429:
        raise fail("rate_limited", http_status=status)
    if 400 <= status < 500:
        raise fail("http_4xx", http_status=status)
    if status >= 500:
        raise fail("http_5xx", http_status=status)
    if status != 200:
        raise fail("http_status", http_status=status)
    body = response.body
    if len(body) > limits.max_response_bytes:
        raise fail("response_too_large")
    if body.startswith(b"\xef\xbb\xbf"):
        body = body[3:]
    if not body.strip():
        raise fail("empty_body")
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        raise fail("bad_encoding") from None
    if text.lstrip().startswith("<"):
        raise fail("html_response")
    if IP_ERROR_BODY_RE.fullmatch(text):
        raise fail("ip_rejected", http_status=status)
    try:
        document = json.loads(text, parse_float=_parse_float, parse_constant=_reject_constant,
                              object_pairs_hook=_no_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise fail("bad_json", detail="%s@%d" % (exc.msg, exc.pos)) from None
    except RecursionError:
        raise fail("bad_json", detail="too_deep") from None
    except ValueError:
        raise fail("bad_json", detail="rejected_value") from None    # 중복 키, NaN, 비정상 숫자
    if not isinstance(document, dict):
        raise fail("bad_shape")
    if document.get("result") != "ok":
        if "error" in document:
            raise fail("api_key_length" if document["error"] == DOC_KEY_LENGTH_ERROR else "api_error")
        raise fail("bad_result")
    if "error" in document:
        raise fail("bad_result")
    return document


# ---------------------------------------------------------------- 금액

@dataclass(frozen=True)
class Amount:
    """status: ok | zero | missing | null | invalid | negative | non_integer

    ok 만 금액으로 쓸 수 있다. 0 은 무료로 확정하지 않는다(문서가 0의 뜻을 정하지 않았다).
    non_integer 는 정확한 값을 보존하되 원화 정수 정책 밖이라 쓰지 않는다.
    """
    status: str
    value: Optional[Decimal] = None

    @property
    def usable(self) -> Optional[Decimal]:
        return self.value if self.status == "ok" else None

    def public(self) -> dict:
        return {"status": self.status, "value": None if self.value is None else str(self.value)}


def classify_amount(item: Mapping[str, Any], name: str) -> Amount:
    if name not in item:
        return Amount("missing")
    raw = item[name]
    if raw is None:
        return Amount("null")
    if isinstance(raw, bool):
        return Amount("invalid")
    if isinstance(raw, int):
        value = Decimal(raw) if abs(raw) <= INTERNAL_MAX_AMOUNT else None
    elif isinstance(raw, Decimal):
        value = raw if raw.is_finite() and raw.as_tuple().exponent <= 0 else None
    elif isinstance(raw, str) and _AMOUNT_RE.fullmatch(raw):
        value = Decimal(raw)
    else:
        return Amount("invalid")
    if value is None or abs(value) > INTERNAL_MAX_AMOUNT:
        return Amount("invalid")
    if value < 0:
        return Amount("negative")
    if value == 0:
        return Amount("zero", Decimal(0))
    if value != value.to_integral_value():
        return Amount("non_integer", value)
    return Amount("ok", value.quantize(Decimal(1)))


# ---------------------------------------------------------------- 표시 값

class _TextOnly(HTMLParser):
    _DROP = {"script", "style", "iframe", "object", "embed", "template", "noscript"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._DROP:
            self.skip += 1
        self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in self._DROP and self.skip:
            self.skip -= 1
        self.parts.append(" ")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def plain_text(raw: Any, limit: int = INTERNAL_MAX_TEXT) -> Optional[str]:
    """HTML 을 글자로만 남긴다. 태그와 스크립트 내용은 버리고 남은 꺾쇠는 전각으로 바꾼다."""
    if not isinstance(raw, str):
        return None
    text = raw
    for _ in range(3):      # &amp;lt;script&amp;gt; 같은 이중 인코딩까지 벗긴다
        parser = _TextOnly()
        parser.feed(text)
        parser.close()
        stripped = "".join(parser.parts)
        if stripped == text:
            break
        text = stripped
    text = "".join(c if c.isprintable() else " " for c in text)
    text = " ".join(text.split()).replace("<", "＜").replace(">", "＞")
    return text[:limit] or None


def classify_image(raw: Any) -> tuple[str, Optional[str], Optional[str]]:
    """(status, image_url, image_path). 절대 주소는 몰 https 만, 상대 경로는 기준 주소 미확정이라 경로로만 둔다."""
    if raw is None or raw == "":
        return "none", None, None
    if not isinstance(raw, str) or len(raw) > 500 or "\\" in raw or ".." in raw or "%2e" in raw.lower():
        return "rejected", None, None
    if any(not c.isprintable() or c.isspace() for c in raw) or raw.startswith("//"):
        return "rejected", None, None
    if ":" in raw:
        try:
            parts = urlsplit(raw)
            port = parts.port
        except ValueError:
            return "rejected", None, None
        if (parts.scheme != "https" or parts.hostname not in _IMAGE_HOSTS or parts.username is not None
                or parts.password is not None or port is not None or parts.query or parts.fragment
                or not _IMAGE_PATH_RE.fullmatch(parts.path)):
            return "rejected", None, None
        return "absolute", raw, None
    if not _IMAGE_PATH_RE.fullmatch(raw):
        return "rejected", None, None
    return "relative", None, raw


# ---------------------------------------------------------------- price

@dataclass(frozen=True)
class PriceItem:
    pd_no: str
    found: bool
    name: Optional[str] = None
    maker: Optional[str] = None
    spec_text: Optional[str] = None
    image_status: str = "none"
    image_url: Optional[str] = None
    image_path: Optional[str] = None
    price: Amount = Amount("missing")
    mileage: Amount = Amount("missing")
    delivery_price: Amount = Amount("missing")
    sale_state: str = "unknown"     # 반환됐다고 판매 가능·재고 있음이 아니다
    currency: Optional[str] = None  # 문서에 없다. 원화로 확정하지 않는다

    def public(self) -> dict:
        return {
            "pd_no": self.pd_no, "found": self.found, "name": self.name, "maker": self.maker,
            "spec_text": self.spec_text, "image_status": self.image_status,
            "image_url": self.image_url, "image_path": self.image_path,
            "price": self.price.public(), "mileage": self.mileage.public(),
            "delivery_price": self.delivery_price.public(),
            "sale_state": self.sale_state, "currency": self.currency,
        }


@dataclass(frozen=True)
class PriceResult:
    requested: tuple[str, ...]
    items: Mapping[str, PriceItem]
    missing: tuple[str, ...]
    dropped_field_count: int = 0
    observed: Mapping[str, bool] = field(default_factory=dict)
    allowed_raw: tuple[dict, ...] = field(default=(), repr=False)   # 허용 필드 원값. 증거 저장 전용

    def public(self) -> dict:
        return {"requested": list(self.requested), "missing": list(self.missing),
                "items": [self.items[code].public() for code in self.requested],
                "dropped_field_count": self.dropped_field_count, "observed": dict(self.observed)}


def _response_code(raw: Any) -> str:
    if isinstance(raw, bool):
        raise MallApiError("bad_shape")
    if isinstance(raw, int):
        raw = str(raw)
    if not isinstance(raw, str) or not _PD_NO_RE.fullmatch(raw):
        raise MallApiError("bad_shape")
    return raw


def _price_item(raw: Mapping[str, Any], code: str) -> PriceItem:
    status, image_url, image_path = classify_image(raw.get("pd_image_basic"))
    return PriceItem(
        pd_no=code, found=True, name=plain_text(raw.get("pd_name")), maker=plain_text(raw.get("made")),
        spec_text=plain_text(raw.get("pd_spec"), INTERNAL_MAX_SPEC_TEXT),
        image_status=status, image_url=image_url, image_path=image_path,
        price=classify_amount(raw, "price"), mileage=classify_amount(raw, "mileage"),
        delivery_price=classify_amount(raw, "pd_delivery_price"),
    )


def parse_price_response(response: TransportResponse, requested: tuple[str, ...],
                         limits: Limits = DEFAULT_LIMITS) -> PriceResult:
    document = _decode_envelope(response, limits, write=False)
    raw_items = document.get("items")
    if not isinstance(raw_items, list):
        raise MallApiError("bad_shape")
    found: dict[str, PriceItem] = {}
    allowed_raw: list[dict] = []
    dropped = 0
    names: set[str] = set(document) - {"result", "items"}
    wanted = set(requested)
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise MallApiError("bad_shape")
        code = _response_code(raw.get("pd_no"))
        if code not in wanted:
            raise MallApiError("unexpected_item")
        if code in found:
            raise MallApiError("duplicate_item")
        found[code] = _price_item(raw, code)
        allowed_raw.append({k: raw[k] for k in _ALLOWED_FIELDS if k in raw})
        extra = set(raw) - set(_ALLOWED_FIELDS)
        dropped += len(extra)
        names |= extra
    missing = tuple(code for code in requested if code not in found)
    items = {code: found.get(code) or PriceItem(pd_no=code, found=False) for code in requested}
    observed = {label: any(p.search(n) for n in names) for label, p in _OBSERVE_PATTERNS.items()}
    return PriceResult(requested=requested, items=items, missing=missing, dropped_field_count=dropped,
                       observed=observed, allowed_raw=tuple(allowed_raw))


def fetch_prices(pd_nos: Iterable[Any], *, transport: Any = None, limits: Limits = DEFAULT_LIMITS) -> PriceResult:
    """기본 transport 는 offline 이다. 재시도하지 않는다. DB 에 저장하지 않는다."""
    requested = normalize_price_request(pd_nos)
    url = build_price_url(requested)
    try:
        response = _send(transport or OfflineTransport(), url, limits, write=False)
        result = parse_price_response(response, requested, limits)
    except MallApiError as exc:
        log.warning("mall_ai_api price failed code=%s", exc.code)
        raise
    log.info("mall_ai_api price ok requested=%d missing=%d", len(requested), len(result.missing))
    return result


# ---------------------------------------------------------------- basket (실제 호출 금지)

@dataclass(frozen=True)
class BasketLine:
    pd_no: str
    qty: int = 1


@dataclass(frozen=True)
class BasketReceipt:
    key: str = field(repr=False)
    link: str = field(repr=False)
    lines: tuple[BasketLine, ...] = ()


def new_quote_key() -> str:
    """견적 식별자다. 인증 비밀키가 아니지만 예측되면 남의 장바구니를 덮을 수 있어 난수로 만든다.

    문서가 보여 준 형식인 숫자 20자리로 만든다(약 66비트). 영문 허용 여부는 문서에 없다(API-008).
    숫자 변환 저장소에서 앞자리 0이 사라지지 않도록 첫 자리는 1~9다.
    """
    head = secrets.choice("123456789")
    return head + "".join(secrets.choice("0123456789") for _ in range(DOC_KEY_LENGTH - 1))


def validate_quote_key(key: Any) -> str:
    if not isinstance(key, str) or not _KEY_RE.fullmatch(key):
        raise MallApiError("invalid_key")
    return key


def _normalize_qty(raw: Any) -> int:
    if raw is None:
        return 1
    if isinstance(raw, bool):
        raise MallApiError("invalid_qty")
    if isinstance(raw, str):
        if not _QTY_RE.fullmatch(raw):
            raise MallApiError("invalid_qty")
        raw = int(raw)
    if not isinstance(raw, int) or raw < 1 or raw > INTERNAL_MAX_QTY:
        raise MallApiError("invalid_qty")
    return raw


def normalize_basket_lines(lines: Iterable[Any]) -> tuple[BasketLine, ...]:
    """수량 생략은 1. 중복 상품은 병합 규칙이 문서에 없어 합치지 않고 거부한다."""
    if isinstance(lines, (str, bytes)) or not isinstance(lines, Iterable):
        raise MallApiError("invalid_pd_no")
    result: dict[str, BasketLine] = {}
    for line in lines:
        if isinstance(line, BasketLine):
            code, qty = line.pd_no, line.qty
        elif isinstance(line, tuple):
            if len(line) != 2:
                raise MallApiError("invalid_qty")
            code, qty = line
        else:
            code, qty = line, None
        pd_no = normalize_pd_no(code)
        if pd_no in result:
            raise MallApiError("duplicate_item")
        result[pd_no] = BasketLine(pd_no, _normalize_qty(qty))
    if not result:
        raise MallApiError("empty_request")
    if len(result) > DOC_MAX_ITEMS:
        raise MallApiError("too_many_items")
    return tuple(result.values())


def build_basket_url(key: str, lines: tuple[BasketLine, ...]) -> str:
    spec = ",".join("%s:%d" % (line.pd_no, line.qty) for line in lines)
    return API_URL + "?" + urlencode([("api_id", "basket"), ("api_key", key), ("pd_no", spec)], safe=",:")


def expected_link(key: str) -> str:
    return "%s%s?api_key=%s" % (ORIGIN, BASKET_LINK_PATH, key)


def _verify_basket(document: dict, key: str, lines: tuple[BasketLine, ...]) -> str:
    # 링크는 한 글자도 다르면 거부한다. 외부 원점·userinfo·다른 키·중복 키·상대 경로가 모두 여기서 걸린다.
    link = document.get("link")
    if link != expected_link(key):
        raise MallApiError("bad_link", outcome_unknown=True)
    raw_items = document.get("items")
    if not isinstance(raw_items, list):
        raise MallApiError("bad_shape", outcome_unknown=True)
    got: dict[str, int] = {}
    try:
        for raw in raw_items:
            if not isinstance(raw, dict):
                raise MallApiError("bad_shape")
            code = _response_code(raw.get("pd_no"))
            if code in got:
                raise MallApiError("basket_mismatch")
            got[code] = _normalize_qty(raw["qty"]) if raw.get("qty") is not None else 0
    except MallApiError:
        raise MallApiError("basket_mismatch", outcome_unknown=True) from None
    if got != {line.pd_no: line.qty for line in lines}:
        raise MallApiError("basket_mismatch", outcome_unknown=True)
    return link


class BasketClient:
    """쓰기 호출. 자동 재시도가 없다. 보낸 뒤 성공을 확정하지 못하면 outcome_unknown 으로 끝난다."""

    def __init__(self, transport: Any = None, *, limits: Limits = DEFAULT_LIMITS):
        self._transport = transport or OfflineTransport()
        self._limits = limits

    def replace(self, key: str, lines: Iterable[Any]) -> BasketReceipt:
        # 값 검증보다 먼저 막는다. 허용되지 않은 transport 에는 어떤 경우에도 주소를 넘기지 않는다.
        if getattr(self._transport, "basket_write_allowed", False) is not True:
            raise MallApiError("basket_write_blocked")
        key = validate_quote_key(key)
        normalized = normalize_basket_lines(lines)
        url = build_basket_url(key, normalized)
        try:
            response = _send(self._transport, url, self._limits, write=True)
            document = _decode_envelope(response, self._limits, write=True)
            link = _verify_basket(document, key, normalized)
        except MallApiError as exc:
            log.warning("mall_ai_api basket failed code=%s unknown=%s", exc.code, exc.outcome_unknown)
            raise
        log.info("mall_ai_api basket ok lines=%d", len(normalized))
        return BasketReceipt(key=key, link=link, lines=normalized)


@dataclass
class _Quote:
    owner: str
    key: str
    in_flight: bool = False
    revision: int = 0
    outcome_unknown: bool = False
    receipt: Optional[BasketReceipt] = None


class BasketCoordinator:
    """(사용자, 견적)마다 키 하나. 같은 키의 동시 쓰기를 막고 늦은 응답이 상태를 덮지 못하게 한다.

    메모리 상태다. 프로세스를 여러 개 띄우는 운영에서는 공용 저장소가 필요하다(활성화 전 조건).
    """

    def __init__(self, client: BasketClient):
        self._client = client
        self._lock = threading.Lock()
        self._quotes: dict[tuple[str, str], _Quote] = {}
        self._keys: dict[str, tuple[str, str]] = {}

    @staticmethod
    def _identity(owner: Any, quote: Any) -> tuple[str, str]:
        if not (isinstance(owner, str) and owner and isinstance(quote, str) and quote):
            raise MallApiError("invalid_owner")
        return owner, quote

    def _slot(self, identity: tuple[str, str]) -> _Quote:
        slot = self._quotes.get(identity)
        if slot is None:
            key = new_quote_key()
            while key in self._keys:
                key = new_quote_key()
            slot = _Quote(owner=identity[0], key=key)
            self._quotes[identity] = slot
            self._keys[key] = identity
        return slot

    def key_for(self, owner: str, quote: str) -> str:
        with self._lock:
            return self._slot(self._identity(owner, quote)).key

    def adopt_key(self, owner: str, quote: str, key: str) -> None:
        """저장돼 있던 견적의 키를 되살린다. 다른 사용자·다른 견적의 키는 거부한다."""
        identity = self._identity(owner, quote)
        validate_quote_key(key)
        with self._lock:
            if self._keys.get(key, identity) != identity or identity in self._quotes:
                raise MallApiError("key_conflict")
            self._quotes[identity] = _Quote(owner=owner, key=key)
            self._keys[key] = identity

    def invalidate(self, owner: str, quote: str) -> None:
        """이 시점 이전에 나간 요청의 응답은 버린다. 요청이 돌아오기 전까지 새 쓰기는 여전히 막는다."""
        with self._lock:
            slot = self._quotes.get(self._identity(owner, quote))
            if slot:
                slot.revision += 1
                slot.receipt = None

    def state(self, owner: str, quote: str) -> dict:
        with self._lock:
            slot = self._quotes.get(self._identity(owner, quote))
            if not slot:
                return {"in_flight": False, "outcome_unknown": False, "receipt": None}
            return {"in_flight": slot.in_flight, "outcome_unknown": slot.outcome_unknown, "receipt": slot.receipt}

    def replace(self, owner: str, quote: str, lines: Iterable[Any], *, confirm_unknown: bool = False) -> BasketReceipt:
        """confirm_unknown 은 사람이 결과 불명 뒤 다시 누른 경우에만 넘긴다. 코드가 자동으로 넘기지 않는다."""
        identity = self._identity(owner, quote)
        normalized = normalize_basket_lines(lines)
        with self._lock:
            slot = self._slot(identity)
            if slot.in_flight:
                raise MallApiError("busy")
            if slot.outcome_unknown and not confirm_unknown:
                raise MallApiError("outcome_unknown_pending", outcome_unknown=True)
            slot.in_flight = True
            issued = slot.revision
        try:
            receipt = self._client.replace(slot.key, normalized)
        except MallApiError as exc:
            with self._lock:
                slot.in_flight = False
                if exc.outcome_unknown:
                    slot.outcome_unknown = True
                    slot.receipt = None
            raise
        except BaseException:
            with self._lock:
                slot.in_flight = False
                slot.outcome_unknown = True
                slot.receipt = None
            raise
        with self._lock:
            slot.in_flight = False
            if issued != slot.revision:
                # 서버에는 이 늦은 요청이 반영됐을 수 있다. 화면 상태는 덮지 않고 불명으로 남긴다.
                slot.outcome_unknown = True
                raise MallApiError("stale_response", outcome_unknown=True)
            slot.outcome_unknown = False
            slot.receipt = receipt
        return receipt
