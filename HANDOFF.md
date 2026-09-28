# HANDOFF — 2026-09-28 기준

> 다음 에이전트가 이어받기 위한 현재 상태. **비밀값(비밀번호·API 키·토큰)은 여기 적지 않는다** —
> 이름만 적는다. 현재 수(상품·후보·검수 대기)는 적지 않는다: `.venv/Scripts/python scripts/state.py` 로 잰다.
> 규약·배경의 원천은 `CLAUDE.md` · `docs/decisions/decision-log.md` · `.claude/CANON.md` 다.

---

## 1. 현재 브랜치와 미커밋 변경

- **GitHub `main` = `a3e77cf`** (2026-09-25 13:46 UTC, 「고객 추천을 판매 중인 몰 조립PC 최대 2개로 전환」).
  이 HANDOFF 커밋이 그 위에 얹힌다. 작업 브랜치·열린 PR 없음 — **main 직접 커밋이 규약**이다.
- 클라우드 클론(`/home/claude/popcorn-ai`)은 origin/main 과 같고 미커밋 변경 없음.
- **사장님 PC `D:/DEV/popcorn-ai` 의 상태는 확인 못 함** (원격 폴더 연결 없음). 알려진 것:
  - `git status` 에 **683개 파일이 M** 으로 보이는데 CRLF/LF 차이뿐이다. **checkout/restore 금지.**
  - PC 는 2026-09-22 이후 클라우드에서 푸시된 커밋을 아직 `git pull` 안 했을 수 있다 — 「확인 필요」.
- 데이터 가지(배포 안 됨, 실행마다 덮어씀): `data/mall-fetch`(몰 완제PC 수집 결과) · `data/mall-price`(시중가 반영 로그).

## 2. 최근 완료한 작업 (최신순)

### 2026-09-25 방향 전환 — 「판매 상품 기준 추천 재설계」 (①~④ 완료·서버 반영)
사장님 「다시 작업 하자.. 기존거는 모두 무시하고」(12:03 UTC). 용도×가격 칸마다 부품 조합을 **생성**하던
격자 방식을 접고, **몰에서 이미 파는 조립PC 를 기준표로 채점해 표에 표시**한다. 한 상품이 여러 칸에
들어갈 수 있고, 맞는 상품이 없으면 빈칸이 정답이다.

| 단계 | 내용 | 커밋 · 배포 |
|---|---|---|
| ① 기준표 | 용도 11종 × 기본/쾌적/전문 (프로그램·규모 기준). CPU/GPU 지수는 공개 벤치 **근사** 등급표(코드 안 상수) | `7ad49de` |
| ② 채점 | `tools/product_fit.py` — 입력 popcornpc-catalog.xlsx(230행) → 평가 211 · 제외 19(품절·상세 없음·테스트 상품·구성 미선택). 산출 `/mnt/project-files/판매상품_적합성_20260925/`(엑셀·product_fit.json·product_fit_seed.json). DB 무접촉 | `7ad49de`, `fbbcfc6` |
| ③ 관리자 표 | `/admin2/product-fit` (ADM-GRD-020, 상품관리 → 「판매 상품 용도 매트릭스」). 가격대 7 × 용도·수준, 칸별 상품 수·최저가 대표·빈칸 이유. **마이그레이션 0115** · API `GET /api/admin/product-fit` | `0d2df98`, run 36136189052 ✅ |
| ④ 고객 추천 | mvp2 추천을 실제 판매 상품 **최대 2개**로 (사장님 「최대 2개 · 승인」 13:43). 예산 안 최고 수준 + 가장 저렴한 선택, 예산 안에 없으면 「○원부터」+ 최저가 1개. 몰 링크·판매가 카드 | `a3e77cf`, run 36143152042 ✅ |

- 스위치: `api/grid_public.py` `POPCORN_RECO_SOURCE` (기본 `sold`, `grid` 면 옛 조합 격자). **옛 엔진·격자 표는 지우지 않고 꺼 두기만** 했다.
- 실측 발견: 몰 조립PC 는 싸지 않다 — 90만 미만은 사무용 기본뿐, FHD 대작 게임·영상편집 최저 158.5만.
- 「판매 이유 점검」: 더 싼 상품이 모든 용도에서 같거나 높은 단계인 상품 211건 중 160건(단계가 거칠어 과대 추정 가능).
- 몰 상품명 GPU 와 기본 구성 GPU 가 다른 상품 3건(90631·128599·129805) — 관리자 표에 표시만.

### 2026-09-22 ~ 09-25 (방향 전환 이전, 결과는 남아 있음)
- S2 게임 근거 `game_context` 형제 필드 (A-137, `b6ab16e`) · 게임 별칭 표 `talk_game_aliases` 0113 (A-138, `03fdc74`).
- 부품 조합 균형 — 보조 슬롯 최저가 (A-139, `ef7b35e`) · 비게임 격자 구간 이동 0114 (`803f717`).
- 몰 완제PC 212건 수집(`tools/mall_builtpc_fetch.py`, 워크플로 `mall-fetch.yml`) · 몰 시중가를 `products.market_price` 에 202건 반영 (A-140, `mall-price.yml`).
- 서버 VM self-hosted 러너 자동 배포 구축 (`979c427` 외, 아래 §5).

## 3. 진행 중 / 대기 중인 작업

- **격자 재생성 — 보류.** 2026-09-25 15:06 사장님 「일단 보류.. 기획을 해서 줄께」. 빈칸 채우기 안
  (판매 상품 표 203칸 중 113칸 참, 빈 90칸은 전부 「몰 상품이 그 가격대보다 비쌈」)은 **미승인·미착수**.
  사장님 기획이 오면 그것을 새 기준으로 삼는다. **그 전에 격자 생성 재개 금지.**
- **디자인·조판 GPU 하한 기획** (`docs/design/plan-design-gpu-floor-2026-09-25.md`, 안 ㉮/㉯) — 방향 전환으로 **미적용 폐기 상태**. 되살릴 땐 실측 근거부터 다시 확인.
- **mvp2 실화면 확인** — ④ 배포 뒤 사장님 육안 확인 결과를 아직 못 받음 (클라우드는 브라우저 없음) — 「확인 필요」.
- 결정 로그에 2026-09-25 재설계(①~④)가 **아직 등재 안 됨** (마지막 A-140). 다음 기록 때 A-141 로 등재.
- 사장님 결정 대기(임의로 채우지 않는다): U-59 조사 붙은 줄임말(「롤이랑」) · U-60 피파·스타·와우 별칭 ·
  U-61 고객 화면 내부 필드명 노출(`mockups/mvp2/app.js`) · U-62 회귀 [62] DB 항목 기존 FAIL.
- 게임 근거 문구 86종은 관리자 `/admin2/game-copy-review` 에서 **승인 클릭**을 해야 고객에게 나간다 (0112 기준 전부 대기였음 — 현재 상태 「확인 필요」).

## 4. 알려진 문제

- **회귀 미실행 상태.** 서버 회귀가 `/etc/popcorn-ai.env` 에 `ADMIN_PW` 이름의 값이 없어 멈췄다(run 35804371636). 이후 설정 여부 「확인 필요」. 회귀는 운영 Cloud SQL 에 검사용 행을 넣고 지우므로 수동 실행만.
- **재설계(③④)를 지키는 회귀 항목이 없다** — `tests/regression.py` 에 `sold_reco`·`product-fit` 검사 없음.
- 기준표 CPU/GPU 지수는 근사치 — 정밀 벤치 아님. 「판매 이유 점검」 160건은 과대 추정 가능.
- 평가 원천이 ChatGPT 수집 엑셀(2026-09-25 스냅샷)이다. 몰 상품이 바뀌면 재평가 → 새 날짜 시드 → 새 마이그레이션 필요(자동 갱신 없음).
- `deploy/verify.sh` 는 낡아서 **항상 exit 0** — 배포 게이트에서 뺐다. 현행화 미착수.
- 고객 인증은 여전히 dev 어댑터(`api/customer_auth.py`, 이메일만 확인) — CLAUDE.md 「베타 배포 상태」 참조.
- 몰에 테스트 상품 pd_no 123456 「테스트용PC」가 공개로 남아 있음.

## 5. 실행·검증 방법

**배포 (지금 방식 — 예전의 「PC 에서 git pull → alembic → 서버 배포」는 낡았다)**
- `main` 에 푸시 → 서버 VM `popcorn-app` 의 self-hosted 러너(라벨 `popcorn-vm`, 계정 `ghrunner`)가
  `.github/workflows/deploy.yml` 로 **자동 배포**: pull · pip · `alembic upgrade head` · `popcorn-api` 재시작 · 헬스체크.
  `*.md`·`docs/**` 만 바뀐 커밋은 건너뛴다. 결과는 GitHub Actions 「배포」 실행에서 본다.
- root 작업은 서버 고정 스크립트 `/usr/local/bin/popcorn-ci` 한 곳(원본 `deploy/popcorn-ci`). 허용 부명령:
  `deploy | regression | verify | grid | grid-dry | mall-price | mall-price-dry`. **`deploy/popcorn-ci` 를 바꾸면 사장님이 서버에서 `sudo install` 을 다시 해야 반영된다.** 설치 절차 `deploy/RUNNER.md`.
- 수동 워크플로(Actions 탭, workflow_dispatch): `regression.yml`(회귀) · `grid.yml`(격자, dry 가능 — **보류 중**) ·
  `mall-fetch.yml`(몰 수집) · `mall-price.yml`(시중가 반영, dry 가능).

**로컬(사장님 PC, Windows)**
- API: `.venv` + `uvicorn api.main:app` (8000). DB 접속은 루트 `.env`(gitignore)의 `DATABASE_URL`.
- 현재 수: `.venv/Scripts/python scripts/state.py`
- 회귀: API 서버 띄운 뒤 `.venv/Scripts/python tests/regression.py --quiet`
- 재평가: `tools/product_fit.py` (DB 불필요, 엑셀·JSON·시드 출력)

**클라우드 컨테이너(이 하네스)**
- 되는 것: 코드 수정·정적 검사·커밋·푸시, `github.com`, `popcornai.co.kr` HTTPS.
- 안 되는 것: DB 5432 · SSH 22 (설정으로도 불가), Actions 로그·산출물 zip 다운로드 → 서버 결과는 데이터 가지에 커밋해 받는다.
- 브라우저 없음 — 화면 확인은 node 가짜 document 로 대신하고 육안은 사장님 몫.
- 첫 턴: `add_repo` → clone → `register_repo_root` (그래야 `.claude/agents/` 11명이 잡힌다).

## 6. 로컬과 배포 서버의 차이

| | 사장님 PC | 서버 VM `popcorn-app` (개발/스테이징) |
|---|---|---|
| 코드 | `D:/DEV/popcorn-ai` (CRLF 683 M 파일) | `/srv/popcorn-ai`, 러너가 main 을 받음 |
| 설정 | 루트 `.env` | `/etc/popcorn-ai.env` (계정 `popcorn`만 읽음, 러너 `ghrunner` 는 못 읽음) |
| 실행 | `uvicorn` 수동 | systemd `popcorn-api`, `127.0.0.1:8000` + nginx(`deploy/nginx-popcorn.conf`) |
| DB | 같은 Cloud SQL `popcorn-db` / `popcorn_pc` 를 공유 | 동일 |
| 테스트 표시 | `X-Popcorn-Test` 헤더가 먹힘(localhost) | 헤더 **항상 무시** — 배치·회귀는 자기 session_id 를 직접 `data_origin='test'` 로 표시 |
| 기타 | 크롤 작업공간 `D:/Hermes-Workspace`, 에이전트 정의 미러 `E:\DEV\.claude\agents\` | 다나와 재수집 타이머·실패 알림(`deploy/README.md`) |

- 서버 env 주요 **이름**(값은 적지 않음): `DATABASE_URL`, `ADMIN_PW`, `POPCORN_RECO_SOURCE`(미설정 = sold), `POPCORN_ARCHIVE_DIR`, 텔레그램 알림 값.
- 주소: 고객 `https://popcornai.co.kr/mvp2/index.html` · 관리자 `https://admin.popcornai.co.kr/admin2/` · 몰 `https://popcornpc.co.kr` (`products.product_code` == 몰 `pd_no`).
- 서버는 개발/스테이징이다. 운영은 새로 세운다(decision-log I-01).

## 7. DB 마이그레이션 적용 상태

- 저장소 head = **`0115_product_usage_fit`** (down_revision 0114).
- 서버 적용: 배포 run 40(`0d2df98`, 36136189052) 이 `alembic upgrade head` 로 0115 를 적용해 **성공**, 이후 run 41(`a3e77cf`, 36143152042)도 성공 → **서버 DB = 0115 로 판단**(Actions 기록 근거, DB 직접 조회는 못 함).
- 최근: 0113 `talk_game_aliases` · 0114 비게임 격자 구간 · 0115 `product_fit_levels`/`product_fit_products`/`product_usage_fit` (시드 `db/migrations/data/product_fit_20260925.json`).
- DB 는 PC 와 서버가 공유하므로 PC 에서 따로 upgrade 할 필요는 없다. 스키마 변경 순서: ERD(`docs/06_db-erd.md`) 개정 → 새 마이그레이션.

## 8. 반드시 유지해야 할 결정

- **추천 원천 = 판매 중인 몰 조립PC** (2026-09-25). 격자 생성기는 끈 채로 둔다. 격자 재개는 사장님 기획을 받은 뒤.
- 고객에게 보이는 실제 상품은 **최대 2개**.
- 고객 화면은 **mvp2 하나** (`mockups/mvp2/`). S1~S4(mvp1)는 옛 백업.
- 게임 근거는 reasons 에 섞지 않는 `game_context` 형제 필드. 검수 게이트(`reviewed_by IS NOT NULL`)는 `api/game_copy.py` 한 곳에만.
- 워크플로에 **`sudo` 직접 쓰기·`pull_request` 트리거 금지**(공개 리포 → 포크 코드가 서버에서 돈다). root 작업은 `popcorn-ci` 에만.
- 서버 env 에 **`POPCORN_TEST_HEADER_ENABLED` 절대 넣지 않는다** (실고객 행이 test 로 숨는다, A-75).
- 러너 계정 `ghrunner` 는 `popcorn` 그룹에 넣지 않는다.
- 비밀값은 리포·설정·메모리에 저장 금지. 서버 코드 직접 수정 금지(배포 타깃).
- 작업 규칙(사장님): 3~5줄 계획 승인 후 착수 · 한 단계씩 checker 검증 · `.claude/agents/*.md` 의 `model:` 덮어쓰지 않기 · main 직접 커밋 · 보고는 짧게 핵심만 · 사장님께 시킬 일은 한 목록으로 묶기.
- `usage_alloc` 비율은 규칙으로 박지 않는다(A-139 부기 확정). 숫자를 지어내지 않는다.

### 관련 파일
- 재설계: `tools/product_fit.py` · `api/sold_reco.py` · `api/grid_public.py`(스위치) · `api/admin_product_fit.py` · `api/admin_ui_product_fit.py` · `mockups/mvp2/app.js` · `db/migrations/versions/0115_product_usage_fit.py` · `/mnt/project-files/판매상품_적합성_20260925/`
- 배포: `.github/workflows/deploy.yml` · `deploy/popcorn-ci` · `deploy/RUNNER.md` · `deploy/README.md`
- 기록: `CLAUDE.md` · `docs/decisions/decision-log.md` · `.claude/CANON.md` · `docs/design/plan-design-gpu-floor-2026-09-25.md`
- 몰 수집: `tools/mall_builtpc_fetch.py` · `tools/mall_market_price_apply.py` · `api/mall.py`

---

## 사장님께 필요한 것 (꼭 필요한 것만)

1. mvp2 에서 추천 카드(실제 상품 최대 2개)가 제대로 나오는지 한 번 확인.
2. 격자 작업 기획(보류 해제 시).
3. PC 에서 `git pull` 로 최신 main 받기(683 CRLF 파일은 그대로 둔 채).

## 2026-09-28 추가 인계 — 부품 설명 기반 마련

이 절은 위 9/25 스냅샷 이후의 변경이며 현재 DB 상태 판단에 우선한다.

- **공유 서버 DB를 직접 확인하고 0116을 적용했다.** `product_explanations` 테이블에 201종 초안 저장, 기존 상품 연결 199종 / 조립 전용 미연결 2종(127201·127203). 모두 draft이며 공개 승인 0건. 기존 상품의 가격·사양·상태·검수 플래그는 반영 전후 동일함을 확인했다.
- 설명의 제조사 전체 검증은 미완료다. 등록 이미지 주소 200종이며 실물 모델 대조 전으로 표시한다. SSD 110899·MB 113685의 출처 충돌과 RAM 127555의 용량 충돌을 설명에 기록했다. 사양 원문 부족 3종은 보완 필요로 남긴다.
- 추가 API: `/api/admin/part-explanations`(목록·상세), `/api/part-explanations/{code}`(공개 게이트). 관리자 화면 `/admin2/part-explanations`. **로컬 코드 구현·검증까지이며 서버 API/UI 배포 전**이다. 새 마이그레이션은 이미 적용됐으므로 공유 DB에 재적용 작업을 별도로 하지 않는다.
- 실제 고객 추천 화면 연결, 자유 질의 전송, 설명 수정·승인 UI는 아직 없다. 현재 질문 버튼은 FAQ 펼침이며 고객용 알뜰/추천 카드 생성·공개를 의미하지 않는다.
- 로컬 검토 자료: `C:/Users/leon2/OneDrive/Documents/ChatGPT/팝콘AI/outputs/part-explanations-20260928/`. `index.html`, `부품설명-201종.md`, `부품설명-201종.json`, DB 적용 전후 보고서와 HTTP 검사 결과를 함께 저장했다. 로컬 미리보기 `http://127.0.0.1:8766/`(정적 서버 실행 중일 때).
- 재현 도구: `tools/build_part_explanations.py`, `tools/preview_part_explanations.py`. `tools/apply_part_explanations.py --apply`는 0115→0116 최초 추가만 허용하므로 이미 반영된 DB에 다시 실행하지 않는다.
- 후속: 제조사별 실제 모델 대조 → 충돌·미연결 해결 → 승인 워크플로 → 확정 PC와 설명 연결 → 알뜰/추천 구성별 선택 이유. 104개 구성은 후보이며 모두 실제 출고 승인됐다는 뜻이 아니다.
- 이번 변경은 기존 상품 재수집/품절 상태 반영과 별개인 설명 테이블 추가 작업이다. 기존 카탈로그 수집 결과와 104개 후보 엑셀은 `outputs/final-catalog-20260928/` 및 이전 산출물에 보존돼 있다.
