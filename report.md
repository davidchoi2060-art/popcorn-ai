# /mvp4 부품 사진 측정 — https://dev.popcornai.co.kr/mvp4/

측정 2026-10-29T02:00:02.324Z ~ 2026-10-29T02:29:05.519Z · 비교 before / after · 표본(보통 망) 3, 느린 망·실패 주입 1

열: 구성 GET(offer+registered) · 부품 사진 요청 = 네트워크 200 / 304 / 캐시(memory·disk) · 고유 주소 · 같은 주소를 네트워크로 두 번 이상 받은 수 · 부품 사진 전송 bytes · 카드 첫 부품 사진 표시(중앙값, 단계 시작 기준 ms) · 아이콘 대체 수

## pc1440

| 단계 | 비교 | n | 구성 GET | 사진 200 | 304 | 캐시 | 고유 | 중복 재전송 | 사진 bytes | 첫 사진 ms | 아이콘 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1-first-load-cold | before | 3 | 17 | 23 | 0 | 0 | 23 | 0 | 1863KB | 8529 | 0 |
| 1-first-load-cold | after | 3 | 17 | 23 | 0 | 0 | 23 | 0 | 1863KB | 6893 | 0 |
| 2-more | before | 3 | 22 | 6 | 0 | 0 | 6 | 0 | 538KB | 68 | 0 |
| 2-more | after | 3 | 22 | 6 | 0 | 0 | 6 | 0 | 538KB | 68 | 0 |
| 3-sort-price-asc | before | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0KB | 23 | 0 |
| 3-sort-price-asc | after | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0KB | 23 | 0 |
| 4-filter-category | before | 3 | 6 | 3 | 0 | 0 | 3 | 0 | 177KB | 33 | 0 |
| 4-filter-category | after | 3 | 6 | 3 | 0 | 1 | 4 | 0 | 177KB | 34 | 0 |
| 5-reset-filter | before | 3 | 0 | 0 | 0 | 5 | 5 | 0 | 0KB | 22 | 0 |
| 5-reset-filter | after | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0KB | 23 | 0 |
| 6-detail | before | 3 | 1 | 0 | 0 | 1 | 1 | 0 | 0KB | - | 0 |
| 6-detail | after | 3 | 1 | 0 | 0 | 0 | 0 | 0 | 0KB | - | 0 |
| 7-back | before | 3 | 17 | 0 | 0 | 23 | 23 | 0 | 0KB | 5748 | 0 |
| 7-back | after | 3 | 17 | 0 | 0 | 23 | 23 | 0 | 0KB | 5009 | 0 |
| 8-reload-warm | before | 3 | 17 | 0 | 0 | 23 | 23 | 0 | 0KB | 5591 | 0 |
| 8-reload-warm | after | 3 | 17 | 0 | 0 | 23 | 23 | 0 | 0KB | 4625 | 0 |

## pc1440-slow

| 단계 | 비교 | n | 구성 GET | 사진 200 | 304 | 캐시 | 고유 | 중복 재전송 | 사진 bytes | 첫 사진 ms | 아이콘 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1-first-load-cold | before | 1 | 17 | 23 | 0 | 0 | 23 | 0 | 1863KB | 25395 | 0 |
| 1-first-load-cold | after | 1 | 17 | 23 | 0 | 0 | 23 | 0 | 1863KB | 23709 | 0 |
| 2-more | before | 1 | 22 | 1 | 0 | 0 | 1 | 0 | 69KB | 68 | 0 |
| 2-more | after | 1 | 22 | 1 | 0 | 0 | 1 | 0 | 69KB | 78 | 0 |
| 3-sort-price-asc | before | 1 | 0 | 5 | 0 | 0 | 5 | 0 | 469KB | 24 | 0 |
| 3-sort-price-asc | after | 1 | 0 | 5 | 0 | 0 | 5 | 0 | 469KB | 14 | 0 |
| 4-filter-category | before | 1 | 6 | 3 | 0 | 0 | 3 | 0 | 177KB | 40 | 0 |
| 4-filter-category | after | 1 | 6 | 3 | 0 | 0 | 3 | 0 | 177KB | 36 | 0 |
| 5-reset-filter | before | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0KB | 20 | 0 |
| 5-reset-filter | after | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0KB | 23 | 0 |
| 6-detail | before | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0KB | - | 0 |
| 6-detail | after | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0KB | - | 0 |
| 7-back | before | 1 | 17 | 0 | 0 | 23 | 23 | 0 | 0KB | 8284 | 0 |
| 7-back | after | 1 | 17 | 0 | 0 | 23 | 23 | 0 | 0KB | 6631 | 0 |
| 8-reload-warm | before | 1 | 17 | 0 | 0 | 23 | 23 | 0 | 0KB | 8271 | 0 |
| 8-reload-warm | after | 1 | 17 | 0 | 0 | 23 | 23 | 0 | 0KB | 6167 | 0 |

## m390

| 단계 | 비교 | n | 구성 GET | 사진 200 | 304 | 캐시 | 고유 | 중복 재전송 | 사진 bytes | 첫 사진 ms | 아이콘 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1-first-load-cold | before | 3 | 17 | 23 | 0 | 0 | 23 | 0 | 1863KB | 5864 | 0 |
| 1-first-load-cold | after | 3 | 17 | 23 | 0 | 0 | 23 | 0 | 1863KB | 5013 | 0 |
| 2-more | before | 3 | 22 | 6 | 0 | 0 | 6 | 0 | 538KB | 69 | 0 |
| 2-more | after | 3 | 22 | 6 | 0 | 0 | 6 | 0 | 538KB | 68 | 0 |
| 3-sort-price-asc | before | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0KB | 25 | 0 |
| 3-sort-price-asc | after | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0KB | 25 | 0 |
| 4-filter-category | before | 3 | 6 | 3 | 0 | 0 | 3 | 0 | 177KB | 37 | 0 |
| 4-filter-category | after | 3 | 6 | 3 | 0 | 0 | 3 | 0 | 177KB | 33 | 0 |
| 5-reset-filter | before | 3 | 0 | 0 | 0 | 1 | 1 | 0 | 0KB | 24 | 0 |
| 5-reset-filter | after | 3 | 0 | 0 | 0 | 1 | 1 | 0 | 0KB | 22 | 0 |
| 6-detail | before | 3 | 1 | 0 | 0 | 2 | 2 | 0 | 0KB | - | 0 |
| 6-detail | after | 3 | 1 | 0 | 0 | 2 | 2 | 0 | 0KB | - | 0 |
| 7-back | before | 3 | 17 | 0 | 0 | 23 | 23 | 0 | 0KB | 5161 | 0 |
| 7-back | after | 3 | 17 | 0 | 0 | 23 | 23 | 0 | 0KB | 4386 | 0 |
| 8-reload-warm | before | 3 | 17 | 0 | 0 | 23 | 23 | 0 | 0KB | 4809 | 0 |
| 8-reload-warm | after | 3 | 17 | 0 | 0 | 21 | 21 | 0 | 0KB | 4168 | 0 |

## m390-slow

| 단계 | 비교 | n | 구성 GET | 사진 200 | 304 | 캐시 | 고유 | 중복 재전송 | 사진 bytes | 첫 사진 ms | 아이콘 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1-first-load-cold | before | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0KB | - | 0 |
| 1-first-load-cold | after | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0KB | - | 0 |
| 2-more | before | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0KB | - | 0 |
| 2-more | after | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0KB | - | 0 |
| 3-sort-price-asc | before | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0KB | - | 0 | 오류 1건: page.selectOption: Timeout 30000ms exceeded. Call log:   - waiting for locator('[data-dp-filter-form] select[name=sort]'
| 3-sort-price-asc | after | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0KB | - | 0 | 오류 1건: page.selectOption: Timeout 30000ms exceeded. Call log:   - waiting for locator('[data-dp-filter-form] select[name=sort]'
| 4-filter-category | before | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0KB | - | 0 |
| 4-filter-category | after | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0KB | - | 0 |
| 5-reset-filter | before | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0KB | - | 0 | 오류 1건: page.selectOption: Timeout 30000ms exceeded. Call log:   - waiting for locator('[data-dp-filter-form] select[name=catego
| 5-reset-filter | after | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0KB | - | 0 | 오류 1건: page.selectOption: Timeout 30000ms exceeded. Call log:   - waiting for locator('[data-dp-filter-form] select[name=catego
| 6-detail | before | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0KB | - | 0 | 오류 1건: page.waitForURL: Timeout 30000ms exceeded. =========================== logs =========================== waiting for navi
| 6-detail | after | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0KB | - | 0 | 오류 1건: page.waitForURL: Timeout 30000ms exceeded. =========================== logs =========================== waiting for navi
| 7-back | before | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0KB | - | 0 |
| 7-back | after | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0KB | - | 0 |
| 8-reload-warm | before | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0KB | - | 0 |
| 8-reload-warm | after | 1 | 17 | 22 | 0 | 0 | 22 | 0 | 1753KB | 18371 | 0 |

## pc1440-fail-first-image

| 단계 | 비교 | n | 구성 GET | 사진 200 | 304 | 캐시 | 고유 | 중복 재전송 | 사진 bytes | 첫 사진 ms | 아이콘 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1-first-load-cold | before | 1 | 17 | 34 | 0 | 0 | 46 | 0 | 6645KB | 6661 | 0 |
| 1-first-load-cold | after | 1 | 17 | 34 | 0 | 0 | 46 | 0 | 6645KB | 5926 | 0 |

## 같은 부품 사진의 크기 (detail 원본 vs thumbnail)

부품 12종: detail 200 12종 합 2976KB · thumbnail 200 12종 합 960KB

| 부품 코드 | detail | ms | 304 재검증 ms | thumbnail | ms | 304 재검증 ms |
|---|---|---|---|---|---|---|
| 108887 | 200 125KB | 1281 | 304 168 | 200 51KB | 175 | 304 167 |
| 112789 | 200 285KB | 331 | 304 168 | 200 110KB | 173 | 304 168 |
| 110899 | 200 156KB | 178 | 304 168 | 200 52KB | 171 | 304 167 |
| 113685 | 200 336KB | 194 | 304 168 | 200 97KB | 170 | 304 167 |
| 128778 | 200 141KB | 171 | 304 167 | 200 51KB | 169 | 304 167 |
| 111146 | 200 306KB | 177 | 304 167 | 200 86KB | 171 | 304 167 |
| 121846 | 200 360KB | 185 | 304 167 | 200 91KB | 170 | 304 168 |
| 105195 | 200 249KB | 179 | 304 166 | 200 73KB | 170 | 304 167 |
| 118490 | 200 287KB | 173 | 304 167 | 200 85KB | 175 | 304 167 |
| 129552 | 200 273KB | 180 | 304 166 | 200 49KB | 168 | 304 168 |
| 121492 | 200 231KB | 176 | 304 167 | 200 107KB | 169 | 304 167 |
| 121632 | 200 229KB | 173 | 304 167 | 200 107KB | 172 | 304 167 |
