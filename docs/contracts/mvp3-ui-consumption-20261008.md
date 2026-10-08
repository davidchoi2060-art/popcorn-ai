# MVP3 UI 소비 계약 (서버 → 고객 화면) — 2026-10-08

- 목적: Codex가 `mockups/mvp3/app.js`에 공개 BOM 렌더러·대표 이미지·`game_context` 처리를 통합하기 전에, 서버가 **지금 실제로 무엇을 내보내는지**를 고정한다.
- 기준: `origin/main` `1ecf4df` + PR #3(`26e026c`, 추천 응답 정리) + PR #5(`65b037e`, 보관 429) 병합 후 형태. 두 PR은 아직 병합 전이다.
- 근거: 코드와 마이그레이션 파일만 읽었다. **이 환경에서 실 DB에 접속하지 않았다.** 그래서 「실 DB 적용」 칸은 전부 「미확인」이고, 실 DB 값으로 확인한 사실은 이 문서에 없다.
- 상태 표기 세 단계: **설계**(코드·스키마 존재) / **단위 검사**(이 브랜치에서 실행해 통과) / **실 DB 적용**(운영 DB에 행이 있고 고객 경로로 나가는 것을 확인).

## 0. 요약 — 요청 항목별 현재 상태

| 항목 | 고객 경로로 나가는가 | 설계 | 단위 검사 | 실 DB 적용 |
|---|---|---|---|---|
| 추천 상품 카드(`/api/grid/recommend` sold) | 예 | 완료 | 완료(PR #3 28건) | 미확인 |
| 고객용 `reasons` | 예(추천 카드 안) | 완료 | 완료(PR #3) | 미확인 |
| `game_context` | 예(게임 용도 card_set 단위) | 완료 | 회귀 [63] 정적 검사만 | 미확인 |
| 공개 BOM(완제품 부품 구성) | **아니오 — 라우트 없음** | 함수만 있음 | 완료(투영 18건 · 읽기 32건 · 발행 36건) | 미확인 |
| 완제품 대표 사진 | **아니오 — 관리자 경로만** | 관리자용 완료 | 완료(6건) | 미확인 · **판매 SKU와 공개 연결 없음** |
| 부품별 사진 | 별도 경로로 예(게이트 문제 있음, §5.2) | 완료 | 완료(4건) | 미확인 |
| 부품별 가격 | 별도 경로로 예(부품 설명 API) · 완제품 BOM 가격은 아니오 | 완료 | 완료(4건) | 미확인 |

핵심: **MVP3 추천 카드와 완제품 BOM·대표 사진은 지금 서로 다른 원천을 본다.** 추천 카드는 `product_fit_products`(0115)에서, BOM·대표 사진은 `pc_configurations`(0117)·`pc_media_jobs`(0120)에서 나온다. 둘을 잇는 고객 라우트는 아직 없다.

## 1. 현재 판매 SKU와 configuration revision

### 1.1 「판매 중」이 정해지는 곳

추천 카드(MVP3가 실제로 받는 상품)의 판정은 `api/admin_product_fit.load()` 하나다.

```
FROM product_fit_products f LEFT JOIN products p ON p.product_code = f.product_code
제외: f.excluded 가 있음  또는  p.status ∈ ('품절','단종','삭제대기')
가격: p.sale_price 가 있으면 그것("현재 판매가"), 없으면 f.crawl_price("몰 수집가(2026-09-25)")
```

주의 둘:
- `product_fit_products.product_code`에는 `products` FK가 없다. `products`에 행이 없으면 status가 NULL이라 **제외되지 않고 수집가로 나간다.** 「`products.status='판매중'`인 것만」이 아니다.
- 공개 BOM 쪽 판정은 다르다: `products.status='판매중'` **그리고** 발행 이벤트 승인(§3). 같은 SKU라도 추천 카드에는 나오고 BOM은 404일 수 있다.

### 1.2 SKU 목록

정확한 「지금 판매 중」 목록은 실 DB의 `products.status`·`sale_price`가 정한다. 이 환경에서 실 DB를 읽지 못했으므로, 아래는 **마이그레이션에 실린 시드 기준**이다.

- 파일: [`mvp3-sold-sku-seed-20261008.csv`](mvp3-sold-sku-seed-20261008.csv) — 0115 시드(`db/migrations/data/product_fit_20260925.json`)에서 `excluded`가 빈 **211개** SKU.
- 열: `product_code, seed_name, seed_price, configuration_id_seed, configuration_source_seed`.
- 211개 중 **92개**만 완제품 구성 시드(`pc_configuration_catalog_20260928.json`)에 `offer_id='P{code}'`로 묶여 있다. **나머지 119개는 구성 행 자체가 없어 BOM·대표 사진을 낼 수 없다.**
- 구성 시드의 `summary`: `approved_for_customer: 0`, `db_written: false`(2026-09-28 기준). 그 뒤 `tools/import_pc_configuration_copy.py`로 적재됐는지는 실 DB에서 확인해야 한다.

### 1.3 configuration revision

`pc_configurations.revision`(0117, 기본값 1, 수정 때마다 +1)이 정본이다. 시드 JSON에는 revision이 없다. **SKU별 실제 revision은 실 DB에서만 나온다 — 이 문서는 값을 적지 않는다.**

실 DB에서 뽑는 읽기 전용 질의(서버 담당이 실행해 이 문서에 붙인다):

```sql
SELECT f.product_code, p.status, p.sale_price, o.offer_id, c.configuration_id, c.revision, c.status AS config_status,
       (SELECT action FROM pc_customer_publication_events e
         WHERE e.configuration_id = c.configuration_id ORDER BY event_seq DESC LIMIT 1) AS last_publication_action
FROM product_fit_products f
LEFT JOIN products p ON p.product_code = f.product_code
LEFT JOIN pc_configuration_offers o ON o.offer_id = 'P' || f.product_code
LEFT JOIN pc_configurations c ON c.configuration_id = o.configuration_id
WHERE f.excluded IS NULL AND COALESCE(p.status,'') NOT IN ('품절','단종','삭제대기')
ORDER BY f.product_code;
```

## 2. `POST /api/grid/recommend` — MVP3가 읽는 필드

`RECO_SOURCE`(환경변수 `POPCORN_RECO_SOURCE`, 기본 `sold`)가 `sold`일 때의 응답이다. MVP3 `live-model.js`는 `kind!=='sold'`인 card_set을 `unsupported`로 버린다.

### 2.1 최상위

| 필드 | 출처 | 빈 값 |
|---|---|---|
| `ok` | 항상 `true` | — |
| `card_sets[]` | §2.2 | 용도가 없거나 게임 등급이 없으면 `[]` |
| `needs[]` | `talk_schema.missing_for(state)` — `"usages"`, `"game.grade"` | `[]` |
| `assumed[]` | 해상도를 안 받았을 때 `"game.resolution=1080p"` | `[]` |
| `ai_estimated[]` | `state.game.grade_src=="ai_estimate"`일 때 `{game_names, grade}` | `[]` |
| `dropped[]` | `validate_state`가 접은 값 `{field,value,reason}` | `[]` |
| `platform` · `budget_won` · `budget_bound` · `game_grade` · `game_resolution` · `game_name` | 입력 state 정규화 결과 | 없으면 `null` |
| `cards[]` | 하위호환, sold 경로는 항상 `[]` | — |

`notes`는 PR #3에서 응답에서 뺐다(서버 로그로만 간다).

### 2.2 `card_sets[]` (kind `sold`)

| 필드 | 출처 | 빈 값 |
|---|---|---|
| `kind` | `"sold"` 고정 | — |
| `usage` | 고객 용도 라벨(입력 그대로) | — |
| `usage_grid` | 평가 용도(`sold_reco.USAGE_RULES`로 매핑) | 매핑 안 되는 용도는 card_set 자체가 없다 |
| `min_level` · `min_level_work` | `product_fit_levels.level` · `.work` | 해당 단계가 없으면 `null` |
| `items[]` | §2.3, 최대 2개 | `[]` 가능 |
| `empty_reason` · `empty_note` | `"보유 상품 없음"` 또는 `"예산 안 상품 없음"` + 문장 | 상품이 있으면 `null` |
| `game_context` | §4. **게임 용도 card_set에만 키가 생긴다** | 검수 통과 문구가 없으면 `null`. 비게임 card_set에는 키가 없다 |
| `cards` · `empty_cells` · `omitted_variants` · `center_*` · `bands_considered` · `tiers_considered` | 옛 화면 호환 | 항상 빈 값 |

`"예산 안 상품 없음"`일 때 `items`에는 예산을 넘는 최저가 1개가 `over_budget: true`로 들어 있다.

### 2.3 `items[]`

| 필드 | 출처 | 빈 값·규칙 |
|---|---|---|
| `product_code` | `product_fit_products.product_code` | 정수 |
| `name` | `product_fit_products.crawl_name` (몰 수집명, `products.product_name` 아님) | 문자열 |
| `price` | `products.sale_price`, 없으면 `crawl_price` | `price is None`인 상품은 후보에서 빠지므로 응답에는 항상 정수 |
| `price_src` | `"현재 판매가"` 또는 `"몰 수집가(2026-09-25)"` | 화면은 그대로 표시한다 |
| `mall_url` | `product_fit_products.mall_url` | `null` 가능 |
| `spec` | `product_fit_products.spec` → `sold_reco.public_spec()` | dict면 `cpu`·`gpu`(문자열), `ram_gb`·`ssd_gb`·`vram_gb`(0 이상 수)만. 없는 키는 아예 없다. dict가 아니면 문자열 또는 `null` |
| `level` | `product_usage_fit.level` | 문자열 |
| `tag` | `"예산 안 최고 수준"` · `"가장 저렴한 선택"` · `"같은 수준 다른 구성"` · `"한 단계 위"` · `"예산을 넘는 최저가"` | — |
| `over_budget` | `price > budget_won`(하한 예산 `이상`이면 항상 false) | bool |
| `reasons[]` | §2.4 | 최소 1줄 |

**추천 카드에는 BOM·사진·부품 가격 필드가 없다.** 지금 MVP3가 이 응답만으로 BOM이나 사진을 그리려면 값을 지어내야 한다.

### 2.4 고객용 `reasons` (PR #3 이후)

순서대로:
1. `"{usage_grid} {level} — {product_fit_levels.work}"` — 항상 1줄.
2. 다음 수준 안내 0~2줄 — `product_usage_fit.blocked` 원문이 `tools/product_fit.check()`의 고정 틀과 **전체 일치**할 때만 Codex 확정 문구로 바꿔 싣는다(8종). 「미확인」 행과 CPU 게임 등급은 싣지 않고 서버 로그로만 남긴다.
3. `"판매가에 {includes} 포함"` — `product_fit_products.includes`가 있을 때만.

내부 지수(`cpu_mt` 등)·조건 원문·「충족 조건:」 줄은 응답에 없다.

## 3. 공개 BOM — 설계만 있고 고객 경로는 없다

- 함수: `api/customer_sold_offer_read.read_customer_sold_offer(conn, product_code, source_reader=...)`. 파일 첫 줄이 "No route"이고, 호출처는 테스트뿐이다. **고객 라우트 0개.**
- 연결 키: `offer_id = 'P' + str(product_code)` → `pc_configuration_offers.offer_id`(PK) → `configuration_id` → `pc_configurations`(PK). `products`와 FK는 없고 문자열 규약이다(`api/pc_configuration_copy.py:99-144`).
- 공개 게이트(전부 만족해야 200, 아니면 `{status:404, error:'not_public'}`):
  - `products.status = '판매중'`
  - `pc_customer_publication_events`(0129)의 최신 이벤트가 `approve`이고 근거 해시가 현재 구성과 일치(`pc_customer_publication.read_current` → `state='approved'`, `source_state='current'`)
  - 부품마다 `product_explanations` 승인·판매중·현재본 + 부품 사진 승인 증빙(§5)
  - 읽기 전용 REPEATABLE READ 스냅샷 트랜잭션 안에서 호출
- 200일 때 `data` 필드(`api/customer_pc_projection.py:171-183`):

| 필드 | 내용 |
|---|---|
| `configuration_id` · `revision` · `offer_id` · `product_code` | 식별자 |
| `description` | `{title, intro, scene, benefits, checks, faq}` — `pc_configurations.content` |
| `parts[]` | `{ordinal, slot, quantity, pseudo, name, description, specs[{label,value}]}` — `pc_configuration_parts` + `product_explanations.content`. `pseudo` 부품은 이름·설명이 `null`, specs `[]` |
| `price` | `{state, amount, checked_at, observed_date, model}` — **이 호출 경로는 가격을 넘기지 않아 `state='unknown'`, `amount=null`** |
| `stock` | `{state:'unknown', checked_at}` — 같은 이유 |
| `compatibility` | `{document_state:'unknown', public_summary, assembly_state}` |
| `customer_conditions` | `os·keyboard·mouse·monitor·warranty` 각 `{state, detail, months, needs_reconfirmation, customer_statement}` |
| `photo` | **항상 `{state:'unresolved', url:null}`** — 서버가 의도적으로 고정한다 |

**부품별 가격은 BOM 응답에 없다.** 완제품 가격 `pc_configuration_offers.price_snapshot`도 이 응답으로 나가지 않는다.

## 4. `game_context`

- 위치: sold 경로에서는 **게임 용도 card_set 객체의 키**다(`api/grid_public.py` `recommend`). 상품(item)마다 붙지 않는다.
- 출처: `game_customer_copy`(0103) JOIN `games`, 게이트 `reviewed_by IS NOT NULL`(검수 승인, 0112). 고객이 말한 게임명을 순서대로 `games.name`에 대응시켜 **처음으로 검수를 통과한 한 게임**만 싣는다.
- 모양:

```json
{"game_name": "...", "spec_summary": "...", "why_this_pc": "...", "upgrade_hint": "...", "caution": "...",
 "source": {"kind": "game_customer_copy", "fields": ["..."], "url": "..."},
 "confidence": "...", "reviewed_at": "ISO 8601"}
```

- 빈 값: 게임명이 없거나 대응되는 게임이 없거나 검수 통과 문구가 없으면 `null`. 개별 문자열 필드도 `null`일 수 있다. 화면은 `null`이면 영역을 그리지 않는다.
- `reasons`와 섞지 않는다(엔진 계산 대 사람 검수 — 원천과 갱신 주기가 다르다).

## 5. 사진과 가격의 SKU 연결

### 5.1 완제품 대표 사진

- 테이블 `pc_media_jobs`(0120·0121): `job_id` PK, `configuration_id` FK, `selected`(구성당 하나, 부분 UNIQUE), `status`, `visual_basis`, `asset{bucket,key,sha256,notice}`.
- 저장: 객체 저장소 키 `pc-configurations/{job_id}/representative.png`.
- 「현재」 판정: `selected AND status='ready'`이고 `visual_basis`가 현재 구성의 visual_basis와 같을 때. 다르면 `representative_image_stale`.
- 서빙: `/api/admin/pc-media/{configuration_id}/images/{job_id}` **하나뿐(관리자 인증, `Cache-Control: private`)**.
- **판매 SKU와의 공개 연결: 미연결.** 고객 라우트가 없고, 공개 BOM도 `photo`를 `unresolved`로 고정한다. 대표 PNG가 저장소에 몇 개 있든 `product_code → offer → configuration → selected job` 경로를 고객에게 여는 코드가 없다.

### 5.2 부품별 사진

- 원천: `product_explanations.content->'image_asset'`(`{bucket, detail_key, thumbnail_key, detail_sha256}`), 키 `source_product_code`(0116). 부품 BOM 행은 `pc_configuration_parts.explanation_code`로 여기에 붙는다.
- 승인 이력: `part_photo_approval_events`(0131) — `approve|revoke`, 출처·권리 근거.
- 고객 경로: `GET /api/product-images/{code}/{detail|thumbnail}`(`api/product_images.py`). **⚠ 이 라우트는 `image_asset`만 있으면 서빙하고, 부품 사진 승인 이벤트나 설명 승인 여부를 보지 않는다.** 공개 BOM의 사진 게이트와 기준이 다르다. 서버 쪽 후속 항목으로 둔다(이 PR에서 고치지 않음).
- `GET /api/part-explanations/{code}`는 설명이 승인·판매중·현재본일 때만 200이고 `image_url=/api/product-images/{code}/detail`을 준다.

### 5.3 부품별 가격

- `GET /api/part-explanations/{code}`의 `price` = `products.sale_price`(`price_basis: "현재 부품 판매가"`). 부품 단독 가격이다.
- 완제품 BOM 안에서 부품별로 가격을 나눈 값은 **어디에도 없다.** `pc_configuration_offers.price_snapshot`은 완제품 총액이다. 부품 판매가의 합은 완제품 판매가와 다르다(조립·포함 품목) — 화면이 부품가를 더해 총액처럼 보이면 안 된다.

## 6. 다른 고객 경로 (참고)

- `GET/POST /api/mvp3/saved-quotes`: quote = `{id, product, state, saved_at}`. `product`는 추천 item과 같은 공개 필드 + `price_confirmed:false`. 429 계약은 PR #5 본문.
- `POST /api/talk/parse`: 최상위에 `provider`·`model`·`cost_usd`·`tokens_in`·`tokens_out`·`answer_provider`·`answer_model`·`answer_cost_usd`·`answer_error`가 실려 나간다. 추천 응답과 같은 종류의 내부 값 노출이라 서버 쪽 후속 항목으로 둔다. MVP3는 이 값을 읽지 않아야 한다.

## 7. 화면 통합 전에 서버가 해야 할 것 (Claude 담당)

1. 실 DB에서 §1.3 질의를 돌려 SKU별 configuration·revision·발행 상태를 이 문서에 붙인다.
2. 공개 BOM을 고객에게 열려면 `read_customer_sold_offer`를 부르는 고객 라우트와 `source_reader`를 새로 지어야 한다(설계 결정 필요, 별도 PR).
3. 대표 사진을 고객에게 열려면 승인된 구성에 한해 `selected` 현재본만 서빙하는 고객 라우트가 필요하다(별도 PR).
4. `/api/product-images`에 승인 게이트를 맞춘다. `/api/talk/parse`의 내부 값을 걷는다.

그 전까지 MVP3는 추천 카드(§2)와 `game_context`(§4)만 소비할 수 있다. BOM·대표 사진 영역은 서버 값이 없으므로 그리지 않는다.

## 8. 이 문서를 만들 때 실행한 검사

- 브랜치 `origin/main` `1ecf4df`, `DATABASE_URL`은 접속 불가 더미.
- `tests.test_customer_pc_projection` 18건, `tests.test_customer_sold_offer_read` 32건, `tests.test_part_explanations` 4건, `tests.test_pc_customer_publication` 36건, `tests.test_pc_media` 6건 통과.
- `tests.test_pc_configuration_offer_binding` 25건 중 1건 실패: `test_original_whole_ast_imports_routes_and_functions_are_unchanged`(고정해 둔 `pc_configuration_copy.py` AST 해시 불일치). `main`에서 이미 실패하는 상태이고 이 문서 변경과 무관하다.
- 추천 응답 형태는 PR #3 브랜치의 `tests/test_grid_recommend_public_response.py`(28건 통과)와 `tests/fixtures/grid_recommend_sold_response.json`이 고정한다.
