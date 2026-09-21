#!/usr/bin/env bash
# DB 비밀번호 교체 — 서버 /etc/popcorn-ai.env 갱신 + 재기동
#
# 사장님이 서버에서 직접 실행한다. 비밀번호는 화면에 찍히지 않고
# 이 파일에도 저장되지 않는다.
#
# 쓰는 법:
#   ssh -i ~/.ssh/google_compute_engine leon2@34.47.124.184
#   (접속 후)  bash /tmp/rotate_db_pw.sh
set -euo pipefail

ENVF=/etc/popcorn-ai.env
BAK="/etc/popcorn-ai.env.bak.$(date +%Y%m%d_%H%M%S)"

echo "=============================================="
echo " DB 비밀번호 교체 — 서버"
echo "=============================================="
echo

# 1) 백업 (되돌릴 수 있게)
sudo cp -p "$ENVF" "$BAK"
echo "[1/5] 백업 완료: $BAK"

# 2) 새 비밀번호 입력 (화면에 안 보임 · 두 번 확인)
echo
read -rsp "새 DB 비밀번호 입력: " PW1; echo
read -rsp "한 번 더 입력      : " PW2; echo
if [ "$PW1" != "$PW2" ]; then
  echo "!! 두 값이 다릅니다. 아무것도 바꾸지 않고 종료합니다."; exit 1
fi
if [ -z "$PW1" ]; then
  echo "!! 빈 값입니다. 종료합니다."; exit 1
fi

# 3) URL 인코딩 (비밀번호에 @ : / # 등이 있어도 안전하게)
PWENC=$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.stdin.readline().rstrip("\n"), safe=""))' <<<"$PW1")

# 4) DATABASE_URL 의 비밀번호 부분만 교체
sudo python3 - "$ENVF" "$PWENC" <<'PYEOF'
import re, sys
path, pw = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as f:
    txt = f.read()
new, n = re.subn(
    r'(^\s*DATABASE_URL\s*=\s*"?[A-Za-z0-9+._-]+://[^:@/]+:)[^@]+(@)',
    lambda m: m.group(1) + pw + m.group(2),
    txt, flags=re.M)
if n != 1:
    sys.exit(f"!! DATABASE_URL 을 {n}개 찾았습니다(1개여야 함). 중단합니다.")
with open(path, "w", encoding="utf-8") as f:
    f.write(new)
print("[2/5] DATABASE_URL 갱신 완료")
PYEOF
unset PW1 PW2 PWENC

# 5) 접속 시험 — 재기동 «전에» 확인한다
echo "[3/5] 새 비밀번호로 접속 시험..."
if sudo -u popcorn bash -c "set -a; . $ENVF; set +a; \
   cd /srv/popcorn-ai && .venv/bin/python -c \"
import os
from sqlalchemy import create_engine, text
e = create_engine(os.environ['DATABASE_URL'])
with e.connect() as c:
    print('    접속 성공 · 상품', c.execute(text('SELECT COUNT(*) FROM products')).scalar(), '건')
\""; then
  echo "[4/5] 접속 확인됨 — 재기동합니다"
else
  echo
  echo "!! 접속 실패. 원래 파일로 되돌립니다."
  sudo cp -p "$BAK" "$ENVF"
  echo "   되돌렸습니다. 콘솔에서 바꾼 비밀번호가 맞는지 확인하세요."
  exit 1
fi

# 6) 재기동
sudo systemctl restart popcorn-api
sleep 5
if systemctl is-active --quiet popcorn-api; then
  echo "[5/5] popcorn-api 정상 기동"
else
  echo "!! 기동 실패 — 로그:"
  sudo journalctl -u popcorn-api -n 20 --no-pager
  exit 1
fi

echo
echo "=============================================="
echo " 서버 완료. 이제 로컬 PC 의 .env 도 바꾸세요."
echo " 백업: $BAK"
echo "=============================================="
