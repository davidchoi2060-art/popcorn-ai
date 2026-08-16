"""관리자 비밀번호를 서버에서 직접 설정한다 (슬라이스 70).

닭과 달걀 문제를 푼다: 비밀번호가 없으면 로그인할 수 없고, 로그인하지 못하면
비밀번호를 발급할 수 없다. 첫 계정만 여기서 연다.

    .venv/Scripts/python tools/set_admin_password.py admin@popcornpc.local

비밀번호는 **인자로 받지 않는다** — 명령줄에 적으면 셸 히스토리와 프로세스 목록에
남는다. 실행하면 화면에 보이지 않게 두 번 입력받는다.
원문은 저장·출력·기록하지 않는다. DB로 가는 것은 scrypt 해시뿐이다.
"""
import argparse
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools._console import ensure_utf8_console       # noqa: E402
ensure_utf8_console()

from dotenv import load_dotenv                       # noqa: E402
from sqlalchemy import create_engine, text           # noqa: E402

from api.passwords import hash_password, strength_problem   # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("email", help="비밀번호를 설정할 운영자 이메일")
    ap.add_argument("--force-change", action="store_true",
                    help="최초 로그인에서 변경을 요구한다(임시 비밀번호 발급용)")
    args = ap.parse_args()

    load_dotenv(os.path.join(ROOT, ".env"))
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL이 없습니다(.env 또는 환경변수).")
        return 2
    engine = create_engine(url)

    email = args.email.strip().lower()
    with engine.connect() as c:
        op = c.execute(text(
            "SELECT operator_id, name, role, status FROM admin_operators"
            " WHERE lower(email)=:e"), {"e": email}).mappings().first()
    if op is None:
        print(f"그런 운영자가 없습니다: {email}")
        return 1
    print(f"대상: {op['name']} ({email}) · {op['role']}/{op['status']}")
    if op["status"] != "활성":
        print("경고: 활성 계정이 아닙니다 — 비밀번호를 설정해도 로그인할 수 없습니다.")

    pw = getpass.getpass("새 비밀번호: ")
    again = getpass.getpass("다시 입력: ")
    if pw != again:
        print("두 입력이 다릅니다.")
        return 1
    bad = strength_problem(pw, email)
    if bad:
        print("약한 비밀번호:", bad)
        return 1

    with engine.begin() as c:
        c.execute(text(
            "UPDATE admin_operators SET password_hash=:h, password_set_at=now(),"
            " must_change_password=:mc, login_fail_count=0, locked_until=NULL"
            " WHERE operator_id=:i"),
            {"h": hash_password(pw), "mc": bool(args.force_change),
             "i": op["operator_id"]})
    # 원문은 출력하지 않는다
    print("설정했습니다." + (" 최초 로그인에서 변경을 요구합니다."
                          if args.force_change else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
