# CI 전용 변경을 자동 배포에서 분리하는 안 (초안, 2026-10-08)

> 상태: **설계 초안**. deploy.yml 적용 · main 병합 · dispatch 승인이 아니다.
> 요청: PR #2 코멘트 6056806017 (PC 쪽). 작성: 클라우드 쪽 검사 · PR 흐름 담당.
> 근거로 읽은 것: main `1ecf4df` 의 `.github/workflows/deploy.yml`, `deploy/popcorn-ci`,
> `tests/regression.py`, PR #1 · #13 파일 목록. 아무것도 실행하지 않았다.

## 1. 지금 무엇이 문제인가

- `deploy.yml` 은 `push: branches: [main]` 에 `paths-ignore: ['docs/**', '**/*.md']` 만 건다.
- PR #1 (5파일) · PR #13 (3파일) 은 앱 코드를 하나도 안 바꾸지만 docs 밖 파일이라,
  main 에 들어가는 순간 `popcorn-ci deploy` 가 돈다:
  코드 받기(ff-only) → `pip install -r requirements.txt` → **`alembic upgrade head`** → 재시작 → 헬스 체크.
- PC · 클라우드 양쪽이 같은 결론을 확인했다(6056777081 · 6056806017).

## 2. 기준 (PC 쪽 제시, 그대로 따른다)

1. `[skip ci]` 로 unit 까지 건너뛰지 않는다. `tests/**` 같은 넓은 제외도 쓰지 않는다.
2. **정확한 CI 파일 경로만** 제외한다.
3. 제품 파일이 하나라도 섞이면 기존대로 배포한다.
4. `deploy.yml` 자체와 다른 workflow 변경은 CI 전용으로 취급하지 않는다(배포한다).
5. `workflow_dispatch`(손 배포 · 회귀)의 기존 의미는 그대로 둔다.

## 3. 변경안 (deploy.yml, 후보)

```diff
 on:
   push:
     branches: [main]
     paths-ignore:
       - 'docs/**'
       - '**/*.md'
+      # CI 전용 파일 — 서버 배포(popcorn-ci deploy)가 읽지 않는다. 정확한 경로만 적는다.
+      # 여기 없는 파일이 하나라도 섞이면 배포가 돈다. 넓은 glob(tests/** 등)을 쓰지 않는다.
+      - '.github/workflows/unit.yml'
+      - 'requirements-test.txt'
+      - 'tests/ci_run.py'
+      - 'tests/conftest.py'
+      - 'tests/test_ci_run.py'
+      - 'tests/bundle_run.py'
+      - 'tests/test_bundle_run.py'
   workflow_dispatch:
```

### 각 경로를 넣어도 되는 근거

| 경로 | 서버 배포가 쓰나 | 근거 |
|---|---|---|
| `.github/workflows/unit.yml` | 아니다 | ubuntu-latest 에서만 돈다. 서버는 workflow 를 읽지 않는다 |
| `requirements-test.txt` | 아니다 | `popcorn-ci` 59행은 `requirements.txt` 만 설치한다 |
| `tests/ci_run.py` · `tests/test_ci_run.py` | 아니다 | unit job 전용 실행기 |
| `tests/conftest.py` | 아니다 | pytest 전용. 서버 회귀는 `tests/regression.py` 를 스크립트로 실행하고(`popcorn-ci` 86행) 그 파일은 표준 라이브러리만 import 한다 |
| `tests/bundle_run.py` · `tests/test_bundle_run.py` | 아니다 | bundle job 전용 |

**넣지 않는 것:** `tests/regression.py` (dispatch 회귀가 서버에서 실행한다), 그 밖의 `tests/*` (지금 목록에 없는 새 파일은 보수적으로 배포 쪽에 둔다 — CI 전용임이 확실해지면 한 줄씩 추가한다).

## 4. 반례 표 (기대 동작)

GitHub 규칙: push 의 바뀐 파일이 **전부** `paths-ignore` 에 걸릴 때만 건너뛴다. 하나라도 안 걸리면 돈다.

| # | push 에 담긴 변경 | 기대 | 이유 |
|---|---|---|---|
| 1 | PR #1 의 5파일만 | 건너뜀 | 전부 목록 안 |
| 2 | PR #13 의 3파일만 | 건너뜀 | 전부 목록 안 |
| 3 | PR #1 5파일 + `api/main.py` | **배포** | 제품 파일 섞임 (기준 3) |
| 4 | `.github/workflows/deploy.yml` 만 | **배포** | 목록 밖 (기준 4) |
| 5 | `unit.yml` + `regression.yml` | **배포** | 다른 workflow 섞임 (기준 4) |
| 6 | `tests/regression.py` 만 | **배포** | 서버가 dispatch 회귀에 쓴다 |
| 7 | `tests/test_새파일.py` 만 | **배포** | 정확 경로가 아니다 (보수적) |
| 8 | `requirements.txt` 만 | **배포** | 서버가 설치한다 |
| 9 | `tests/ci_run.py.bak` | **배포** | glob 이 아니라 정확 경로 |
| 10 | `docs/x.md` 만 | 건너뜀 | 기존 규칙 그대로 |
| 11 | workflow_dispatch (손 실행) | **배포** | paths 필터는 push 에만 적용된다 (기준 5) |

건너뛴 CI 커밋이 쌓여도 서버가 어긋나지 않는다: 다음 정상 배포가 `merge --ff-only FETCH_HEAD` 로 그 커밋들을 함께 받는다(`popcorn-ci` 46~54행). 그 사이 서버 트리의 CI 파일만 main 보다 뒤처지고, 서버는 그 파일을 읽지 않는다.

### 알려진 한계

- GitHub 문서 기준으로 경로 필터는 diff 를 최대 300파일까지만 본다. 한 push 가 300파일을 넘으면 판정이 어긋날 수 있고, 그 방향이 「배포 누락」일 수도 있다. 그래서 300파일을 넘는 main push 뒤에는 배포가 실제로 돌았는지 확인한다(PR #1 · #13 은 5 · 3파일, PR #10 은 51파일).
- 판정은 push 의 before..after 차이로 한다. 여러 PR 을 한 번에 push 하면 합집합으로 판정한다(제품 파일이 하나라도 있으면 배포 — 안전한 쪽).

## 5. 이 변경을 처음 넣는 커밋 자체가 배포를 일으킨다

변경 대상이 `deploy.yml` 이고, 기준 4 에 따라 `deploy.yml` 은 목록에 넣지 않는다. 그래서
**이 분리안을 담은 커밋은 반드시 한 번 배포를 돌린다.** push 이벤트는 그 커밋의 새 workflow
정의로 판정하지만, 바뀐 파일(`deploy.yml`)이 새 목록에도 없으니 결과는 같다.

`[skip ci]` 와 배포 중지 없이 가는 길은 둘이다.

**A. 다음 정규 배포에 얹는다 (추가 배포 0회, 추천)**
- 어차피 배포될 제품 변경(예: 0133 PR #11, PC 작업 PR #10)과 **같은 push** 로 main 에 넣는다.
- 그 배포는 이미 승인 절차를 거치는 배포라, 분리안 때문에 늘어나는 배포가 없다.
- 순서: 분리안이 들어간 정규 배포 → PR #1 → PR #13 (둘 다 건너뜀).
- 조건: 그 정규 배포의 승인 · 운영 조건(아래 B 와 같음)을 그대로 충족해야 한다.

**B. 단독으로 넣고 한 번의 무변경 재배포를 받아들인다**
- 현재 main 위에 deploy.yml 한 파일만 바꾼 커밋. 앱 코드 · requirements · migration 변경 0.
- 서버에서 일어나는 일: ff-only 로 그 커밋만 받기 → 같은 requirements 재설치 → `alembic upgrade head`(서버가 이미 main head 면 무변경) → 재시작(수 초 중단) → 헬스 체크.
- 필요한 운영 조건 (PC 배포 담당 확인 몫):
  1. 서버 HEAD 가 main 의 조상이다(아니면 ff-only 에서 멈춘다 — 배포 실패이지 손상은 아니다).
  2. 서버 `alembic current` 가 main 의 head 와 같다(다르면 이 배포가 밀린 migration 을 실제로 적용한다 — 이것이 「강제 migration」 위험의 실체다).
  3. 재시작 중 짧은 중단을 받아들일 수 있는 시간대.
  4. 되돌림 경로(이전 커밋으로 ff 불가 시의 절차)가 확인돼 있다.
- 1 · 2 를 확인하지 못하면 B 는 고르지 않는다. 그 경우 A 로 간다.

A · B 어느 쪽이든 PR #1 · #13 의 병합은 분리안이 main 에 들어간 **뒤** 에 한다.

## 6. 배포 없이 필터만 미리 검증하는 방법 (선택)

self-hosted 러너를 건드리지 않고 판정 규칙만 확인할 수 있다.

- 임시 브랜치 `probe/paths-ignore` 에만 존재하는 시험 workflow 를 둔다:
  `runs-on: ubuntu-latest`, `on: push: branches: [probe/paths-ignore]`, 위 3절과 **같은** paths-ignore, 본문은 `echo ran`.
- 4절 반례 1 · 2 · 3 · 4 · 6 · 9 를 그 브랜치에 한 커밋씩 push 해 실행 여부를 본다.
- 끝나면 브랜치를 지운다. main · deploy.yml · 서버 변경 0.
- 이 시험 자체는 PC 쪽 동의 뒤에 클라우드 쪽이 돌린다.

## 7. 소유 경계 (제안)

| 무엇 | 담당 |
|---|---|
| 이 문서 · 반례 표 · 6절 시험 | 클라우드(검사 · PR 흐름) |
| 5절 운영 조건 1~4 확인 · A/B 선택 | PC 배포 담당 |
| deploy.yml 후보 PR 작성 | 합의 후 정한다 |
| main 병합 · 배포 승인 | 중헌님 |
