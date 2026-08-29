# 내부 직원 베타 배포 절차 (GCP VM · 외부 IP · HTTP)

> **현행(2026-07-30, 접속 주소·접근 정책은 2026-08-17·08-09 갱신 반영 — 아래)**:
> `popcorn-app`(asia-northeast3-b) · 고정 IP `34.47.124.184` · Cloud SQL `popcorn-db`.
> 접속 **https://admin.popcornai.co.kr/admin2/login**(구 `/admin/login.html`은
> 2026-08-14~17 admin2 이전으로 410 Gone — §검증 참조). 접근 정책은 **관리자·고객
> 모두 열어 둔다**(2026-08-09 개정 — §7). 재검증은 `sudo bash deploy/verify.sh`.
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

### 접근 정책 — 관리자·고객 모두 연다 (2026-07-30 결정 · 2026-08-09 고객 축 개정)

> ⚠️ 이 절 제목은 원래 "관리자는 열고 고객은 막는다"였다 — **2026-08-09에 고객 경로도
> 열렸는데(바로 아래 표) 제목이 그 갱신을 안 따라가 11일 넘게 자기모순 상태였다**
> (기록자 2026-08-20 발견·정정). 아래 본문·표는 그때도 맞았다 — 제목만 낡아 있었다.

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

> ⚠️ **이 다섯 줄을 문자 그대로 반복 돌리면 매번 3/5가 "실패"로 보인다** — 그런데
> 그 3줄은 오늘 배포가 깬 것이 아니라 **원래 그렇게 응답하는 것이 정상**이다(2026-08-20
> 확인자 실측 — 배포와 무관하게 로컬 개발 서버에서도 똑같이 재현된다). 아래 개별
> 설명대로 기대값을 맞춰 읽지 않으면 ① 진짜 회귀가 나도 "원래 이렇다"고 넘기거나
> ② 반대로 정상 상태를 배포 사고로 오인하게 된다.

```bash
B=https://admin.popcornai.co.kr
curl -sI $B/admin/login.html     | head -1    # 410  구 화면 — 아래 설명, 200 이면 오히려 의심
curl -sI $B/api/admin/products   | head -1    # 401  미들웨어 게이트
curl -sI $B/mvp1/s1-session.html | head -1    # 200  고객 화면(2026-08-09 개방) — StaticFiles
                                               #      마운트라 HEAD 도 정상 지원된다(아래 설명)
curl -s -o /dev/null -w '%{http_code}\n' $B/api/showcase   # 200  고객 API(2026-08-09 개방) — HEAD 아닌 GET 으로 잰다(아래 설명)
curl -s -o /dev/null -w '%{http_code}\n' $B/api/health     # 200  감시용 — 위와 같은 이유로 GET
sudo certbot renew --dry-run                  # 90일 뒤 조용한 만료를 막는 유일한 검사
```

**`/admin/login.html`은 410이 정상이다.** 2026-08-14~17 커밋으로 구 관리자 로그인
화면을 admin2로 옮기며 의도적으로 치웠다(`api/main.py`의 `_ADMIN_LEGACY_GONE_HTML`·
`_legacy_admin_page_gone` — 본문이 "이 화면은 admin2로 이전되었습니다"라고 스스로
말한다). 지금 관리자 화면은 `$B/admin2/login`에서 연다(위 §「현행」 배너도 이 주소로
고쳤다). **이 줄이 200을 돌려주면 좋은 신호가 아니라 이 라우트가 되살아났거나 뭔가
바뀐 것**이니 그때 의심한다.

**`/api/showcase`·`/api/health`는 `curl -sI`(HEAD)를 쓰면 안 된다.** 이 둘은
`@app.get(...)`로만 등록됐고, FastAPI/Starlette는 그렇게 등록한 라우트에 HEAD를
자동으로 얹지 않는다 — HEAD가 자동으로 되는 것은 `StaticFiles` 마운트뿐이다(바로 위
`/mvp1/s1-session.html`이 HEAD에도 200인 이유가 그것이다 — 정적 파일 마운트를 거친다).
**이 문제는 오늘 배포와 무관한 프레임워크 특성이라 로컬 개발 서버에서도 똑같이
재현된다.** GET으로 상태코드만 받으면(`-o /dev/null -w '%{http_code}'`) 정상 200이다.

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

## 다나와 시세 재수집 타이머 (A-109 차등 주기 · 2026-08-23)

> 시세(GPU·CPU·CPU쿨러 등)는 자주 바뀌고 비활성 부품(MB·RAM 등)은 거의 안 바뀐다는
> 실측(decision-log **A-111**의 실행 수단, A-109)에 따라 **부품 종류별로 재수집
> 주기를 가른다.** 이 절은 `deploy/systemd/`의 unit 세 개를 서버에 앉히는 절차다.
> **서버에서 직접 만들거나 고치지 않는다**(P-06) — 리포에서 고쳐 push 하고 서버는
> 받기만 한다. 부품 묶음 정의(fast=GPU·CPU·CPU쿨러 공랭/수랭, slow=MB·RAM·SSD·HDD·
> 케이스·파워)는 여기 다시 적지 않는다 — 단일 원천은 `tools/danawa_fetch.py`의
> `PART_GROUPS`다.

파일 셋(템플릿 서비스 하나 + 타이머 둘):

| 파일 | 역할 |
|---|---|
| `deploy/systemd/popcorn-danawa-market@.service` | 템플릿. 인스턴스 `%i`가 `fast`\|`slow` — `tools/danawa_fetch.py --market --group %i --limit 5000`을 실행 |
| `deploy/systemd/popcorn-danawa-market-fast.timer` | 주 1회(매주 월요일 05:00 KST) — `@fast.service` 실행 |
| `deploy/systemd/popcorn-danawa-market-slow.timer` | 월 1회(매월 1일 01:00 KST) — `@slow.service` 실행 |

### 설치

```bash
sudo install -m 644 /srv/popcorn-ai/deploy/systemd/popcorn-danawa-market@.service /etc/systemd/system/
sudo install -m 644 /srv/popcorn-ai/deploy/systemd/popcorn-danawa-market-fast.timer /etc/systemd/system/
sudo install -m 644 /srv/popcorn-ai/deploy/systemd/popcorn-danawa-market-slow.timer /etc/systemd/system/
sudo systemctl daemon-reload
```

**설치 전에 시각 표기부터 검증한다** — `Asia/Seoul` 시간대 접미사가 이 서버
systemd(255)에서 실제로 원하는 대로 해석되는지 확인한다:

```bash
systemd-analyze calendar 'Mon *-*-* 05:00:00 Asia/Seoul'   # fast — 다음 월요일 05:00 KST가 나와야 한다
systemd-analyze calendar '*-*-01 01:00:00 Asia/Seoul'      # slow — 다음 달 1일 01:00 KST가 나와야 한다
```

`Next elapse`가 기대한 KST 요일·시각과 다르거나 명령 자체가 오류를 내면, 각
`.timer` 파일 안에 주석으로 이미 적어 둔 **UTC 대체 줄**로 바꾼다(파일 안에 위치·값이
있다) — 바꾼 뒤 **같은 명령으로 다시 검증**하고서 설치한다.

### 활성화 · 다음 실행 시각 확인

```bash
sudo systemctl enable --now popcorn-danawa-market-fast.timer
sudo systemctl enable --now popcorn-danawa-market-slow.timer
sudo systemctl list-timers 'popcorn-danawa*'
```

`list-timers`의 `NEXT` 열이 위 `systemd-analyze calendar` 결과와 같은 시각을
가리키는지 대조한다. `popcorn-danawa-market@.service` 자체는 `enable`하지 않는다
— 활성화 대상은 두 `.timer`뿐이다(서비스는 [Install]이 없다).

### 수동 1회 실행 · 로그 확인

> ⚠️ **첫 실행은 서버 캐시가 0건이라 전량 새로 수집한다.** 로컬 PC 캐시(3,631건·
> 540MB)는 이 서버에 없다 — `fetch()`가 매 상품마다 실제로 다나와에 요청을 보낸다.
> fast(대상 999건)는 약 37분, slow(대상 2,632건)는 약 96분 걸린다(2026-08-23
> 하네스 실측 — 대상 건수는 카탈로그가 늘면 따라 늘고, 그러면 소요 시간도 늘어난다).
> 타이머를 기다리지 않고 손으로 한 번 돌려 실제로 끝까지 도는지 먼저 확인하는
> 편이 안전하다.

```bash
# 서비스를 직접 지정해서 지금 바로 한 번 돌린다(인스턴스명 필수 — 템플릿 자체는 못 돌린다)
sudo systemctl start popcorn-danawa-market@fast.service
sudo journalctl -u popcorn-danawa-market@fast.service -f
```

```bash
sudo systemctl start popcorn-danawa-market@slow.service
sudo journalctl -u popcorn-danawa-market@slow.service -f
```

`-f`는 실시간 추적이라 fast는 최대 약 37분, slow는 최대 약 96분 터미널을 붙잡는다
— **계속 붙잡지 말고** `Ctrl+C`로 빠져나온 뒤 나중에 다시 확인해도 된다:

```bash
systemctl status popcorn-danawa-market@fast.service --no-pager      # 마지막 실행 결과(성공/실패)
sudo journalctl -u popcorn-danawa-market@fast.service --since '2 hour ago'
```

### 끄는 법 · 되돌리는 법

```bash
sudo systemctl disable --now popcorn-danawa-market-fast.timer
sudo systemctl disable --now popcorn-danawa-market-slow.timer
```

타이머만 끄면 **다음 예정 실행이 없어질 뿐**, 이미 끝난 수집(제안·자동 승인된 시세)은
그대로 남는다 — 되돌리려면 `product_reviews`·`products.market_price`를 원장 규약대로
손으로 되돌려야 하고, 이 unit 자체에는 되돌림 기능이 없다. unit 파일까지 걷으려면:

```bash
sudo rm /etc/systemd/system/popcorn-danawa-market-fast.timer \
        /etc/systemd/system/popcorn-danawa-market-slow.timer \
        /etc/systemd/system/popcorn-danawa-market@.service
sudo systemctl daemon-reload
```

### 실패 확인 — 이제 능동 알림이 있다 (U-57 해소, 절차는 아래 §「실패 알림」)

타이머·서비스가 실패하면 **journald에는 남는다** — `systemctl status
popcorn-danawa-market@fast.service`가 `failed`를 보여주고, `SyslogIdentifier=
popcorn-danawa-%i` 덕에 `journalctl -t popcorn-danawa-fast`(또는 `-slow`)로도 찾을
수 있다(이건 전부터 있던 방법이다). **여기에 더해**, 이 unit에 `OnFailure=`를
걸어 실패하면 텔레그램으로도 능동적으로 알린다 — 설치 · 시험 절차는 바로 아래
「실패 알림 (OnFailure — U-57 해소)」 절 참조. **이 unit 하나에만 국한된 배선이
아니다** — 같은 방식으로 다른 unit도 붙일 수 있게 템플릿으로 만들었다.

## 실패 알림 (OnFailure — U-57 해소 · 2026-08-23 결정 · 2026-08-24 구현)

> 배경: A-111로 다나와 재수집을 systemd timer로 걸면서, "**어디서** 도는지"는
> 정해졌지만 "**실패하면 누가 아는지**"는 미정으로 남았다(`docs/decisions/decision-log.md`
> **U-57**) — 실패해도 journald에만 남고 아무에게도 안 갔다. 이 절이 그 해소다.

어떤 systemd unit이든 `OnFailure=`로 이 알림 unit을 걸면, 실패 시 최근 로그
20줄과 함께 텔레그램으로 알린다. 지금 실제로 연결된 것은
`popcorn-danawa-market@.service`(fast·slow 두 인스턴스) 하나뿐이다.

| 파일 | 역할 |
|---|---|
| `deploy/systemd/popcorn-notify-failure@.service` | 알림 템플릿. `%i`(반드시 `%i` — `%I`는 안 된다, 아래 참조)로 "실패한 unit 식별자"를 받아 `scripts/notify_failure.py`를 실행 |
| `scripts/notify_failure.py` | journalctl로 마지막 로그를 뽑고, `scripts/notify_telegram.py`(기존 스크립트를 그대로 재사용 — 다시 구현하지 않는다)로 전송 |
| `deploy/systemd/popcorn-danawa-market@.service` | (기존 파일 수정) `[Unit]`에 `OnFailure=popcorn-notify-failure@%p-%i.service` 한 줄 추가 |

**왜 `%n`이 아니라 `%p-%i`인가** — `popcorn-danawa-market@fast.service`처럼
실패하는 unit 자신이 이미 `@`를 포함한 템플릿 인스턴스이면, 그 전체 이름을
그대로 다른 unit의 인스턴스 자리에 넣을 수 없다(systemd 유닛 이름의 인스턴스
부분은 `@` 문자를 허용하지 않는다 — `systemd-escape(1)` 기준 안전 문자는
글자·숫자·`:`·`_`·`.`·`-`뿐이고 `@`는 escape 대상이다). `@%n.service`로 그대로
쓰면 전개 결과에 `@`가 두 번 들어가 인스턴스 이름이 무효가 되고, systemd는 그
`OnFailure=` 의존성 자체를 **조용히** 버린다 — 알림을 달아 놓고도 정작 실패하면
아무 일도 안 일어나는, U-57과 같은 증상이 알림 배선 위에서 재발하는 것이다.
그래서 `%p`(접두사)와 `%i`(인스턴스)를 하이픈으로 이어 붙인 값을 넘긴다 —
이 둘은 정의상 `@`를 포함할 수 없다. 받는 쪽(`scripts/notify_failure.py`의
`resolve_unit_name()`)이 마지막 `-`를 `@`로 되돌려 `journalctl -u`에 쓸 이름을
복원한다(인스턴스 이름 자체에 하이픈이 없다는 전제 — 지금 쓰는 fast/slow는
문제없다). 전체 근거는 두 파일의 머리말 주석에 있다(여기서 반복하지 않는다).

**⚠ 받는 쪽(`popcorn-notify-failure@.service`)은 `%i`를 쓴다 — `%I`가 아니다
(2026-08-24 서버 실측 사고로 확정).** systemd에서 `-`는 `/`의 escape
표현이다. `%i`는 인스턴스 이름을 escape된 그대로(추가 처리 없이) 주고,
`%I`는 그것을 사람이 읽는 형태로 **unescape**한다 — 그 과정에서 `-`를 전부
`/`로 되돌린다. 처음 `%I`로 배선해 서버에 실제로 설치하고
`popcorn-danawa-market@fast.service`를 일부러 실패시켜 봤더니, journald에
`popcorn-danawa-market-fast`가 아니라 **`popcorn/danawa/market/fast`**로
깨져 남았다(Description 문구·스크립트가 받는 인자 양쪽 다) — `journalctl -u
popcorn/danawa/market/fast.service`는 존재하지 않는 unit이라 마지막 로그를
못 가져온다. `%i`로 바꾸면 `resolve_unit_name()`이 원래 받기로 설계된
그대로("하이픈이 살아있는 원문")가 오므로 스크립트는 고치지 않았다.

### `notify_telegram.py`가 배포 서버(.env 없음)에서 동작하는가 — 판정

**동작한다.** `scripts/_tg_env.py`의 `creds()`는 ① 프로젝트 `.env`를 먼저 보고
② 없으면(또는 키가 없으면) **프로세스 환경변수**로 넘어간다(코드:
`scripts/_tg_env.py`의 `creds()` — `_from_env_file()`이 `OSError`를 삼키고 빈
dict를 반환 → `os.environ.get(...)`으로 폴백). 배포 서버 리포에는 `.env` 파일
자체가 없으므로 ①은 항상 빈 값이고, `EnvironmentFile=/etc/popcorn-ai.env`가
채운 **프로세스 환경변수**(②)가 쓰인다. `CLAUDE.md` §텔레그램의 "자격증명은
프로젝트 `.env`(전역 환경변수 아님)"는 **이 PC(개발 PC)에서 여러 프로젝트 봇이
섞이는 것**을 막으려는 규칙이고, 배포 서버는 애초에 다른 프로젝트가 없으니
전제가 다르다 — `.env`가 없는 환경에서 환경변수 폴백은 이미 코드에 있던
동작이지, 이번에 새로 만든 우회가 아니다.

### 설치

```bash
# 신규
sudo install -m 644 /srv/popcorn-ai/deploy/systemd/popcorn-notify-failure@.service /etc/systemd/system/
# 기존 파일 갱신(OnFailure= 한 줄이 추가됐다)
sudo install -m 644 /srv/popcorn-ai/deploy/systemd/popcorn-danawa-market@.service /etc/systemd/system/
sudo systemctl daemon-reload
```

`popcorn-notify-failure@.service` 자체는 `enable`하지 않는다([Install]이 없다) —
시작은 실패한 unit의 `OnFailure=`가 그때그때 담당한다.

### ⚠ 사장님이 직접 하셔야 하는 것 — `/etc/popcorn-ai.env`에 두 줄 추가

리포에도 이 문서에도 토큰 값을 적지 않는다.

⚠ **2026-08-24 서버 실측 사고 — `printf ... >>` 처럼 «덧붙이는» 방식으로
넣지 않는다.** 이 방식으로 넣었더니 이 문서 예시에 있던 꺾쇠 자리표시자
(`<봇 토큰>`·`<채팅 ID>`)가 값으로 착각돼 **그대로** 들어갔다 — 전송이
`http.client` 안에서 `UnicodeEncodeError`로 죽었고 journald에는 트레이스백만
남아 «왜» 안 가는지 알 수 없었다(지금은 `scripts/notify_failure.py`가 이
형태를 미리 걸러 분명한 문구를 남긴다 — 아래 「안전하게 실패를 흉내 내는
법」③). 덧붙이기는 **같은 키 줄이 여러 개** 생기는 문제도 겹친다 — 뒷줄이
이긴다고 해도 어느 줄이 실제로 쓰이는지 사람이 매번 헷갈린다.

**반드시 편집기로 열어, 자기 눈으로 실제 값을 보면서 고친다:**

```bash
sudo nano /etc/popcorn-ai.env
```

파일 맨 아래로 가 **직접 타이핑으로** 두 줄을 추가한다. 아래는 "이런 모양"
이라는 설명이지 그대로 붙여 넣는 명령이 아니다 — `<`와 `>` 사이를 실제
값으로 **바꿔서** 쓴다(값은 로컬 PC `.env`에 이미 있다 — 봇은
`@popcornpc_ai_bot`):

    TELEGRAM_BOT_TOKEN=<여기를 실제 봇 토큰으로 바꿔 쓴다>
    TELEGRAM_CHAT_ID=<여기를 실제 채팅 ID로 바꿔 쓴다>

**저장하기 전에 화면에서 `<`·`>`가 안 보이는지 눈으로 확인한다** — 꺾쇠가
남아 있으면 아직 자리표시자 그대로라는 뜻이다.

저장한 뒤 **권한이 그대로인지 확인한다** — 이 파일은 `640 root:popcorn`이어야
한다(§0 참조 — `600`으로 두면 `popcorn` 계정으로 도는 진단 스크립트가 못 읽는
사고가 이미 있었다). `nano`로 저장해도 기존 파일의 권한은 보통 유지되지만,
새로 만들었거나 의심되면:

```bash
sudo chmod 640 /etc/popcorn-ai.env && sudo chown root:popcorn /etc/popcorn-ai.env
ls -l /etc/popcorn-ai.env    # -rw-r----- root popcorn 이어야 한다
```

**넣은 뒤, 값을 출력하지 않고 «형태»만 재서 스스로 확인한다**(CLAUDE.md
§텔레그램 · T-07 마스킹 금지 원칙과 같은 이유 — 값이 아니라 사실만 본다).
`scripts/notify_failure.py`의 `credential_problems()`가 서버에서 실제로 보는
것과 같은 종류의 판정이다 — 존재(줄 수, 중복 검사 겸함) → 길이 →
비ASCII 포함 여부:

```bash
sudo grep -c '^TELEGRAM_BOT_TOKEN=' /etc/popcorn-ai.env   # 1 이어야 한다(0=없음, 2+=중복 줄)
sudo grep -c '^TELEGRAM_CHAT_ID='   /etc/popcorn-ai.env   # 1 이어야 한다(0=없음, 2+=중복 줄)
sudo bash -c "grep '^TELEGRAM_BOT_TOKEN=' /etc/popcorn-ai.env | cut -d= -f2- | wc -c"   # 40 안팎이 정상 — 한 자리 수면 의심
sudo bash -c "grep '^TELEGRAM_CHAT_ID='   /etc/popcorn-ai.env | cut -d= -f2- | wc -c"   # chat_id 자릿수 + 1(개행) 정도
sudo bash -c "grep '^TELEGRAM_BOT_TOKEN=' /etc/popcorn-ai.env | cut -d= -f2- | grep -cP '[^\x00-\x7F]'"   # 0 이어야 한다(1 이상=비ASCII 섞임=자리표시자 의심)
sudo bash -c "grep '^TELEGRAM_CHAT_ID='   /etc/popcorn-ai.env | cut -d= -f2- | grep -cP '[^\x00-\x7F]'"   # 0 이어야 한다
```

줄 수가 1이 아니거나, 길이가 한 자리 수이거나, 비ASCII 개수가 1 이상이면
자리표시자가 그대로 남았거나 중복 줄이 있는 것이다 — 바로 아래 「이미 잘못
들어간 줄을 고치는 법」을 따른다. **이 여섯 줄을 전부 통과해도 실제로 가는지는
아래 「안전하게 실패를 흉내 내는 법」①로 한 번 더 확인한다** — 형태 검사가
잡는 것은 "자리표시자·중복 잔재"뿐이고, 형태가 멀쩡한데 값 자체가 틀린
경우(예: 다른 봇의 토큰)까지는 못 잡는다.

### 이미 잘못 들어간 줄을 고치는 법 — 또 덧붙이지 않는다

`printf ... >>` 등으로 이미 넣었다면 **같은 키 줄이 여러 개**일 수 있다.
그 위에 한 줄 더 append하면 문제가 늘 뿐이다 — `EnvironmentFile=`은
나중 줄이 앞 줄 값을 덮어쓰지만, 그걸 믿고 줄을 계속 쌓지 않는다(사람이 나중에
어느 줄이 유효한지 알 길이 없어진다):

```bash
sudo nano /etc/popcorn-ai.env
```

`TELEGRAM_BOT_TOKEN=`·`TELEGRAM_CHAT_ID=`로 시작하는 줄을 **찾아서**(nano는
`Ctrl+W`로 검색) 중복이 있으면 지우고 **정확히 한 줄씩만** 남긴 뒤, 남긴 줄의
`=` 뒤 값을 실제 값으로 고쳐 쓴다. 저장 후 바로 위 여섯 줄 검사를 다시 돌려
줄 수가 각 1인지, 형태가 정상인지 재확인한다.

**이미 떠 있는 다른 서비스(`popcorn-api` 등)를 재시작할 필요는 없다** — 알림
unit은 `Type=oneshot`이라 실패가 나서 호출될 때마다 그 순간의
`/etc/popcorn-ai.env`를 새로 읽는다.

### 안전하게 실패를 흉내 내는 법 — **진짜 수집 unit은 건드리지 않는다**

① **알림 스크립트 자체만 시험**(가장 빠름 — OnFailure= 배선 자체는 확인 못
한다, 존재하지 않는 가짜 unit 이름으로 스크립트 로직만 돈다). 인스턴스 이름에
하이픈을 넣지 않는다 — `resolve_unit_name()`이 하이픈을 "%p-%i 조인"으로
해석해 엉뚱하게 쪼갠다(예: `test-manual`은 `test@manual.service`로 잘못
복원된다. 이 한계는 두 unit 파일 머리말에 이미 적혀 있다):

```bash
sudo systemctl start popcorn-notify-failure@smoketest.service
sudo journalctl -u popcorn-notify-failure@smoketest.service -n 30 --no-pager
```

`smoketest`라는 실제 unit은 없으므로 본문에 "로그 없음" 문구가 함께 오는 게
정상이다 — 그래도 텔레그램 발송 성공/실패 여부(그리고 자격증명이 없을 때
③처럼 그 사실을 journald에 남기는지)는 이걸로 확인된다.

② **`OnFailure=` 배선 자체까지 시험**(임시 템플릿 unit을 만들어 일부러
실패시킨다 — `popcorn-danawa-market@.service`와 무관한 별도 이름이라 진짜
수집에 영향이 없다):

```bash
sudo tee /etc/systemd/system/popcorn-notify-test@.service > /dev/null <<'EOF'
[Unit]
Description=알림 배선 시험용 (시험 후 반드시 삭제한다)
OnFailure=popcorn-notify-failure@%p-%i.service

[Service]
Type=oneshot
ExecStart=/bin/false
EOF
sudo systemctl daemon-reload
sudo systemctl start popcorn-notify-test@demo.service   # ExecStart=/bin/false라 반드시 실패한다

# 잠시 후(몇 초) 확인 — popcorn-notify-test@demo 가 실패 -> %p-%i 로
# "popcorn-notify-test-demo" 가 되어 아래 인스턴스가 자동으로 시작된다:
sudo journalctl -u popcorn-notify-failure@popcorn-notify-test-demo.service -n 30 --no-pager
```

**시험이 끝나면 반드시 치운다**:

```bash
sudo rm /etc/systemd/system/popcorn-notify-test@.service
sudo systemctl daemon-reload
```

③ **자격증명이 없을 때의 동작도 확인해 둔다** — `/etc/popcorn-ai.env`에 두
줄을 넣기 전에 위 ①을 먼저 돌려 보면, 텔레그램으로는 아무것도 안 오지만
`journalctl -u popcorn-notify-failure@smoketest.service`에는
`TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 가 없다 - /etc/popcorn-ai.env 에 두 줄을
추가해야 한다`가 **분명히** 남아야 한다. 아무 흔적도 없이 조용히 끝나면 그
자체가 결함이다.

④ **자격증명은 있지만 형태가 이상할 때도 트레이스백이 아니라 문구가 남는지
확인한다**(2026-08-24 서버 실측 사고의 재발 방지 — `scripts/notify_failure.py`의
`credential_problems()`). 위 「넣은 뒤... 형태만 재서 스스로 확인한다」의 여섯
줄 검사가 이미 이 사고 자체를 막지만, 혹시 그 검사를 건너뛰고 값을 넣었다면
①을 한 번 더 돌려 `journalctl`에 다음 중 하나처럼 **원인과 고칠 위치를 담은
한 줄**이 남는지 본다(값 자체는 어디에도 안 찍힌다):

    TELEGRAM_BOT_TOKEN 값이 비어 있다 - ...
    TELEGRAM_BOT_TOKEN 이 플레이스홀더 그대로다(꺾쇠 <, > 포함) - ...
    TELEGRAM_BOT_TOKEN 에 비ASCII 문자가 있다(...) - ...
    TELEGRAM_BOT_TOKEN 형식이 텔레그램 봇 토큰(숫자:영숫자) 이 아니다 - ...

`UnicodeEncodeError`나 `Traceback` 같은 파이썬 내부 오류 문자열이 보이면 이
검사가 무너진 것이다 — 이 절 자체가 실패다.

### 재귀 방지

`popcorn-notify-failure@.service` 자신에는 `OnFailure=`를 걸지 않는다 — 걸면
자격증명이 없는 채로 배포됐을 때 "알림 실패 → 자기 자신을 다시 호출 → 또
실패 → ..."로 반복될 수 있다.

## 몰 공급처·가격 갱신 — 손으로 돌린다 (2026-08-27 자동화로 신설 · 2026-08-29 손으로 돌리는 것으로 확정)

> ⚠ **지금은 자동으로 돌지 않는다 — decision-log `A-124`(2026-08-29 사장님 확정).**
> 2026-08-27에는 2026-08-26에 사람이 손으로 한 절차(추천 후보 조회 → 몰에서
> 공급처·가격 수집 → 「가능」 최저가로 매입가·판매가 재계산 → 전 공급처 품절
> 상품 후보 제외, decision-log **A-114~A-116**)를 매일 새벽 자동으로 반복하도록
> 이 도구와 아래 systemd 유닛을 만들었다. **그 "새벽 무인 실행"이 문제였다** —
> 그 시각엔 쿠키를 줄 사람이 없고, 미리 넣어 둔 쿠키는 며칠이면 만료된다(아래
> §쿠키를 얻는 법 참조). 그래서 **자동 스케줄은 켜지 않고, 필요할 때 사람이
> 손으로 돌린다**로 바뀌었다.
>
> **아래에서 지금 실제로 하는 일은 §「쿠키를 얻는 법」과 §「손으로 돌리는
> 절차」뿐이다.** 「설치」·「활성화」로 표시된 절은 나중에 자동화를 다시 검토할
> 때 쓸 **참고 기록**이지 지금 할 일이 아니다 — 순서대로 실행하면 도로 무인
> 새벽 실행이 켜진다.
>
> 도구 자체(`tools/mall_daily_sync.py`·`tools/mall_supplier_fetch.py`)는 자동이든
> 손으로 돌리든 같다 — 바뀐 것은 "누가 언제 돌리는가"뿐이다. **서버에서 직접
> 만들거나 고치지 않는다**(P-06) — 리포에서 고쳐 push하고 서버는 받기만 한다.

파일 셋:

| 파일 | 역할 |
|---|---|
| `tools/mall_daily_sync.py` | 실행 본체. 1~4단계를 순서대로 돈다(`--apply` 없으면 드라이런) |
| `deploy/systemd/popcorn-mall-sync.service` | 단일 서비스(템플릿 아님) — `tools/mall_daily_sync.py --apply` 실행 |
| `deploy/systemd/popcorn-mall-sync.timer` | 매일 03:00 KST 1회 — 시각 근거는 파일 안 주석(다나와 타이머와의 겹침 회피) |

### 결과를 보는 곳 — 작업 현황판이 아니라 **관리자 대시보드**

⚠ **2026-08-27 사장님 확인으로 방향이 바뀌었다.** 처음엔 작업 현황판
(`.claude/dash-queue.jsonl`, `api/dash.py`)에 남기려 했는데, 그 화면은 **하네스의
로컬 세션 전사본**(`~/.claude/projects/...`, 사장님 PC에만 있다)을 읽는 화면이라
배포 서버에서 도는 이 배치가 거기에 닿을 방법이 없다. 그래서 결과를
**`mall_sync_runs` 표(`db/migrations/versions/0067_mall_sync_runs.py`)에 남기고**,
`/admin2/`(관리자 대시보드, `api/admin_dashboard.mall_sync_status` ·
`api/admin_ui_home.py` · `templates/admin/home.html.j2`)가 그것을 읽어 "오늘의
흐름" 바로 아래 한 줄로 보여준다. **로그인만 하면 보인다** — 별도 조작이 없다.

    정상    몰 공급처·가격 2026-08-27 03:00 — 수집 2,726건 · 가격 12건 변경 · 보류 1건 · 후보 제외 3건
    실패    ⚠ 몰 갱신 실패(2026-08-27 03:00) — 몰 세션이 만료되었습니다(로그인 페이지로 redirect 감지) —
            MALL_ADMIN_COOKIE 를 다시 넣어야 합니다
    미실행  몰 갱신 — 아직 실행된 적 없습니다
    오래됨  ⚠ 몰 갱신 2026-08-25 03:00 — ... (마지막 실행 후 31시간 경과)

마지막 줄("오래됨")이 "하루 넘게 안 돎" 판정이다 — 가장 최근 실행의 `started_at`이
30시간(하루 주기 + 지터·실행시간 여유, `api/admin_dashboard.MALL_SYNC_STALE_HOURS`)
넘게 지나면, 그 실행이 성공이었어도 경고(⚠)로 바뀐다. 성공은 조용히, 실패·오래됨은
눈에 띄게(warn 배지, 기존 "재고 정합" 자리와 같은 색).

⚠ **이 30시간 기준은 "매일 자동으로 돈다"는 전제로 만들어졌다.** A-124(손으로
돌린다) 이후에는 사람이 며칠 간격을 두고 돌릴 수 있으므로, 그 사이 대시보드에
"오래됨" 경고가 뜨는 것은 **정상이다** — 타이머가 죽었다는 신호가 아니다. 이
판정 기준(코드) 자체를 손으로 돌리는 주기에 맞출지는 이번 결정의 범위 밖이다.

### 설치 (참고 기록 — 지금 실행하지 않는다, A-124)

⚠ **이 절부터 아래 §「활성화」 앞부분까지는 무인 자동 실행을 켜는 절차다.**
A-124(2026-08-29)로 자동 스케줄을 켜지 않기로 했으므로 **지금은 아래 명령을
실행하지 않는다.** 나중에 무인 인증 수단(예: 윈윈소프트 API 승인)이 생겨
자동화를 다시 검토할 때를 위한 참고로만 남긴다.

```bash
sudo install -m 644 /srv/popcorn-ai/deploy/systemd/popcorn-mall-sync.service /etc/systemd/system/
sudo install -m 644 /srv/popcorn-ai/deploy/systemd/popcorn-mall-sync.timer /etc/systemd/system/
sudo systemctl daemon-reload
```

**설치 전에 시각 표기부터 검증한다**(다나와 타이머와 같은 절차):

```bash
systemd-analyze calendar '*-*-* 03:00:00 Asia/Seoul'   # 다음 날 03:00 KST가 나와야 한다
```

`Next elapse`가 기대와 다르면 `.timer` 파일 안 UTC 대체 줄로 바꾼 뒤 같은 명령으로
다시 검증하고 설치한다(파일 안에 위치·값이 이미 있다).

**마이그레이션**(`mall_sync_runs` 표)은 위 자동화 설치와 무관하게, `--apply`로
한 번이라도 반영하려면(손으로 돌리든 나중에 자동으로 돌리든) 미리 적용돼 있어야
한다 — 표가 없으면 대시보드 타일이 "조회 실패"로만 보인다(정상 — 아직 표가
없다는 뜻, 화면이 숫자를 지어내지 않는다):

```bash
cd /srv/popcorn-ai/db && ../.venv/bin/python -m alembic upgrade head
```

### 쿠키를 얻는 법 — 지금은 `/etc/popcorn-ai.env`에 넣지 않는다

⚠ **이 절은 2026-08-27 작성 당시 "무인 자동 실행이 읽을 수 있도록 서버 설정
파일에 쿠키를 상주시킨다"는 전제로 쓰여 있었다.** 그 전제 자체가
`CLAUDE.md:89-90` · decision-log **A-114**의 「쿠키를 `.env`나 코드에 두지
않는다」와 문자 그대로 어긋난다 — **자동화 여부와 무관하게 원래도 어긴 안내였다.**
`A-124`(2026-08-29)로 자동 실행 자체를 켜지 않기로 하면서 그 전제도 함께
없어졌다 — **`/etc/popcorn-ai.env`에 `MALL_ADMIN_COOKIE`를 추가하지 않는다.**
(참고: 바로 위 §「실패 알림」의 텔레그램 토큰은 이 규칙 대상이 아니다 — 만료되지
않는 값이고 A-114·A-124는 **몰 로그인 쿠키에만** 적용된다.)

**지금 실제로 쓰는 절차**(오늘 이 방식으로 200건을 수집했다):

1. 사장님이 `popcornpc.co.kr` 관리자에 로그인해 둔 브라우저에서 쿠키 값을
   확인해 하네스에게 전달한다 — 얻는 법(개발자도구 Network 탭 → `/adm_cate/`로
   시작하는 요청 → Request Headers의 `Cookie` 값)은 `tools/mall_supplier_fetch.py`
   모듈 docstring §쿠키를 얻는 법과 같다(여기서 되풀이하지 않는다 — 같은 절차를
   두 곳에 적으면 한쪽만 고쳐져 어긋난다).
2. 하네스는 그 값을 **어떤 파일에도 쓰지 않고**, 그 실행 프로세스 하나에만
   유효한 환경변수로 넘겨 아래 §「손으로 돌리는 절차」의 명령을 돌린다.
3. 실행이 끝나면 그 값은 버린다 — 다음에 필요할 때 사장님께 **다시 청한다**
   (「갱신」이 아니다 — 텔레그램 토큰처럼 서버에 영구히 두는 값과는 다른 취급).

⚠ **이 쿠키는 로그인 시점부터 유효기간이 있다.** 실행 중 만료되면(로그인
페이지로 redirect) 스크립트가 즉시 "세션 만료"로 멈추고 실패로 기록한다(대시보드
「실패」 예시 참조) — 낱개 상품 실패로 취급하지 않는다. 그 실행은 버리고, 새
쿠키를 다시 청해 처음부터 다시 돌린다.

### 활성화 (참고 기록 — 지금 실행하지 않는다, A-124)

```bash
sudo systemctl enable --now popcorn-mall-sync.timer
sudo systemctl list-timers 'popcorn-mall-sync*'
```

⚠ 위 두 줄이 무인 새벽 실행을 켜는 지점이다 — **A-124 아래에서는 실행하지
않는다.** 지금 쓰는 것은 바로 아래 §「손으로 돌리는 절차」뿐이다.

### 손으로 돌리는 절차 (지금 쓰는 방식)

첫 실행은 캐시가 0건이라 전량 새로 수집한다(다나와 타이머와 같은 사정) —
**먼저 `--apply` 없이(드라이런) 확인한다**:

```bash
sudo -u popcorn /srv/popcorn-ai/.venv/bin/python /srv/popcorn-ai/tools/mall_daily_sync.py --limit 20
```

(위 명령은 서버에서 돌릴 때의 모양이다 — 로컬에서 돌릴 때는 같은 스크립트를
`.venv` 인터프리터로 부르면 된다. `MALL_ADMIN_COOKIE`는 위 §「쿠키를 얻는 법」
②대로 이 명령 앞에 그 실행에만 유효한 환경변수로 붙인다 — 정확한 쉘 문법은
그때그때 다르므로 여기 적지 않는다.)

`--limit 20`으로 소수만 먼저 돌려 콘솔 요약(수집·가격 변경·보류·후보 제외 건수)이
말이 되는지 본 뒤, `--limit` 없이(전체) 드라이런 한 번, 그 다음에야 `--apply`로
실제 반영한다. systemd 서비스로 감싸 돌리려면(선택 — 맨 명령으로 돌려도 된다):

```bash
sudo systemctl start popcorn-mall-sync.service
sudo journalctl -u popcorn-mall-sync.service -f
```

`-f`는 실시간 추적이라 최대 약 1~2시간(현재 대상 규모 기준, `popcorn-mall-sync.service`
파일 안 타임아웃 산정 참조) 터미널을 붙잡는다 — 계속 붙잡지 말고 `Ctrl+C`로 빠져나온
뒤 나중에 다시 확인해도 된다:

```bash
systemctl status popcorn-mall-sync.service --no-pager
sudo journalctl -u popcorn-mall-sync.service --since '2 hour ago'
```

실행이 끝나면 `/admin2/`(관리자 대시보드)를 열어 위 「정상」 문구가 실제로 뜨는지
확인한다 — journald 로그와 대시보드 둘 다 같은 실행을 말해야 한다.

### 끄는 법 (참고 기록) · 되돌리는 법 (지금도 쓴다)

⚠ **지금은 타이머를 켠 적이 없다**(A-124) — 아래 "끄는 법"은 나중에 §「활성화」를
실행해 자동화를 켰을 경우를 대비한 참고다. 반면 **"되돌리는 법"은 손으로
`--apply`를 돌렸을 때도 똑같이 쓴다** — 자동/수동과 무관하게 유효하다.

```bash
sudo systemctl disable --now popcorn-mall-sync.timer
```

타이머만 끄면 **다음 예정 실행이 없어질 뿐**, 이미 반영된 값은 그대로 남는다.
unit 파일까지 걷으려면:

```bash
sudo rm /etc/systemd/system/popcorn-mall-sync.timer /etc/systemd/system/popcorn-mall-sync.service
sudo systemctl daemon-reload
```

**그날 반영분을 되돌리려면**(값이 잘못 들어갔을 때 — 원장은 삭제가 아니라 역방향
전이다) 세 단계 전부 근거가 남아 있다:

1. 대시보드 또는 `SELECT * FROM mall_sync_runs ORDER BY run_id DESC LIMIT 5`로
   되돌릴 실행의 `run_id`·`reprice_log_id`·`exclude_log_id`를 확인한다.
2. **매입가·판매가**(3단계) — `reprice_log_id`가 가리키는
   `admin_operator_activity_logs` 행의 `detail->'before'`(상품별 `{pc, purchase,
   sale, locked_sale}` 스냅샷)를 순회하며 `products.purchase_price`·`sale_price`를
   복원하고 `product_price_history`에 `reason='mall_daily_sync_reprice_undo'`로
   역방향 행을 남긴다 — `api/admin_price_import.undo()`(ADM-PRC-040, `/api/admin/
   price-import/undo/{log_id}`와 같은 모양, 다만 그 엔드포인트는 `supplier_price_files`
   기반이라 이 log_id를 직접 받지 않는다 — **지금은 이 되돌림이 API로 노출돼 있지
   않다**, DBA가 같은 패턴의 SQL로 손으로 수행한다. 도구화는 이번 작업 범위 밖이다).
3. **후보 제외**(4단계) — `exclude_log_id`가 가리키는 로그의 `detail->'before'`
   (상품별 `{pc, part_type, locked_fields, ai_candidate_yn}` 스냅샷)를 순회하며
   `products.ai_candidate_yn`·`locked_fields`를 함께 원복한다(값만 되돌리고 잠금이
   남으면 다음 실행이 영영 못 채운다 — A-115와 같은 규칙). 끝나면
   `action='mall_daily_sync_exclude_no_supplier_undo'`로
   `detail={"ref_log_id":<exclude_log_id>,"restored":N}` 되돌림 로그를 새로 남긴다
   (같은 `ref_log_id`로 이미 되돌린 기록이 있으면 중단 — 중복 실행 방지, A-115·A-116과
   같은 안전장치).

`mall_sync_runs` 행 자체는 지우지 않는다 — "그날 실행이 있었다"는 사실은 되돌려도
남는다(원장 규약).

### 실패 확인

`popcorn-mall-sync.service`에도 `OnFailure=`가 걸려 있다(위 「실패 알림」 절과 같은
메커니즘, 이 unit은 템플릿이 아니라 `%n`을 그대로 쓴다 — 파일 안 주석 참조). 실패하면
**텔레그램으로도** 오고, **대시보드에도** 뜬다(둘은 서로 다른 실패 정의를 쓸 수 있다
— 텔레그램은 "systemd 가 실패로 판정"[비정상 종료 코드], 대시보드는 `mall_daily_sync.py`
자신이 "세션 만료·0건 수집"처럼 **정상 종료(exit 1)로 명시적으로 실패를 기록한 것**도
포함한다 — 예를 들어 `_abort_reason()`이 잡는 경우들은 프로세스가 깔끔하게 종료돼도
대시보드에는 실패로 남는다).

### 안전하게 실패를 흉내 내는 법 — 진짜 수집 unit은 건드리지 않는다

① **세션 만료를 실제로 재현**: 손으로 돌릴 때 넘기는 `MALL_ADMIN_COOKIE`
환경변수 값의 마지막 몇 글자만 바꾼 **무효한 값**으로 드라이런을 한 번 돌린다
(A-124 이후에는 이 값이 `/etc/popcorn-ai.env`가 아니라 그 실행 한정 환경변수로
오므로, 재현도 그 환경변수만 바꿔서 한다 — 서버 설정 파일은 건드리지 않는다) —
`tools/mall_supplier_fetch.py`의 `LoginRequired` 감지가 즉시 걸리고
`tools/mall_daily_sync.py`가 3·4단계를 건너뛰는지, 대시보드가 "세션 만료" 문구를
보여주는지(`--apply`로 돌렸을 때) 확인한다.

② **큰 변동 보류를 실제로 재현**: `MALL_SYNC_BIG_SWING_RATIO`를 1에 가깝게
(예: `1.01`) 잠깐 낮춰 드라이런을 돌리면, 실제로는 정상 범위인 가격 변동도 대부분
보류 목록에 걸린다 — "그 건만 보류되고 나머지는 정상 반영되는지"(값을 준 건 전부가
아니라 조건에 걸린 건만 보류)를 확인하는 데 쓴다. 이 값도 서버 설정 파일에 영구히
두지 않는다(정상 변동까지 전부 보류되면 이 도구의 의미가 없어진다) — 손으로 한
번 돌릴 때만 임시로 준다:

```bash
sudo -u popcorn MALL_SYNC_BIG_SWING_RATIO=1.01 \
  /srv/popcorn-ai/.venv/bin/python /srv/popcorn-ai/tools/mall_daily_sync.py --limit 50
```

## 남아 있는 위험 (베타에서 감수하는 것 · 정직 기록)

| 위험 | 지금 상태 | 해소 조건 |
|---|---|---|
~~평문 통신~~ | **해소(2026-07-28)** — HTTPS 전환 완료 | — |
~~nginx가 고객 경로를 막는다~~ | **낡음(2026-08-09 개정으로 무효)** — 고객 경로는 이제 열려 있다(§7). 그래서 아래 두 항목은 더는 "막혀 있어 괜찮은" 위험이 아니라 **지금 그대로 노출된 위험**이다 | — |
| 고객 인증 dev 어댑터 | `"@" in email`이 전부 — **막는 nginx 차단이 없어 그대로 노출된다**(§7 「열면서 감수한 구멍」 참조) | 실 OAuth |
신원 확인 | dev 어댑터(입력 이메일을 신뢰) — ~~Basic Auth가 유일한 실질 방벽~~(2026-07-30 폐기, 상단 「최초 결정과 그 뒤 바뀐 것」 참조). **지금 방벽은 없다** — 관리자 쪽만 비밀번호 인증 + `/api/admin/*` 미들웨어가 막고, 고객 쪽은 이메일 형식 검사뿐이다 | 실 OAuth 연동 |
로그인 시도 제한 | 없음 | fail2ban 또는 앱 레벨 제한 |
고객 축 | ~~코드는 있지만 베타에서 쓰지 않는다~~ **2026-08-09부터 열려 실제로 쓰인다**(§7) | 위 dev 어댑터가 실 OAuth 로 바뀌는 것 — 「고객 오픈」 자체는 이미 결정·실행됐다 |

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
