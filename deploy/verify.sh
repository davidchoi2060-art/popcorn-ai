#!/usr/bin/env bash
# 배포 후 동작 검증 — 서버에서 실행한다.
#   sudo bash /srv/popcorn-ai/deploy/verify.sh
#
# nginx를 우회해 127.0.0.1:8000으로 직접 확인한다(Basic Auth 없이). 봉쇄 자체는
# bootstrap.sh가 이미 401로 검증했고, 여기서는 **앱과 DB가 실제로 물려 있는지**를 본다.
set -uo pipefail
API="http://127.0.0.1:8000"
JQ() { python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }

echo "=== 1. 서비스 ==="
systemctl is-active popcorn-api
curl -s --max-time 10 "$API/api/health"; echo

echo "=== 2. 봉쇄(nginx 경유, 인증 없이) ==="
printf "  /admin/products.html -> "
curl -s -o /dev/null -w '%{http_code}\n' --max-time 10 http://127.0.0.1/admin/products.html
printf "  /api/health(예외 허용) -> "
curl -s -o /dev/null -w '%{http_code}\n' --max-time 10 http://127.0.0.1/api/health

echo "=== 3. 관리자 로그인(부트스트랩 계정) ==="
BOOT=$(sudo grep '^ADMIN_BOOTSTRAP_EMAILS=' /etc/popcorn-ai.env | cut -d= -f2- | cut -d, -f1)
echo "  계정: $BOOT"
curl -s --max-time 30 -c /tmp/pcck -X POST -H 'Content-Type: application/json' \
     -d "{\"email\":\"$BOOT\",\"provider\":\"dev\"}" "$API/api/admin/auth/login" \
  | JQ '"state=" + str(d.get("state")) + " role=" + str((d.get("operator") or {}).get("role"))'

echo "=== 4. 실데이터(관리자 API) ==="
curl -s --max-time 120 -b /tmp/pcck "$API/api/admin/products?page=1&size=1" \
  | JQ '"상품 " + format(d["total"], ",") + "건 · KPI " + str(d["kpis"]) + " · 첫 행 " + d["items"][0]["sku"]'
curl -s --max-time 120 -b /tmp/pcck "$API/api/admin/reviews?page=2&size=1" \
  | JQ '"검수 대기 " + format(d["total"], ",") + "건"'

echo "=== 5. 견적 엔진(게스트 경로) ==="
curl -s --max-time 120 -X POST -H 'Content-Type: application/json' \
     -d '{"constraints":[]}' "$API/api/candidates/count" \
  | JQ '"S1 후보 " + format(d["total"], ",") + "건"'
curl -s --max-time 180 -X POST -H 'Content-Type: application/json' \
     -d '{"mode":"guided","constraints":[{"l":"용도","v":"게임"},{"l":"예산","v":"100만원"}]}' \
     "$API/api/recommend" \
  | JQ '"가성비 " + format(d["sets"]["value"]["total"], ",") + " · 추천 " + format(d["sets"]["recommend"]["total"], ",") + " · 호환 " + str(len(d["sets"]["recommend"]["compat"]["checks"])) + "종 전부통과=" + str(all(c["pass"] for c in d["sets"]["recommend"]["compat"]["checks"]))'

echo "=== 6. 고객 경계(미인증) ==="
printf "  /api/my/orders -> "
curl -s -o /dev/null -w '%{http_code}\n' --max-time 15 "$API/api/my/orders"

shred -u /tmp/pcck 2>/dev/null || true
echo "=== 검증 끝 ==="
