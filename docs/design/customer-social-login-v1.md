# 고객 회원·소셜 로그인 설계 v1 (구글·카카오·네이버)

- 작성 2026-10-13 · Claude(개발) · **상태: 사장님 확정 2026-10-13 「제안대로 진행해」 — §13 결정 D-1~D-8 모두 제안대로** (구현 P1 부터)
- 근거 결정: 2026-10-13 사장님 「(나)로 가자, 회원만 자체로 해」 — 회원·소셜 로그인은 팝콘AI가 직접, 주문·결제·배송·환불·정산은 팝콘PC 쇼핑몰(지금 그대로). A-97(구매 순간 쇼핑몰로 인계) 유지, 2026-10-08 결정 ⑤ 중 «고객 실인증 범위 제외»만 바뀜.
- 화면 디자인은 코덱스가 맡는다(사장님 2026-10-13 「디자인은 코덱스」). 이 문서는 동작·데이터·보안·사람 단계만 정한다. 디자인할 화면 목록은 §11.
- 기준 코드: main `13cb070`. 지금 고객 로그인과 `/api/my/*` 는 전부 503 `auth_unavailable`(fail-closed, 2026-10-08 c8487e0 이후). CLAUDE.md·nginx 주석의 「@만 확인하는 dev 어댑터」 서술은 낡았다.

---

## 0. 한눈에

| 항목 | 정하는 것 |
|---|---|
| 로그인 방법 | 구글 · 카카오 · 네이버 (비밀번호 없음, 이메일 로그인 없음) |
| 가입 | 첫 소셜 로그인 → **가입 동의 화면**(필수 약관·개인정보·만 14세 이상 확인) → 회원 생성. 동의 전에는 회원도 세션도 만들지 않는다 |
| 회원을 찾는 열쇠 | (공급자, 공급자가 준 고유 ID) 쌍. **이메일로 찾거나 자동 연결하지 않는다** |
| 세션 | 쿠키 `popcorn_member_session`(HttpOnly · SameSite=Lax · Secure), 서버에는 해시만, 14일 절대 만료, 로그아웃·탈퇴 시 철회(지우지 않음) |
| 회원이 얻는 것 | 다른 기기에서도 내 견적·구매 상담 신청 이어 보기, 마이페이지(프로필·내 견적·내 문의·로그아웃·탈퇴) |
| 회원이 얻지 않는 것 | 주문·결제·배송·환불 내역 — 팝콘PC 쇼핑몰에서 본다(마이페이지에서 쇼핑몰 주문 조회로 연결만) |
| 공급자 토큰 | 로그인 확인 직후 버린다. 저장하지 않는다 |
| 켜는 스위치 | 환경 변수 `CUSTOMER_AUTH_ENABLED=on` + 공급자 키. 하나라도 없으면 지금처럼 503 |

## 1. 이미 정해져 있고 그대로 따르는 것

코드·ERD·테스트가 이미 고정한 원칙이다(조사 근거: `api/customer_identity.py`, `api/customer_auth.py`, `docs/06_db-erd.md` §3.11, `db/migrations/versions/0008_*`).

1. 비밀번호를 저장하지 않는다. 회원은 소셜 로그인으로만 들어온다.
2. 회원 식별은 (`issuer_key`, `subject`) 정확 일치. **이메일은 조회 키가 아니다** — `resolve_identity` 가 강제하고 `test_same_email_different_subject_does_not_link_even_with_profile_email` 이 고정한다.
3. 공급자가 준 닉네임·이메일은 회원 원장의 연락처를 덮어쓰지 않는다(`test_provider_display_claim_does_not_overwrite_canonical_member_contact`). 이메일이 없는 공급자 계정도 받는다.
4. `VerifiedPrincipal` 은 서버 검증기만 만들 수 있다(`_from_server_verifier`). 클라이언트가 보낸 값으로는 못 만든다.
5. 회원 상태가 `active` 가 아니면 세션은 즉시 무효(ERD 계약 ⑤).
6. 세션은 지우지 않고 `revoked` 로 남긴다.
7. 쿠키는 64자리 hex 토큰, 서버엔 sha256 만. 개인 데이터 읽기는 `X-Popcorn-Auth-Context` 헤더(세션 문맥 UUID)가 맞아야 한다(CSRF 방어 겸).

바뀌는 것은 하나다: **「첫 로그인이 곧 가입」(0008)** → 첫 로그인 뒤 **가입 동의 화면을 거쳐야 가입**. 개인정보 수집·이용 동의와 만 14세 확인 없이 회원을 만들 수 없기 때문이다.

## 2. 공급자별 연결 방식

| 공급자 | 방식 | 받는 정보(최소) | 식별자 | 비고 |
|---|---|---|---|---|
| 구글 | OpenID Connect (Authorization Code + PKCE) | `sub`, 이메일(선택), 이름(선택) | ID 토큰 `sub` | ID 토큰 서명을 구글 JWKS 로 검증, `aud`·`iss`·`exp`·`nonce` 확인 |
| 카카오 | OpenID Connect (카카오 로그인 OIDC 활성화) + PKCE | `sub`, 닉네임(선택), 이메일(선택) | ID 토큰 `sub` | 이메일은 **비즈 앱 전환·검수 뒤에만** 받을 수 있다 → 이메일 없이도 가입되게 설계 |
| 네이버 | OAuth 2.0 (네이버 로그인) + `state` | `id`, 닉네임·이메일(선택) | 프로필 API `response.id` | 토큰으로 프로필 API 를 서버에서 한 번 부른다. 네이버 OIDC 제공 여부는 앱 등록 때 확인하고, 되면 OIDC 로 바꾼다 |

- 세 공급자 모두 **이름·이메일은 «선택» 정보**로만 쓴다. 회원 식별에 쓰지 않는다.
- 공급자 access/refresh token 은 프로필을 읽은 직후 버린다. DB·로그에 남기지 않는다.
- 공급자 연결 해제(카카오 «연결 끊기» 등)는 탈퇴 때 호출한다(§7).

### 2.1 콜백 주소 (앱 등록에 쓸 값)

```
https://www.popcornai.co.kr/api/auth/google/callback
https://www.popcornai.co.kr/api/auth/kakao/callback
https://www.popcornai.co.kr/api/auth/naver/callback
```

- 고객 화면 기준 주소를 `www.popcornai.co.kr` 하나로 정한다(쿠키는 호스트 단위라 `popcornai.co.kr` 과 섞이면 로그인이 풀린 것처럼 보인다). nginx 에서 `popcornai.co.kr` → `www` 301 로 맞추는 작업을 같이 한다.
- **운영 서버를 새로 만들 때** 도메인이 그대로 `www.popcornai.co.kr` 이면 등록을 바꿀 필요가 없다. 개발 서버가 다른 주소(`dev.`)로 옮겨 가면 그 주소의 콜백을 **추가 등록**한다(세 공급자 모두 여러 개 등록 가능).
- `/api/auth/` 는 nginx 에서 이미 고객 호스트로 열려 있다(관리자 `/api/admin/auth/` 와 다른 경로 — 다시 막을 때 혼동 금지, CLAUDE.md 경고).

## 3. 로그인·가입 흐름

```
[고객] 로그인 버튼(구글/카카오/네이버)
  → GET /api/auth/{provider}/start?return=<지금 화면>
      서버: state·nonce·PKCE verifier 생성 → oauth_login_attempts 에 10분짜리 한 번용 기록
            (브라우저엔 attempt 를 가리키는 HttpOnly 쿠키만) → 공급자 인증 화면으로 302
[공급자] 로그인·동의
  → GET /api/auth/{provider}/callback?code&state
      서버: ① state 일치·미사용·10분 이내 확인 → 시도 기록 «사용됨»
            ② code → 토큰 교환(PKCE verifier) ③ 신원 검증(ID 토큰 서명·aud·iss·exp·nonce / 네이버는 프로필 API)
            ④ VerifiedPrincipal._from_server_verifier(...) ⑤ resolve_identity
         ├ 연결된 회원 있음(active) → 세션 발급(쿠키) → return 화면으로 302
         ├ 연결된 회원 없음(409 identity_unlinked) → «가입 대기» 기록(신원·10분) → /mvp3/join.html 로 302
         └ 철회·정지·충돌 → 안내 화면(사유 문구만, 내부 코드 노출 없음)
[고객] 가입 동의 화면: 필수 ① 이용약관 ② 개인정보 수집·이용 ③ 만 14세 이상 / 선택 ④ 마케팅 수신
  → POST /api/auth/join {consents:[...], nickname?}
      서버: 가입 대기 기록 확인 → 한 트랜잭션에 members + member_verified_identities + member_consents
            + 세션 발급 → 이 브라우저의 비회원 견적·문의를 회원에 붙임(§6) → 쿠키
[고객] 로그아웃 POST /api/auth/logout → 세션 철회 + 쿠키 삭제
```

- 만 14세 미만은 가입하지 않는다(법정대리인 동의 절차를 두지 않는 정책 — 사장님 확인 D-4). 체크하지 않으면 가입 버튼이 서버에서도 거절된다.
- 가입 대기 기록은 회원이 아니다. 10분 뒤 사라지고, 동의하지 않고 떠나면 아무것도 남지 않는다(개인정보 최소화).
- `return` 은 같은 사이트 안의 경로만 받는다(열린 리다이렉트 방지).
- 같은 공급자로 이미 가입한 사람이 다시 가입 화면에 오는 일은 없다(③에서 회원이 찾아진다).

### 3.1 같은 사람이 다른 공급자로 들어오면

- **자동으로 합치지 않는다.** 카카오로 가입한 사람이 나중에 구글로 들어오면, 구글 신원은 연결된 회원이 없으므로 새 가입 흐름으로 간다.
- 가입 화면에 «이미 다른 방법으로 가입하셨다면 그 방법으로 로그인한 뒤 마이페이지에서 연결할 수 있어요»를 항상 보인다(특정 이메일의 가입 여부는 알려 주지 않는다 — 계정 존재 노출 방지).
- **연결하기**(2단계, §10 P4): 로그인한 상태에서 마이페이지 «다른 로그인 방법 연결» → 그 공급자로 한 번 더 인증 → 그 신원이 아직 아무 회원에게도 없을 때만 지금 회원에 추가. 이미 다른 회원에 붙어 있으면 거절(합치기는 사람 확인 사항).

## 4. 데이터 (ERD 개정 → 새 마이그레이션, 한 번에)

저장소 규칙대로 `docs/06_db-erd.md` 를 먼저 개정하고 마이그레이션을 만든다. 이미 제안된 C2 스키마(저장소 밖 `schema-candidate.txt`, 미수용)를 바탕으로 하되 가입 동의·로그인 시도 표를 더한다.

| 표 | 핵심 열 | 비고 |
|---|---|---|
| `members` (기존) | + `auth_subject UUID UNIQUE NULL`, + `auth_revision BIGINT NOT NULL DEFAULT 0`, + `withdrawn_at TIMESTAMPTZ NULL` | 기존 `joined_via`·`provider_uid` 는 표시용으로만 남김(첫 가입 공급자). `email UNIQUE` 는 유지하되 공급자 이메일로 채우지 않는다(연락처는 회원이 직접 넣을 때만) |
| `member_verified_identities` (신규) | `identity_id`, `member_id`, `issuer_key`(google/kakao/naver), `subject`, `verified_at`, `revoked_at`, `UNIQUE(issuer_key, subject)` | 대소문자·공백 정규화 금지. 1:N (회원 1명에 공급자 여럿 — 연결하기 단계에서 사용) |
| `member_consents` (신규) | `member_id`, `kind`(terms/privacy/age14/marketing), `version`, `agreed_at`, `withdrawn_at` | 약관 문구 버전을 남긴다. 마케팅은 언제든 철회 |
| `member_verified_sessions` (신규) | `credential_hash` PK(sha256), `member_id`, `identity_id`, `auth_context_id UUID`, `issued_auth_revision`, `issued_at`, `expires_at`(14일), `revoked_at`, `user_agent` | 기존 `member_sessions`(0008)는 쓰지 않는다(C2 후보 결정과 같음) |
| `member_session_issuance_receipts` (신규) | `proof_ref`, `credential_hash` UNIQUE, provenance 6개 열, `authority_ref` | 기존 P1 계약(발급 증거 대조)이 요구하는 «서버가 검증해 발급했다»는 영수증. 콜백이 세션과 같은 트랜잭션에 쓴다 |
| `oauth_login_attempts` (신규) | `attempt_id`, `provider`, `state_hash`, `nonce`, `pkce_verifier`, `return_path`, `created_at`, `used_at` | 10분 · 한 번용. 정리 작업이 하루 지난 행을 지운다 |
| `member_join_pending` (신규) | `pending_id`, `issuer_key`, `subject`, `display_nickname`, `display_email`, `created_at`, `used_at` | 동의 전 신원. 10분 · 한 번용 · 하루 뒤 삭제 |
| `mvp3_saved_recommendations`, `purchase_inquiries`, `handoffs` (기존) | + `member_id BIGINT NULL` | §6 회원 귀속 |

- 시각은 기존 C2 후보처럼 epoch BIGINT 로 할지, 저장소 다른 표처럼 TIMESTAMPTZ 로 할지 ERD 개정 때 하나로 정한다(제안: TIMESTAMPTZ — 다른 표와 같게).
- 새 의존성: ID 토큰 서명 검증용 `PyJWT[crypto]`(requirements 에 JWT 라이브러리 없음 — 계약 제안 D5).

## 5. 서버 구현 — 기존 골격에 끼우는 자리

| 기존 자리 | 넣을 것 |
|---|---|
| 새 `api/customer_oidc.py` (계약상 I1) | 공급자 3개 어댑터: start URL 생성, 토큰 교환, 신원 검증, `VerifiedPrincipal._from_server_verifier` 호출. 공급자 설정이 없으면 그 공급자는 «준비 안 됨» |
| `customer_auth_store` `StoredReadPort` / `TrustedPrincipalPort` (R1, V2) | §4 표를 읽는 실제 구현 |
| `customer_auth_sql_read` (Q1) | `SESSION_QUERY` 가 가리키는 표를 §4 마이그레이션으로 실제로 만든다 |
| `customer_auth_provenance` `IndependentIssuanceAuthority` (P1) | 영수증 표를 읽는 구현 |
| `customer_auth.py` `RUNTIME_RESOLVER` (178-179행) | `CUSTOMER_AUTH_ENABLED=on` 이고 위 포트가 준비됐을 때만 실제 해석기로 바꾼다. 아니면 지금처럼 503 |
| 로그인·로그아웃 쓰기 경로 (지금 포트 자체가 없음) | 세션 발급기(쿠키 + 세션 + 영수증 한 트랜잭션), 철회기(로그아웃·탈퇴). 이번에 새로 정의 |
| `/api/auth/login`(이메일 dev 로그인 자리) | 지우지 않고 계속 503(이메일 로그인은 하지 않는다) |
| 미들웨어 허용 범위 | `GET /api/my/profile` 만 → `/api/my/profile`, `/api/my/quotes`, `/api/my/inquiries`, `/api/my/identities`, `POST /api/my/withdraw` 로 넓힌다. 옛 `/api/my/orders`·`/payments`·`/refunds`·`/reviews` 는 계속 닫음(쇼핑몰 몫) |

- 관리자 인증(`api/auth.py`)과는 섞지 않는다. 관리자 화면의 구글·카카오 버튼(「준비 중」)은 이번 범위가 아니다.
- 해시로 고정된 계약 테스트 6곳(`test_customer_profile_context` 의 `customer_auth.py`·`customer_identity.py` 전체 해시 등)과 «런타임 503» 단언들은 구현 PR 에서 **일부러** 새 기준으로 바꾸고, 바꾼 이유를 PR 에 적는다.

## 6. 비회원 기록을 회원에 붙이기 (mvp3)

- 지금 견적 보관의 주인은 (방문자 쿠키 `pc_vid` → `user_id`, 브라우저 보관 키 `X-Access-Key` 의 해시) 두 축이다.
- **가입·로그인할 때 이 브라우저의 기록을 회원에 붙인다**: 같은 `user_id` + 같은 `owner_key_hash` 인 보관 견적, 같은 `user_id` 의 구매 상담 신청, 인계 기록에 `member_id` 를 채운다. 이 브라우저를 쥔 사람이 곧 그 기록의 주인이라는 지금의 소유 판정을 그대로 쓴다.
- 이미 다른 회원에 붙은 기록은 옮기지 않는다(공용 PC 대비).
- 로그인 뒤에는 `member_id` 로도 목록을 읽어 다른 기기에서 이어 본다. 비회원은 지금과 똑같다(회원 가입 강요 없음 — 시나리오 S01).
- 화면 문구 「다른 기기나 회원 계정에서는 이 보관 기록을 이어 볼 수 없어요」(`mockups/mvp3/app.js`)는 로그인 상태에 따라 바꾼다.

## 7. 탈퇴·정지

- **탈퇴**(회원 본인): 마이페이지 → 확인 → `members.status='withdrawn'`, `withdrawn_at`, 세션 전부 철회, 신원 연결 철회, 공급자 연결 끊기 호출(카카오 unlink 등, 실패해도 탈퇴는 진행하고 기록), 닉네임·이메일 즉시 가림. 보관 견적·문의의 연락처는 기존 보관 기간 규칙(구매 상담 180일 후 파기)대로.
- 같은 공급자로 다시 들어오면 새 회원으로 가입(이전 회원과 이어지지 않음). 재가입 제한 기간을 둘지는 사장님 확인(D-5).
- **정지**(관리자): `/admin2/members` 에 정지·해제(owner 권한) 추가 → `status='suspended'` → 세션 즉시 무효. 지금 회원 화면에는 정지 동작이 없다.

## 8. 관리자 화면

- `/admin2/members`: 가입 공급자(여럿이면 모두), 상태(활성/정지/탈퇴), 가입일·최근 로그인, 동의 내역(버전·일시), 이 회원의 보관 견적·구매 상담 신청 바로 가기, 정지·해제.
- 회원 기준 통합 조회(시나리오 S10): 회원 → 보관 견적 → 구매 상담 신청 → 쇼핑몰 인계 기록. 주문·결제는 쇼핑몰 화면에서(몰 API 전까지 인계 번호로 사람이 대조).
- 공급자 고유 ID(`subject`)는 관리자에게도 앞 몇 자리만 보인다.

## 9. 보안·운영 점검표

- `state`·`nonce`·PKCE 필수, 한 번 쓰면 끝, 10분 만료. 콜백 주소는 등록값과 정확히 일치.
- 쿠키 `Secure` 를 켠다 — 개발 서버는 이미 HTTPS 이므로 `/etc/popcorn-ai.env` 의 `COOKIE_SECURE=1`(지금 비어 있을 수 있음 — 배포 전 확인).
- 콜백·가입 경로에 방문자별 호출 한도(`access_gate` 와 같은 틀).
- 로그에는 공급자 이름·결과 코드만(이메일·subject·토큰 금지 — 로그 문자열은 ASCII, CLAUDE.md 슬라이스 40).
- 공급자 장애 시 그 버튼만 «잠시 후 다시» — 비회원 상담은 그대로.
- 공급자 키는 `/etc/popcorn-ai.env` 에만: `CUSTOMER_AUTH_ENABLED`, `GOOGLE_OAUTH_CLIENT_ID`/`_SECRET`, `KAKAO_REST_API_KEY`/`KAKAO_CLIENT_SECRET`, `NAVER_CLIENT_ID`/`_SECRET`. 저장소·채팅·검수 파일에 넣지 않는다.

## 10. 작업 순서 (PR 단위 · 각 PR 은 사장님 확인 뒤 병합 — 자동병합 라벨 안 붙임)

| 단계 | 내용 | 켜짐 여부 |
|---|---|---|
| P1 | ERD 개정 + 마이그레이션(§4) + 저장소 읽기·쓰기 구현(R1·Q1·P1 포트) + 테스트 | 꺼짐(503 유지) |
| P2 | `customer_oidc.py` 3사 어댑터(시험용 가짜 공급자로 검증) + start/callback/join/logout + 세션 발급·철회 + 해시 고정 테스트 갱신 | 키·스위치 없으면 꺼짐 |
| P3 | mvp3 연결: 상단 로그인 진입점, 가입 동의 화면, 비회원 기록 귀속, 다른 기기 이어보기 (화면 = 코덱스 디자인) | 같음 |
| P4 | 마이페이지(프로필·내 견적·내 문의·로그인 방법 연결·로그아웃·탈퇴) + 관리자 회원 화면 보강(정지·동의 내역) | 같음 |
| P5 | 개발 서버에 실제 키 넣고 켜기 → 사람이 만든 테스트 계정으로 3사 로그인 → 코덱스 S04·S05·S06·S10 검수 | 켜짐(개발 서버) |

## 11. 코덱스가 디자인할 화면

1. 상단 로그인 진입점(mvp3 `index.html`·`talk.html`·`new-pcs.html` 상단바) — 로그인 전/후 상태
2. 로그인 선택 창(구글·카카오·네이버 버튼 — 각 공급자 브랜드 가이드 준수)
3. 가입 동의 화면(필수 3 + 선택 1, 약관 전문 보기, «다른 방법으로 가입하셨다면» 안내)
4. 로그인 실패·취소·정지 안내
5. 마이페이지(프로필 · 내 견적 · 내 구매 상담 신청 · 로그인 방법 연결 · 쇼핑몰 주문 조회 바로 가기 · 로그아웃 · 탈퇴)
6. 탈퇴 확인
7. 관리자 회원 상세 보강(공급자 여럿·동의 내역·정지)
- 기존 mvp1 `mockups/shared/auth.js` 의 모달은 구글 버튼이 없고 mvp3 에서 쓰지 않는다 — 재사용할지는 디자인 판단.

## 12. 사람이 할 일 (사장님·운영자)

비밀값은 채팅에 붙이지 말고 서버 설정 파일로만 전달한다.

1. **약관 문구 확정**: 이용약관, 개인정보처리방침(수집 항목: 공급자 고유 ID, 닉네임·이메일(선택), 접속 기록 / 보관 기간 / 제3자 제공 없음 / 위탁), 마케팅 수신 동의(받을 경우). 공개 주소(예: `https://www.popcornai.co.kr/terms`, `/privacy`)가 있어야 카카오·네이버 검수를 받는다.
2. **구글**: Google Cloud 프로젝트(운영자 계정) → OAuth 동의 화면(앱 이름·로고·지원 이메일·개인정보처리방침 주소·승인 도메인 `popcornai.co.kr`) → OAuth 클라이언트(웹) → 승인된 리디렉션 URI §2.1 → 범위 `openid email profile` → «프로덕션»으로 게시.
3. **카카오**: Kakao Developers 앱 생성 → 플랫폼 Web 사이트 도메인 `https://www.popcornai.co.kr` → 카카오 로그인 활성화 + **OpenID Connect 활성화** → Redirect URI §2.1 → 동의 항목: 닉네임(선택). 이메일을 받으려면 비즈 앱 전환(사업자 정보)과 검수 → REST API 키·Client Secret 발급.
4. **네이버**: NAVER Developers 애플리케이션 등록 → 사용 API «네이버 로그인», 제공 정보(별명·이메일 — 선택) → 서비스 URL `https://www.popcornai.co.kr`, Callback URL §2.1 → 개발 중엔 테스트 ID 등록 → 공개 전 **검수 요청**(서비스 화면 캡처·개인정보처리방침 필요).
5. **테스트 계정**: 실제 개인정보가 아닌 테스트용 구글·카카오·네이버 계정(P5 검수용).
6. **결정**(§13).

## 13. 사장님 결정 — 2026-10-13 확정(「제안대로 진행해」)

| 번호 | 질문 | 확정 |
|---|---|---|
| D-1 | 구글·카카오·네이버 셋 다 오픈 때 같이? | 셋 다(지시대로). 검수가 늦는 공급자는 버튼만 늦게 켠다 |
| D-2 | 한 회원에 로그인 방법 여러 개 연결 허용? | 허용하되 «로그인한 상태에서 직접 연결»만(자동 합치기 없음) |
| D-3 | 이메일을 꼭 받아야 하나? | 받지 않아도 가입되게(카카오 비즈 앱 전 대비). 연락이 필요하면 구매 상담 신청 때 받는 지금 방식 유지 |
| D-4 | 만 14세 미만 | 가입 불가(법정대리인 동의 절차 없음) — 확인 체크로 받음 |
| D-5 | 탈퇴 후 재가입 | 즉시 새 회원으로 가입 가능, 이전 기록과 연결 안 함 |
| D-6 | 비회원 견적을 로그인 때 자동으로 계정에 붙일지 | 자동(같은 브라우저 = 지금의 소유 판정) |
| D-7 | 고객 화면 기준 주소 | `www.popcornai.co.kr` 하나로(apex → www) |
| D-8 | 마케팅 수신 동의를 받을지 | 오픈 때는 받지 않음(필요해질 때 추가) |

## 14. 하지 않는 것

- 이메일·비밀번호 로그인, 휴대폰 본인인증(실명 확인 아님 — «verified» 는 공급자 계정 확인일 뿐)
- 주문·결제·환불 기능(쇼핑몰 몫), PG 연동
- 관리자 로그인의 소셜 버튼
- 쇼핑몰 회원과의 자동 연동(몰 API 가 생기면 별도 설계 — `members.mall_member_id` 는 그대로 둠)
