# 내부 직원 베타 배포 절차 (GCP VM · 외부 IP · HTTP)

> **현행(2026-07-30)**: `popcorn-app`(asia-northeast3-b) · 고정 IP `34.47.124.184`
> · Cloud SQL `popcorn-db`. 접속 **https://admin.popcornai.co.kr/admin/login.html**
> 접근 정책은 **관리자 열림 · 고객 404 차단**(§7). 재검증은 `sudo bash deploy/verify.sh`.
>
> ⚠️ 아래 §0~§6은 **최초 구축 절차**다(2026-07-26 기준, HTTP·Basic Auth 전제).
> 지금 서버는 그 상태가 아니다 — 현행 접근 정책은 **§7이 정본**이다.

**범위**: 내부 직원만 쓰는 베타. 고객은 들어오지 않는다 → 결제(PG)·통신판매업 신고·법정 표시·
택배사 연동은 이 배포의 범위가 아니다.

**최초 결정(2026-07-26)과 그 뒤 바뀐 것:**
1. ~~nginx Basic Auth로 사이트 전체를 봉쇄한다~~ → **2026-07-30 폐기.** certbot이 설정을
   고치며 `auth_basic`이 사라진 것을 발견하고, 복구 대신 **경로별 분리**를 택했다(§7).
2. ~~HTTP로 시작한다~~ → **2026-07-28 HTTPS 전환 완료**(`admin.popcornai.co.kr`).

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

## 7. HTTPS · 접근 정책 (2026-07-30 현행)

> **이 절은 이미 끝난 일을 기록한 것이다.** 새로 세우는 서버가 아니면 따라 할 것이 없다.
> 슬라이스 91에 있던 "2단계 전환 절차"는 폐기했다 — 그때 `dev.popcornai.co.kr`을
> 전제로 썼는데, 실제로는 **`admin.popcornai.co.kr`으로 7월 28일에 이미 끝나 있었다.**
> 그 절차를 그대로 따라가면 돌아가는 설정을 덮어쓴다.

### 현재 상태

| 항목 | 값 |
|---|---|
| 접속 | **https://admin.popcornai.co.kr** |
| 인증서 | Let's Encrypt (2026-07-28 발급 · 90일) |
| HTTP(80) | ACME 통로만 남기고 301 → HTTPS |
| 설정 정본 | `deploy/nginx-popcorn.conf` — **서버 실제와 일치한다** |

### 접근 정책 — 관리자는 열고 고객은 막는다 (사용자 결정 2026-07-30)

예전에는 Basic Auth가 사이트 전체를 봉쇄했다. 그런데 `certbot --nginx`가 설정을 고치는
과정에서 **`auth_basic` 지시어가 사라져** 사이트가 공개된 상태로 이틀을 보냈다.
Basic Auth 복구 대신 경로별로 나누는 쪽을 택했다.

| 대상 | 정책 | 무엇이 막는가 |
|---|---|---|
| 관리자 | **열어 둔다** | 비밀번호 인증(슬라이스 70) + `/api/admin/*` 미들웨어 게이트 |
| 고객 | **열어 둔다 (2026-08-09 개정)** | — 막는 것이 없다 |

**2026-08-09 이전에는** 아래 10경로를 nginx가 404로 막았다. 사용자 결정으로 전부 걷었다 —
베타 테스터가 실제로 AI 상담 → 견적 → 구매까지 해보게 하는 것이 지금 단계의 목적이다.

`/mvp1/` · `/api/auth/` · `/api/my/` · `/api/candidates` · `/api/recommend` ·
`/api/swap/` · `/api/orders` · `/api/ops` · `/api/showcase` · `/api/promo-click`

되돌리는 블록은 `nginx-popcorn.conf`에 **주석으로 보존**돼 있다(그대로 주석만 풀면 된다).

> ### ⚠️ 열면서 감수한 구멍 — 반드시 알고 있어야 한다
> 고객 인증은 **아직 dev 어댑터**다. `api/customer_auth.py`의 검증은
> `if "@" not in email` 한 줄이 전부이고 비밀번호도 OAuth도 인증 메일도 없다.
> **아무나 남의 이메일을 입력해 그 사람 세션을 받고, `/api/my/`로 그 사람의
> 주문·결제·환불·후기를 볼 수 있다.** 개방 시점 실회원은 6명(전부 테스트 계정).
>
> **테스터에게 실제 개인정보를 넣지 말라고 공지해야 한다.**
> 실 OAuth(카카오·네이버·구글)가 유일한 해소다 — 붙일 자리는
> `api/admin_profile.PROVIDER_KO` + `_verify_google()`.

> ### ⚠️ `/api/auth/` 와 `/api/admin/auth/` 는 다른 경로다
> nginx 접두어 매칭은 URI 시작부터 본다. `/api/admin/auth/login`은 고객 차단에 걸리지 않는다.
> 나중에 **다시 막을 때** 이 구분을 어기면 아무도 관리자로 들어올 수 없다.

다시 막을 때 **404를 쓴다(403이 아니라)** — 아직 열지 않은 것의 존재를 알리지 않는다.

설정 변경은 로컬에서 고쳐 push → 서버 pull → 아래 절차로 적용한다.
**서버에서 직접 고치지 않는다**(P-06).

### 설정을 바꾸는 절차 — **nginx 설정만** 바꿀 때

> ⚠️ **이 절차를 코드 배포에 쓰지 마라.** 여기엔 `pip install` 도 `alembic` 도 없다.
> 코드가 함께 바뀌었으면 「운영 명령 → 배포 갱신」의 한 줄을 쓴다.
> 2026-08-09 에 이 절차를 코드 배포에 오용해 사이트를 내렸다.

```bash
# 로컬에서 deploy/nginx-popcorn.conf 를 고치고 커밋·푸시한 뒤, 서버에서:
sudo cp /etc/nginx/sites-available/popcorn /etc/nginx/sites-available/popcorn.bak-$(date +%Y%m%d-%H%M%S)
sudo -u popcorn bash -c 'cd /srv/popcorn-ai && git pull --ff-only'
sudo cp /srv/popcorn-ai/deploy/nginx-popcorn.conf /etc/nginx/sites-available/popcorn
sudo nginx -t && sudo systemctl reload nginx
```

`nginx -t`가 실패하면 **reload하지 말고** 백업으로 되돌린다. 백업을 먼저 뜨는 이유다.

### 검증 (외부에서)

```bash
B=https://admin.popcornai.co.kr
curl -sI $B/admin/login.html     | head -1    # 200  관리자 화면은 열려 있다
curl -sI $B/api/admin/products   | head -1    # 401  미들웨어 게이트
curl -sI $B/mvp1/s1-session.html | head -1    # 200  고객 화면 (2026-08-09 개방)
curl -sI $B/api/showcase         | head -1    # 200  고객 API  (2026-08-09 개방)
curl -sI $B/api/health           | head -1    # 200  감시용
sudo certbot renew --dry-run                  # 90일 뒤 조용한 만료를 막는 유일한 검사
```

> **관리자 로그인을 비밀번호 없이 두 번 이상 시도하면 계정이 15분 잠긴다**(슬라이스 70).
> 검증하다 시드 owner를 잠근 적이 있다 — 잠겼으면 `login_fail_count=0, locked_until=NULL`로
> 풀거나 15분을 기다린다.

### 인증서 갱신

certbot이 systemd 타이머로 자동 갱신한다. 80의 `/.well-known/acme-challenge/`가 막히면
**90일 뒤 조용히 만료된다** — 그 location을 지우지 않는다.

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

### 배포 갱신 — 이 한 줄을 쓴다

```bash
sudo -u popcorn bash -c 'cd /srv/popcorn-ai && git pull --ff-only && .venv/bin/pip install -q -r requirements.txt && set -a && . /etc/popcorn-ai.env && set +a && cd db && ../.venv/bin/python -m alembic upgrade head' && sudo systemctl restart popcorn-api && sleep 3 && systemctl is-active popcorn-api
```

**한 줄로 묶은 이유(2026-08-09 실사고):** 예전에는 네 줄짜리 순서였는데, `git pull` 과
`systemctl restart` 만 쓰고 **`pip install` 을 건너뛴 채 배포해 사이트를 내렸다.**
`requirements.txt` 에 `Jinja2` 를 새로 넣은 배포였고, 앱이 import 단계에서 죽어
systemd 가 재시작을 무한 반복했다:

```
ImportError: jinja2 must be installed to use Jinja2Templates
```

`&&` 로 묶으면 **건너뛸 수 없고**, 앞 단계가 실패하면 뒤가 아예 안 돈다.
`requirements.txt` 가 안 바뀌었으면 pip 은 몇 초에 끝나므로 **항상 넣어도 손해가 없다.**

> **§7의 nginx 명령을 코드 배포에 쓰지 마라.** 그것은 설정 파일만 갈아끼우는
> 절차라 `pip install` 도 `alembic` 도 없다. 오늘의 사고가 정확히 그 오용이었다.

**배포 후 확인** — `is-active` 가 `active` 여야 한다. `activating` 이 계속 뜨면
크래시 루프다. 원인은 로그에 있다:

```bash
sudo journalctl -u popcorn-api -n 30 --no-pager
```

## 남아 있는 위험 (베타에서 감수하는 것 · 정직 기록)

| 위험 | 지금 상태 | 해소 조건 |
|---|---|---|
~~평문 통신~~ | **해소(2026-07-28)** — HTTPS 전환 완료 | — |
| 고객 인증 dev 어댑터 | `"@" in email`이 전부 — nginx가 고객 경로를 404로 막고 있다(§7) | 실 OAuth |
신원 확인 | dev 어댑터(입력 이메일을 신뢰) — Basic Auth가 유일한 실질 방벽 | 실 OAuth 연동 |
로그인 시도 제한 | 없음 | fail2ban 또는 앱 레벨 제한 |
고객 축 | 코드는 있지만 베타에서 쓰지 않는다 | 고객 오픈은 별도 결정 |

## ⚠ 운영 서버에 절대 넣지 않는 환경변수

`UI_CHECK_DEV_LOGIN` — **비밀번호 없이 관리자 세션을 심는다.** 화면을 브라우저로
점검할 때만 쓰는 개발 전용 스위치다(`GET /api/admin/auth/dev-login`).

세 겹으로 막혀 있지만 **첫 겹이 곧 마지막 겹이다**:

  ① 이 환경변수가 켜져 있을 때만 동작한다 (없으면 404)
  ② localhost 요청만 받는다 (원격은 403)
  ③ `UI_CHECK_EMAIL` 계정이 활성일 때만

`/etc/popcorn-ai.env` 에 이 이름이 나타나면 **즉시 지우고 서비스를 재시작한다.**
확인:

```bash
sudo grep -c UI_CHECK_DEV_LOGIN /etc/popcorn-ai.env    # 0 이어야 한다
```

같은 이유로 `UI_CHECK_EMAIL`·`UI_CHECK_PW` 도 운영에 두지 않는다
(CLAUDE.md 「브라우저 점검 계정」 — 개발 서버 전용).

`POPCORN_TEST_HEADER_ENABLED` — **회귀(`tests/regression.py`)가 만든 요청을
`consult_sessions.data_origin='test'`로 표시하게 여는 스위치다.** 로컬 API가
배포 서버와 같은 Cloud SQL을 보므로, 이 스위치가 꺼져 있으면(운영 기본값)
회귀성 요청도 전부 `'real'`로 남는다 — 반대로 개발 PC에서 이 값을 켜지 않은
채 회귀를 돌리면 실제 상담 원장이 오염된다(2026-08-20 발견 당시
`consult_sessions` 6,893건 중 6,732건(97.7%)이 이렇게 섞여 있었다 — 경위·
처방은 `docs/decisions/decision-log.md` **A-75**).

두 겹으로 막혀 있다:

  ① 이 환경변수가 켜져 있을 때만 헤더를 신뢰한다 (기본 꺼짐)
  ② `X-Popcorn-Test` 헤더 + **localhost 요청만** — 인터넷의 실고객 요청은
     nginx 뒤에서 이미 실제 클라이언트 IP로 바뀌므로 "localhost"로 보일 수 없다
     (`api/recommend.py`의 `_resolve_data_origin` 참조)

**운영에 켜면 안 되는 이유는 `UI_CHECK_DEV_LOGIN`과 다르다** — 이 스위치
자체는 관리자 권한을 열지 않는다. 대신 **운영 박스 안에서 loopback으로 API를
두드리는 내부 프로세스**(헬스체크·크론 등)가 실고객 세션을 `'test'`로 표시해,
그 세션이 대시보드·퍼널·인계 원장에서 조용히 빠지는 경로를 연다 — 지금 겪은
사고와 반대 방향(진짜인데 가짜로 표시됨)이다. `/etc/popcorn-ai.env`에 이
이름이 나타나면 즉시 지우고 서비스를 재시작한다. 확인:

```bash
sudo grep -c POPCORN_TEST_HEADER_ENABLED /etc/popcorn-ai.env    # 0 이어야 한다
```
