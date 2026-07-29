# 내부 직원 베타 배포 절차 (GCP VM · 외부 IP · HTTP)

> **배포 완료(2026-07-26)**: `popcorn-app`(asia-northeast3-b) · 고정 IP `34.47.124.184`
> · Cloud SQL `popcorn-db`. 접속 `http://34.47.124.184/admin/login.html`
> 검증: 미인증 401 · `:8000` 직접 불가 · Basic Auth 통과 시 200 ·
> 상품 22,838건 · 검수 7,415건 · S1 후보 3,046 · 추천(100만) 1,000,000.
> 재검증은 `sudo bash deploy/verify.sh`.

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

**비밀값은 이 리포에 절대 커밋하지 않는다.** 서버의 `/etc/popcorn-ai.env`(권한 640 root:popcorn)에만 둔다 — systemd는 root로 읽고, 앱 계정은 그룹 읽기로 읽는다(600으로 두면 popcorn 계정이 도는 진단 스크립트가 읽지 못한다 — 실제 배포에서 겪음).

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
sudo install -m 640 -o root -g popcorn /dev/null /etc/popcorn-ai.env
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

> 서버와 로컬이 **같은 Cloud SQL**을 본다 — 로컬에서 마이그레이션을 이미 적용했다면
> 서버에서 다시 돌릴 필요가 없다. 확인만 한다(아래). alembic은 환경변수가 필요하므로
> `/etc/popcorn-ai.env`를 먼저 읽어야 한다(그냥 실행하면 DATABASE_URL 오류).


DB는 이미 Cloud SQL에 있으므로 마이그레이션만 맞춘다(적재는 로컬에서 이미 완료 — products 22,838):

```bash
sudo -u popcorn bash -c 'set -a; . /etc/popcorn-ai.env; set +a; cd /srv/popcorn-ai/db && ../.venv/bin/python -m alembic current'
```

첫 관리자는 `ADMIN_BOOTSTRAP_EMAILS`에 넣은 이메일로 `admin/login.html`에서 로그인하면 자동
승인된다. 나머지 직원은 같은 화면에서 신청하고, 관리자가 **운영자·권한** 화면에서 승인한다.

## 7. HTTPS 전환 (슬라이스 91)

> **이 서버는 개발/스테이징이다**(decision-log I-01). 도메인은 **`dev.popcornai.co.kr`**을 쓴다 —
> 정본 `popcornai.co.kr`은 운영 서버 몫으로 남겨 둔다. 정본을 여기 붙였다가 옮기면
> 인증서·OAuth 리다이렉트 URI·쿠키를 전부 다시 손봐야 한다.

**끝나는 것:** 관리자 비밀번호(슬라이스 70)·Basic Auth 비밀번호·세션 쿠키의 평문 전송.
**끝나지 않는 것:** 누가 들어오는가. HTTPS는 전송 구간만 지킨다 — Basic Auth는 그대로 둔다.

### 0) 선행 — DNS (가비아, 사용자 작업)

| 호스트 | 타입 | 값 |
|--------|------|-----|
| `dev` | A | `34.47.124.184` |

`@`(popcornai.co.kr 자체)는 **비워 둔다**(운영 몫). 전파 확인:

```bash
nslookup -type=A dev.popcornai.co.kr 8.8.8.8
```

### 1) 1단계 설정 적용 — ACME 통로를 연다

`nginx-popcorn.conf`에 `/.well-known/acme-challenge/`만 Basic Auth를 우회하는 블록이 있다.
**이게 없으면 Let's Encrypt가 401을 받아 발급이 실패한다.**

```bash
sudo mkdir -p /var/www/certbot
sudo cp /srv/popcorn-ai/deploy/nginx-popcorn.conf /etc/nginx/sites-available/popcorn
sudo nginx -t && sudo systemctl reload nginx
```

통로가 열렸는지 **발급 전에** 확인한다 — 시험 파일을 놓고 밖에서 읽어본다:

```bash
sudo mkdir -p /var/www/certbot/.well-known/acme-challenge
echo ok | sudo tee /var/www/certbot/.well-known/acme-challenge/test
curl -s -o /dev/null -w '%{http_code}\n' http://dev.popcornai.co.kr/.well-known/acme-challenge/test
sudo rm /var/www/certbot/.well-known/acme-challenge/test
```

`200`이면 통과. **`401`이면 Basic Auth가 아직 막고 있는 것이니 여기서 멈춘다** — 그대로
발급을 시도하면 실패하고, Let's Encrypt는 같은 도메인에 실패 횟수 제한을 건다.

### 2) 인증서 발급 — `--webroot`를 쓴다

```bash
sudo apt install -y certbot
sudo certbot certonly --webroot -w /var/www/certbot -d dev.popcornai.co.kr
```

**`--nginx`가 아니라 `--webroot`인 이유:** `--nginx`는 설정 파일을 직접 고친다. 서버에서 고쳐지면
리포 사본과 갈라지고 **다음 배포가 그걸 덮어쓴다**(P-06 — 서버는 배포 타깃이다).
`--webroot`는 설정에 손대지 않고 우리가 열어둔 경로에 파일만 놓는다.

### 3) 2단계 설정으로 교체

```bash
sudo cp /srv/popcorn-ai/deploy/nginx-popcorn-tls.conf /etc/nginx/sites-available/popcorn
sudo nginx -t && sudo systemctl reload nginx
```

**같은 자리를 덮어쓴다.** 두 파일을 동시에 enabled로 두면 `default_server`가 충돌한다.

### 4) 쿠키를 HTTPS 전용으로

```bash
echo 'COOKIE_SECURE=1' | sudo tee -a /etc/popcorn-ai.env
sudo systemctl restart popcorn-api
```

코드 수정 없이 환경변수 하나다. **이걸 빼먹으면** 세션 쿠키가 계속 평문 경로로도 나가서
2단계의 이득이 절반만 남는다.

### 5) 검증

```bash
curl -sI http://dev.popcornai.co.kr/admin/login.html | head -1        # 301
curl -sI https://dev.popcornai.co.kr/admin/login.html | head -1       # 401 (Basic Auth = 봉쇄 살아있음)
curl -s https://dev.popcornai.co.kr/api/health                        # 인증 없이 통과
sudo certbot renew --dry-run                                          # 갱신 경로 확인
```

`https`에서 **401이 떠야 정상**이다. 200이면 봉쇄가 풀린 것이니 즉시 중단한다(§5를 다시 본다).
`renew --dry-run`은 90일 뒤 조용한 만료를 막는 유일한 검사다 — 건너뛰지 않는다.

### 되돌리기

`nginx-popcorn.conf`를 다시 덮어쓰고 reload하면 1단계로 돌아간다. 인증서는 남아 있으므로
재발급 없이 다시 3)으로 갈 수 있다. `COOKIE_SECURE`는 함께 빼야 한다(HTTP에서 켜두면 로그인이 안 된다).

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
sudo -u popcorn bash -c 'set -a; . /etc/popcorn-ai.env; set +a; cd /srv/popcorn-ai/db && ../.venv/bin/python -m alembic upgrade head'
sudo systemctl restart popcorn-api
```

## 남아 있는 위험 (베타에서 감수하는 것 · 정직 기록)

| 위험 | 지금 상태 | 해소 조건 |
|---|---|---|
평문 통신 | HTTP — Basic Auth 비밀번호·세션 쿠키가 망에서 보인다 | 도메인 + §7 |
신원 확인 | dev 어댑터(입력 이메일을 신뢰) — Basic Auth가 유일한 실질 방벽 | 실 OAuth 연동 |
로그인 시도 제한 | 없음 | fail2ban 또는 앱 레벨 제한 |
고객 축 | 코드는 있지만 베타에서 쓰지 않는다 | 고객 오픈은 별도 결정 |
