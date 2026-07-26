#!/usr/bin/env bash
# 팝콘PC AI — 내부 직원 베타 설치 (Ubuntu · 한 번 실행으로 끝)
#
# 실행:
#   curl 없이 그냥 붙여넣어도 되게 만들었다. GCP 콘솔의 브라우저 SSH에서:
#     sudo bash bootstrap.sh
#   또는 리포를 먼저 받은 뒤:
#     sudo bash /srv/popcorn-ai/deploy/bootstrap.sh
#
# **비밀값은 프롬프트로만 받는다** — 이 파일에도, 로그에도, 히스토리에도 남지 않는다.
# 재실행 안전(멱등): 이미 있는 것은 건드리지 않고 넘어간다.
#
# 설치하는 것: python venv · nginx(Basic Auth 봉쇄) · systemd 서비스 · 방화벽(80만)
# 자세한 배경은 deploy/README.md 참조.
set -euo pipefail

REPO="https://github.com/davidchoi2060-art/popcorn-ai.git"
APP_DIR="/srv/popcorn-ai"
ENV_FILE="/etc/popcorn-ai.env"
HTPASSWD="/etc/nginx/.htpasswd-popcorn"

# 비대화형 배포용 입력 파일(원격 실행 시). 명령줄·프로세스 목록에 비밀값을 싣지 않으려고
# 값을 파일로 받는다. 읽어 설치한 뒤 **즉시 지운다**.
#   /tmp/popcorn-ai.env : DATABASE_URL / ADMIN_BOOTSTRAP_EMAILS / COOKIE_SECURE
#   /tmp/popcorn-ba     : Basic Auth 한 줄 "아이디:비밀번호"
SEED_ENV="/tmp/popcorn-ai.env"
SEED_BA="/tmp/popcorn-ba"

say() { printf "\n\033[1;34m==> %s\033[0m\n" "$1"; }
ok()  { printf "    \033[32m[OK]\033[0m %s\n" "$1"; }

[[ $EUID -eq 0 ]] || { echo "root로 실행하세요: sudo bash $0"; exit 1; }

say "1/7 패키지"
apt-get update -qq
apt-get install -y -qq python3-venv python3-pip nginx apache2-utils git ufw curl >/dev/null
ok "python3-venv · nginx · apache2-utils · git · ufw"

say "2/7 서비스 계정"
if id popcorn &>/dev/null; then ok "popcorn 계정 이미 있음"; else
  useradd -r -m -d "$APP_DIR" -s /usr/sbin/nologin popcorn
  ok "popcorn 계정 생성"
fi

say "3/7 코드"
if [[ -d "$APP_DIR/.git" ]]; then
  sudo -u popcorn git -C "$APP_DIR" pull --ff-only
  ok "git pull"
else
  # useradd -m 이 만든 빈 홈에 clone 하려면 비어 있어야 한다
  find "$APP_DIR" -mindepth 1 -maxdepth 1 -name '.*' -exec rm -rf {} + 2>/dev/null || true
  sudo -u popcorn git clone --depth 1 "$REPO" "$APP_DIR"
  ok "git clone"
fi
if [[ ! -x "$APP_DIR/.venv/bin/python" ]]; then
  sudo -u popcorn python3 -m venv "$APP_DIR/.venv"
fi
sudo -u popcorn "$APP_DIR/.venv/bin/pip" install -q --upgrade pip
sudo -u popcorn "$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"
sudo -u popcorn mkdir -p "$APP_DIR/.cache"
ok "의존성 설치"

say "4/7 환경변수 ($ENV_FILE)"
if [[ -f "$ENV_FILE" ]]; then
  ok "이미 있음 — 값을 바꾸려면 직접 편집: sudo nano $ENV_FILE"
elif [[ -f "$SEED_ENV" ]]; then
  install -m 640 -o root -g popcorn "$SEED_ENV" "$ENV_FILE"
  shred -u "$SEED_ENV" 2>/dev/null || rm -f "$SEED_ENV"
  grep -q "^DATABASE_URL=." "$ENV_FILE" || { echo "DATABASE_URL이 비어 있습니다."; exit 1; }
  grep -q "^ADMIN_BOOTSTRAP_EMAILS=." "$ENV_FILE" || { echo "첫 관리자 이메일이 비어 있습니다."; exit 1; }
  ok "전달받은 값으로 생성(권한 640 root:popcorn) 후 씨앗 파일 삭제"
else
  echo "    Cloud SQL 접속 문자열을 붙여넣으세요."
  echo "    예: postgresql+psycopg2://USER:PASSWORD@HOST:5432/popcorn_pc?sslmode=require"
  read -rsp "    DATABASE_URL: " DB_URL; echo
  [[ -n "$DB_URL" ]] || { echo "DATABASE_URL은 필수입니다."; exit 1; }
  echo "    첫 관리자 이메일 — 이 계정만 첫 로그인 시 자동 승인됩니다(나머지는 이 계정이 승인)."
  read -rp  "    ADMIN_BOOTSTRAP_EMAILS: " BOOT
  [[ -n "$BOOT" ]] || { echo "첫 관리자가 없으면 아무도 승인할 수 없습니다."; exit 1; }
  install -m 640 -o root -g popcorn /dev/null "$ENV_FILE"
  {
    echo "DATABASE_URL=$DB_URL"
    echo "ADMIN_BOOTSTRAP_EMAILS=$BOOT"
    # HTTP로 운영하는 동안은 비워둔다 — 켜면 브라우저가 쿠키를 저장하지 않아 로그인이 안 된다.
    echo "COOKIE_SECURE="
  } > "$ENV_FILE"
  unset DB_URL
  ok "생성(권한 640, root:popcorn)"
fi

say "5/7 Basic Auth — 이것이 지금 유일한 실질 방벽입니다"
if [[ -f "$HTPASSWD" ]]; then
  ok "이미 있음 — 계정 추가: sudo htpasswd $HTPASSWD <아이디>"
elif [[ -f "$SEED_BA" ]]; then
  BAUSER="$(cut -d: -f1 "$SEED_BA")"
  BAPASS="$(cut -d: -f2- "$SEED_BA")"
  [[ -n "$BAUSER" && -n "$BAPASS" ]] || { echo "Basic Auth 값이 비었습니다."; exit 1; }
  htpasswd -bc "$HTPASSWD" "$BAUSER" "$BAPASS" >/dev/null
  unset BAPASS
  shred -u "$SEED_BA" 2>/dev/null || rm -f "$SEED_BA"
  chown root:www-data "$HTPASSWD"; chmod 640 "$HTPASSWD"
  ok "전달받은 계정으로 생성($BAUSER) 후 씨앗 파일 삭제"
else
  echo "    직원이 사이트에 들어올 때 쓸 아이디/비밀번호를 만듭니다."
  echo "    (로그인 화면이 dev 어댑터라, 이 빗장이 없으면 누구나 관리자로 들어옵니다)"
  read -rp "    아이디 [popcorn]: " BAUSER; BAUSER="${BAUSER:-popcorn}"
  htpasswd -c "$HTPASSWD" "$BAUSER"
  chown root:www-data "$HTPASSWD"; chmod 640 "$HTPASSWD"
  ok "생성"
fi

say "6/7 systemd · nginx"
cp "$APP_DIR/deploy/popcorn-api.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now popcorn-api
sleep 2
if curl -fsS --max-time 5 localhost:8000/api/health >/dev/null; then
  ok "API 기동(127.0.0.1:8000) — 외부에서 직접 접근 불가"
else
  echo "    [FAIL] API가 응답하지 않습니다. 로그: journalctl -u popcorn-api -n 50 --no-pager"
  exit 1
fi
cp "$APP_DIR/deploy/nginx-popcorn.conf" /etc/nginx/sites-available/popcorn
ln -sf /etc/nginx/sites-available/popcorn /etc/nginx/sites-enabled/popcorn
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx
ok "nginx 적용(Basic Auth 봉쇄)"

say "7/7 방화벽 · 최종 점검"
ufw allow OpenSSH >/dev/null 2>&1 || true
ufw allow 80/tcp  >/dev/null 2>&1 || true
ufw --force enable >/dev/null 2>&1 || true
ok "80·22만 허용(8000은 열지 않는다)"

# 봉쇄가 실제로 걸렸는지 확인 — 인증 없이 401이 나와야 한다
CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1/admin/login.html || echo "000")
if [[ "$CODE" == "401" ]]; then
  ok "인증 없이 접근 시 401 — 봉쇄 확인"
else
  echo "    [FAIL] 인증 없이 $CODE 가 나왔습니다. 봉쇄되지 않았으니 즉시 확인하세요."
  echo "           sudo nginx -T | grep -A3 auth_basic"
  exit 1
fi

sudo -u popcorn bash -c "set -a; . $ENV_FILE; set +a; cd $APP_DIR && .venv/bin/python deploy/preflight.py" || true

IP=$(curl -s --max-time 3 -H 'Metadata-Flavor: Google' \
     http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip \
     2>/dev/null || echo "")
echo
printf "\033[1;32m설치 완료\033[0m\n"
[[ -n "$IP" ]] && echo "  접속: http://$IP/admin/login.html" \
               || echo "  접속: http://<VM 외부 IP>/admin/login.html"
echo "  브라우저에서 Basic Auth 창이 먼저 떠야 합니다. 통과 후 첫 관리자 이메일로 로그인하세요."
echo "  로그: sudo journalctl -u popcorn-api -f"
