# 내부 직원 베타 배포 절차 (GCP VM · 외부 IP · HTTP)

**범위**: 내부 직원만 쓰는 베타. 고객은 들어오지 않는다 → 결제(PG)·통신판매업 신고·법정 표시·
택배사 연동은 이 배포의 범위가 아니다.

**두 가지 결정**(2026-07-26, 사용자):
1. **nginx Basic Auth로 사이트 전체를 봉쇄한다.** 지금 로그인은 dev 어댑터(입력 이메일을
   신원으로 신뢰)라, 앱이 그대로 노출되면 누구나 승인된 관리자 이메일을 입력해 들어올 수 있다.
   Basic Auth가 그 앞을 막는다. 실 OAuth 연동이 끝나면 걷어낼 수 있다.
2. **HTTP로 시작한다**(도메인 없음). 같은 망을 쓰는 상대는 Basic Auth 비밀번호와 세션 쿠키를
   가로챌 수 있다 — 이건 감수하는 위험이고, 도메인 확보 후 §7로 전환한다.

---

## 0. 준비물 (사용자가 준비 · 리포에 저장하지 않는다)

| 항목 | 비고 |
|---|---|
VM 외부 IP · SSH 접속 | GCP 콘솔에서 확인 |
Basic Auth 계정 | 아래 §3에서 서버에서 직접 생성 |
`DATABASE_URL` | Cloud SQL 접속 문자열(로컬 `.env`와 같은 값) |
`ADMIN_BOOTSTRAP_EMAILS` | 첫 관리자 이메일 1개 — 이 계정만 자동 승인된다 |

**비밀값은 이 리포에 절대 커밋하지 않는다.** 서버의 `/etc/popcorn-ai.env`(권한 600)에만 둔다.

---

## 1. VM 기본 (Ubuntu 기준)

```bash
sudo apt update && sudo apt install -y python3-venv nginx apache2-utils git ufw
sudo useradd -r -m -d /srv/popcorn-ai -s /usr/sbin/nologin popcorn
```

방화벽 — **80만 열고 8000은 절대 열지 않는다**(앱은 127.0.0.1에만 바인드하지만 이중으로 막는다):

```bash
sudo ufw allow OpenSSH && sudo ufw allow 80/tcp && sudo ufw --force enable
```

GCP 방화벽 규칙에서도 tcp:80과 22만 허용한다(콘솔 → VPC 네트워크 → 방화벽).

## 2. 코드 배치

```bash
sudo -u popcorn git clone https://github.com/davidchoi2060-art/popcorn-ai.git /srv/popcorn-ai
cd /srv/popcorn-ai && sudo -u popcorn python3 -m venv .venv
sudo -u popcorn .venv/bin/pip install -r requirements.txt
sudo -u popcorn mkdir -p /srv/popcorn-ai/.cache
```

환경변수 파일 — **이 명령을 그대로 붙이지 말고 값을 채워서** 실행한다:

```bash
sudo install -m 600 -o root -g popcorn /dev/null /etc/popcorn-ai.env
sudo nano /etc/popcorn-ai.env
```

```
DATABASE_URL=postgresql+psycopg2://<user>:<password>@<host>:5432/popcorn_pc
ADMIN_BOOTSTRAP_EMAILS=<첫 관리자 이메일>
COOKIE_SECURE=
```

`COOKIE_SECURE`는 **HTTP인 동안 비워둔다**(켜면 브라우저가 쿠키를 저장하지 않아 로그인이 안 된다).

## 3. Basic Auth 계정 생성

```bash
sudo htpasswd -c /etc/nginx/.htpasswd-popcorn popcorn
```

비밀번호를 물으면 직원 공용 비밀번호를 입력한다. 직원별로 나누려면 `-c` 없이 반복 실행한다.
파일 권한:

```bash
sudo chown root:www-data /etc/nginx/.htpasswd-popcorn && sudo chmod 640 /etc/nginx/.htpasswd-popcorn
```

## 4. 서비스 등록

```bash
sudo cp /srv/popcorn-ai/deploy/popcorn-api.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now popcorn-api
sudo systemctl status popcorn-api --no-pager
curl -s localhost:8000/api/health          # {"ok":true}
```

## 5. nginx

```bash
sudo cp /srv/popcorn-ai/deploy/nginx-popcorn.conf /etc/nginx/sites-available/popcorn
sudo ln -sf /etc/nginx/sites-available/popcorn /etc/nginx/sites-enabled/popcorn
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

확인 — 브라우저에서 `http://<VM 외부 IP>/admin/login.html`. Basic Auth 창이 먼저 떠야 한다.
**뜨지 않으면 봉쇄가 안 된 것이니 즉시 중단하고 §5를 다시 본다.**

## 6. 데이터 · 첫 로그인

DB는 이미 Cloud SQL에 있으므로 마이그레이션만 맞춘다(적재는 로컬에서 이미 완료 — products 22,838):

```bash
cd /srv/popcorn-ai/db && sudo -u popcorn ../.venv/bin/python -m alembic current
```

첫 관리자는 `ADMIN_BOOTSTRAP_EMAILS`에 넣은 이메일로 `admin/login.html`에서 로그인하면 자동
승인된다. 나머지 직원은 같은 화면에서 신청하고, 관리자가 **운영자·권한** 화면에서 승인한다.

## 7. 도메인 확보 후 HTTPS 전환

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d <도메인>
```

그다음 `/etc/popcorn-ai.env`에 `COOKIE_SECURE=1`을 넣고 `sudo systemctl restart popcorn-api`.
이 값 하나로 세션 쿠키가 HTTPS 전용이 된다(코드 수정 없음).

---

## 백업 — 미룰 수 없는 항목

직원이 검수 확정·가격 승인·입고를 시작하면 **그 순간부터 원장이 쌓인다.** 되돌림도 역방향
행으로 흔적을 남기는 설계라 "없던 일"로 만들 수 없다.

1. Cloud SQL 자동 백업이 켜져 있는지 확인(콘솔 → SQL → 인스턴스 → 백업). 보관 7일 이상 권장.
2. **복구 리허설 1회**를 베타 시작 전에 한다 — 백업에서 복원 인스턴스를 만들어 `products`
   건수와 `product_reviews` 대기 건수가 맞는지 확인하고 지운다. 해보지 않은 백업은 백업이 아니다.
3. 데모/실데이터는 `data_origin`으로 구분된다 — 복구 후에도 이 값으로 검증한다.

## 운영 명령

```bash
sudo systemctl restart popcorn-api          # 재시작
sudo journalctl -u popcorn-api -f           # 로그 실시간
sudo journalctl -u popcorn-api --since '10 min ago' -p err   # 에러만
```

배포 갱신:

```bash
cd /srv/popcorn-ai && sudo -u popcorn git pull
sudo -u popcorn .venv/bin/pip install -r requirements.txt
cd db && sudo -u popcorn ../.venv/bin/python -m alembic upgrade head
sudo systemctl restart popcorn-api
```

## 남아 있는 위험 (베타에서 감수하는 것 · 정직 기록)

| 위험 | 지금 상태 | 해소 조건 |
|---|---|---|
평문 통신 | HTTP — Basic Auth 비밀번호·세션 쿠키가 망에서 보인다 | 도메인 + §7 |
신원 확인 | dev 어댑터(입력 이메일을 신뢰) — Basic Auth가 유일한 실질 방벽 | 실 OAuth 연동 |
로그인 시도 제한 | 없음 | fail2ban 또는 앱 레벨 제한 |
고객 축 | 코드는 있지만 베타에서 쓰지 않는다 | 고객 오픈은 별도 결정 |
