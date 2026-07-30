"""비밀번호 해싱·검증 — 원문은 어디에도 남기지 않는다 (슬라이스 70).

표준 라이브러리 `hashlib.scrypt`만 쓴다. 새 의존성이 없고, scrypt는 메모리를 많이
쓰도록 설계돼 GPU 무차별 대입에 강하다.

저장 형식: `scrypt$n$r$p$<salt-b64>$<hash-b64>`
파라미터를 값 안에 넣어 두면 나중에 세기를 올려도 **옛 해시를 그대로 검증**할 수 있다.
형식을 바꿀 때마다 전원 비밀번호를 다시 받게 하면 아무도 안 바꾼다.

**원문은 로그·응답·예외 메시지 어디에도 넣지 않는다.** 이 모듈 밖으로 나가는 것은
해시 문자열과 참/거짓뿐이다.
"""
import base64
import hashlib
import hmac
import os
import re

# 2026년 기준 상호작용 로그인에 무난한 세기(약 100~200ms).
# 올릴 때는 이 값만 바꾸면 된다 — 기존 해시는 자기 파라미터로 검증된다.
_N, _R, _P = 2 ** 14, 8, 1
_DKLEN = 32
_SALT = 16

MIN_LENGTH = 10          # 짧은 비밀번호는 잠금·속도 제한으로도 못 막는다


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def hash_password(raw: str) -> str:
    """비밀번호 → 저장용 문자열. 원문은 이 함수 밖으로 나가지 않는다."""
    salt = os.urandom(_SALT)
    dk = hashlib.scrypt(raw.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P,
                        dklen=_DKLEN, maxmem=64 * 1024 * 1024)
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(dk)}"


def verify_password(raw: str, stored: str | None) -> bool:
    """저장값과 대조. 형식이 깨졌거나 값이 없으면 **통과시키지 않는다**."""
    if not stored or not raw:
        return False
    try:
        algo, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        salt, want = base64.b64decode(salt_b64), base64.b64decode(hash_b64)
        got = hashlib.scrypt(raw.encode("utf-8"), salt=salt,
                             n=int(n), r=int(r), p=int(p),
                             dklen=len(want), maxmem=64 * 1024 * 1024)
    except (ValueError, TypeError):
        return False
    # 시간 일정 비교 — 앞자리부터 틀리는 위치가 새어 나가지 않게
    return hmac.compare_digest(got, want)


def strength_problem(raw: str, email: str | None = None) -> str | None:
    """약한 비밀번호면 이유를, 괜찮으면 None. **원문을 되돌려 주지 않는다.**"""
    if not raw or len(raw) < MIN_LENGTH:
        return f"비밀번호는 {MIN_LENGTH}자 이상이어야 합니다"
    kinds = sum(bool(re.search(p, raw)) for p in
                (r"[a-z]", r"[A-Z]", r"\d", r"[^\w\s]"))
    if kinds < 3:
        return "영문 대문자·소문자·숫자·기호 중 3가지 이상을 섞어 주세요"
    if re.search(r"(.)\1{3,}", raw):
        return "같은 문자를 4번 이상 반복하지 마세요"
    if email:
        local = email.split("@")[0].lower()
        if len(local) >= 4 and local in raw.lower():
            return "이메일과 같은 문자열은 쓸 수 없습니다"
    low = raw.lower()
    for bad in ("password", "popcorn", "admin", "qwerty", "12345678"):
        if bad in low:
            return "흔한 단어가 들어 있습니다"
    return None


# ---- 슬라이스 100: 규칙을 화면에 알려준다 ----
# 화면이 강도 규칙을 **베껴 쓰면** MIN_LENGTH를 올린 날 화면이 거짓을 말한다.
# 그래서 `strength_problem`과 같은 파일에서 규칙 문구를 만들어 내려보낸다 —
# 판정과 설명이 한 곳에 있어야 어긋나지 않는다.
#
# 지금까지는 운영자가 **거절당한 뒤에야** 규칙을 알았다(모달에 아무 안내가 없었다).
def password_rules() -> dict:
    """화면이 그대로 보여줄 규칙. 원문·해시와 무관한 설명만 담는다."""
    return {
        "min_length": MIN_LENGTH,
        "rules": [
            f"{MIN_LENGTH}자 이상",
            "영문 대문자 · 소문자 · 숫자 · 기호 중 3가지 이상 섞기",
            "같은 문자를 4번 이상 반복하지 않기",
            "이메일 앞부분과 같은 문자열 쓰지 않기",
            "흔한 단어(password · admin · qwerty 등) 쓰지 않기",
            "이전 비밀번호와 다르게",
        ],
    }
