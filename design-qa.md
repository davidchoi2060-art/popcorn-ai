# 조립PC 제품군 관리자 화면 QA · 2026-09-29

final result: passed

## 2026-09-29 · 상품 설명 편집 시안 1

Source: `C:/Users/leon2/.codex/generated_images/01a0d6a3-e8fa-7cc1-8897-e6b9fa7e34f0/exec-5c17e547-7ca4-4904-80f5-6110b0ce9d97.png`.
Captures under `C:/Users/leon2/OneDrive/Documents/ChatGPT/팝콘AI/outputs/admin-pc-catalog-mockups-20260929/`: `editor-desktop-final.png` and `editor-mobile.png`.

- Matched P100866, active 상품 설명, two benefits in the unsaved fixture state, 1600×1024 desktop vs source 1568×1003 equivalent ratio. Real catalog has three benefits: deleting the third for visual comparison was only a local in-memory draft, never a DB edit. Registered content is not trimmed to reproduce the illustrative count.
- P2 fixed: initial textarea/counter spacing pushed section navigation below the viewport. Input counters moved inside inputs; benefit textareas use two resizable lines and tighter spacing. Source and latest implementation displayed together again; fields, product rail, section dividers, footer and imagery now match the intended hierarchy.
- P2 fixed: footer updated before tab visibility changed. Observe actual hidden attribute so mouse and keyboard tab changes consistently display the correct actions.
- P2 fixed: native confirm blocked the embedded browser during cancel QA. Replaced with accessible in-page dialog containing 계속 편집 / 변경 취소. Verified that close/cancel protects unsaved inputs and returns to the saved state.
- Desktop and 390×844 mobile inspected. Mobile input scrolls internally and fixed save actions remain accessible. Existing typography, warm surfaces, emerald focus/action, actual supplier case photo and Feather icons retained. Exact legacy copy and longer allowed field limits are deliberate P3 differences.
- Browser: edit, feature add/delete, FAQ add/delete, unsaved preview, save success, saved revision history, cancel/keep editing, close protection and mobile controls verified. No console errors. Write UI used isolated process-memory fixture; real DB write/archive was separately exercised within a rolled-back transaction and rollback confirmed.
- 49 focused unit tests pass (including allowlist, empty/oversized fields, stale revision, no-op, protected fields, archive and actor, retired records, role and cross-site rejection). All 104 existing descriptions validate. Full application history/no-op save routes work through authentication context. No permanent test edits to catalog or new migration.

final result: passed

## Follow-up · panel bottom alignment (2026-09-29)

User reported the right panel ended above the list. On the live 1920×855 viewport the list bottom was 836.67px and inspector bottom 669.98px (166.69px gap). Removed the inspector-only viewport height cap and nested summary scrolling; desktop grid panels now stretch to the same row height, with their content expanding and their footer controls at the bottom. The page scrolls normally when content is taller than the viewport. Local browser inspection at 1280×720 confirmed identical panel bottoms, and the detail button remains reachable by normal page scrolling. This supersedes the independent inspector scrolling described in the original QA history below. Mobile stacked layout rules are unchanged.

## Evidence

- Source visual truth: `C:/Users/leon2/OneDrive/Documents/ChatGPT/팝콘AI/outputs/admin-pc-catalog-mockups-20260929/03-split-v2.png`
- Implementation: same directory `implementation-final.png`; local `/admin2/pc-configurations` with real database, existing admin shell.
- Full comparison: `comparison-final.png` (source and implementation together).
- Focused comparison: `comparison-inspector.png` (P97909 selected in both, actual case photo and saved copy in implementation).
- Desktop viewport / pixels: 1536 × 1024 CSS px / 1536 × 1024 image, no density resampling. Combined image 3072 × 1024. Existing admin CSS text zoom 1.15 preserved.
- Other captures: `implementation-part-detail.png`, `implementation-tablet.png` (768 × 1024), `implementation-mobile.png` (390 × 844).
- State: list with selection and inspector open; full-list screenshot selects first real sorted row N02. The reference uses an illustrative three-row mix and P97909 selection. Inspector comparison separately matches P97909; no fabricated DB rows or sorting were introduced to reproduce the illustrative mix.
- Local preview is a read-only loopback harness. Its shell says login required because it has no production session; server uses the unchanged actual authentication middleware.

## Findings and comparison history

1. P2 resolved — search text wrapped and the first filter option was malformed. Corrected button no-wrap and native option markup. Browser filtering by 신규 gives 15 results; adding information-review required gives an accurate empty result.
2. P2 resolved — long real descriptions and the extra information-review state pushed the detail CTA below the desktop viewport. Compacted hero spacing and made the inspector summary scroll independently; the single footer CTA is now visible at bottom 981.6px at the 1024px viewport. `implementation-before.png` / intermediate `implementation-detail-selection.png` and final full/focused comparisons document the progression.
3. P2 resolved — mobile search consumed space needed by source/review filters, leaving arrow-only controls. Mobile search now has its own row and filter labels have minimum widths. Latest `implementation-mobile.png` shows readable filter captions, no viewport horizontal overflow (document 375px within 390px viewport). Wide table scrolls within its own container.
4. Local-only image credential gap resolved for QA — initial local Google ADC was absent; harness uses the existing public server product-image endpoint. Production image implementation and credentials unchanged. Final captures show actual BOM case images, clearly captioned as case images.

## Required fidelity surfaces

- Typography: existing Pretendard/Noto Sans KR system retained; clear large title, price emphasis, subordinate facts. Real titles wrap naturally. The source's simplified titles were replaced by DB copy intentionally.
- Layout: charcoal 212px sidebar, warm canvas, thin outlined list and inspector, selected pale-green row, single green footer CTA retained. Core proportions approximately 62:38. Shared navigation is denser than the illustrative reference because existing admin routes remain available. Small screens stack the panels and scroll the table horizontally.
- Colors: uses the canonical admin CSS palette; green selection/actions, blue existing-product source, amber information checks, neutral private status. No independent theme or customer tokens introduced.
- Imagery: actual stored case images, aspect ratio preserved with object-fit contain. Generated assembled images are separate ongoing work and not misrepresented here. Reuses packaged icons, no custom art.
- Copy: descriptions already registered are shown as registered. Information changes, final compatibility verification and customer publication are distinct. Price date and assembly-inclusion notes come from saved offers. New registration is explicitly preparing, not a fake active button.

## Interactions and verification

- List / selection / previous-next within page; server pagination 1–3 → 4–6; source and review filter combination; empty-state disabled detail; P97909 search all verified in browser.
- XLSX downloaded through browser to `C:/Users/leon2/Downloads/조립PC_제품군.xlsx`; downloaded data/API workbook checks confirm one P97909 result and price 1,276,600. Browser download-event path wait timed out after the actual file was successfully saved; filesystem verification established completion.
- Detail dialog opens and closes, actual seven-part N02 BOM, CPU expansion includes LGA1700, 4 cores, 8 threads and current individual price 148,900. Existing part explanation renderer reused.
- Console error list empty on final interactions. Python focused unit tests: 35 pass. JS syntax check and git diff whitespace check pass. Authentication gate predicate protects both page and export endpoint.

## Follow-up polish / scope

- P3: packaged icon shapes differ slightly from generated mock icons. Shared admin shell mobile navigation remains the existing implementation.
- New configuration creation/edit/publication and generated assembled-image integration are intentionally subsequent features. No P0/P1/P2 issues remain in this list/detail scope.

## Implementation checklist

- [x] Live DB list, summaries, explanation details and export.
- [x] No DB write or schema migration; existing admin auth retained.
- [x] Visual comparison and responsive corrections.
- [x] Core interactions and error/empty states verified.


## 2026-09-29 · 제품군 상세 내용 출력
- 104개 모두 기존 검토 기록 존재, 부품 코드·수량104/104 일치(읽기 전용 DB 대조).
- 로컬 브라우저 N02: 상품 설명, 호환성15항목(문서상 충족8/조건·추가 확인7), 고객용 설명·알뜰/추천 기준 펼침 확인. JS 오류 없음.
- P100866: SSD P/N·메인보드 리비전의 실제 review_issues 2개와 구성별 확인 사항 출력 확인.
- 단위 테스트40개 통과. BOM 교체/수량 변경 시 과거 기록 표시, 승인 근거로 사용하지 않음, 누락 자료에 판정을 생성하지 않음 검증.
- 기존 데스크톱 좌우 패널 하단 정렬 규칙 유지. 접기/펼치기는 본문 길이에 맞춰 페이지가 늘어나는 방식.

## 2026-09-29 · 전체 구성 보기 2번 시안 및 세 탭

Source directory: `C:/Users/leon2/.codex/generated_images/01a0d6a3-e8fa-7cc1-8897-e6b9fa7e34f0/`.
Parts: `exec-849c495d-2d60-4f37-8f8a-84451309ac2c.png`; copy: `exec-b4f2f1cf-effb-4f9e-9e80-60f1f1d539f0.png`; review: `exec-cfaaa1e8-8db8-4d1b-86c8-7b1b6ed6dba4.png`.

Implementation captures: `C:/Users/leon2/OneDrive/Documents/ChatGPT/팝콘AI/outputs/admin-pc-catalog-mockups-20260929/detail-parts-implemented.png`, `detail-copy-implemented.png`, `detail-review-implemented.png` (1600×1024), `detail-mobile.png` (390×844). Compared source and implementation together. Reference 1568×1003 has the same approximate aspect ratio; existing admin 1.15 text zoom retained.

- P2 resolved: tall part rows hid lower parts. Compacted row spacing and first four specification facts, with additional details expandable. Eight parts fit at desktop height with CPU expanded.
- P2 resolved: previously packaged colored icons and duplicate chevrons differed from the selected visual. Replaced with actual vendored Feather outline icons for navigation and detail controls.
- P2 resolved: modal focus scrolled the background LNB and mobile viewport shifted horizontally. Clip the shell while the dialog is open and lock root overflow. Final mobile dialog left=0, width=390, body width=390, shell scroll=0.
- Fidelity: fixed left product rail, three green-underlined tabs, white/ivory surfaces, thin separators, editorial product copy, actual issue rows and expandable review table. Existing admin typography/palette retained. Product images preserve aspect ratio. Real supplier images, full model names and longer registered copy intentionally replace illustrative content; content scrolls internally without truncating facts.
- Browser checks: tabs and keyboard arrows, part expansion/collapse, all 13 review items, customer preview open/close, parent close, LNB collapse/expand and loaded icons. No JS console errors. Existing saved product total remains distinct from current part prices. No fabricated approval, performance or publication state.
- Validation: 40 focused backend unit tests passed; both JS syntax checks passed. Renderer fixture confirms three tabs/eight parts, saved and individual prices, and escaping of malicious product titles/model names. No DB writes or migration.
- No unresolved P0/P1/P2 findings. P3 illustration differences are deliberate substitutions of real data and real product photography.

final result: passed


## 2026-09-29 · 관리자 부품 편집 결합안

- Source: generated_images/01a0d6a3-e8fa-7cc1-8897-e6b9fa7e34f0/exec-50563adf-74b2-44ec-b48c-05c22ee2751b.png (1672×941). Implementation: outputs/admin-pc-catalog-mockups-20260929/parts-picker-qa.png and parts-confirm-qa.png (1920×1080), parts-mobile-qa.png (390×844), under the task workspace. Source and implementation viewed together; both desktop aspect ratios are 16:9. Existing 1.15 admin zoom retained.
- Preserved: charcoal LNB, ivory surfaces, emerald selected state, left product rail, composition table, right comparison drawer, fixed bottom actions, before/after confirmation. Real photos/model names/specification facts replace reference illustration and fabricated specs. Candidates are paginated above a two-column comparison; filters for unimplemented compatibility approval are not fabricated.
- P2 resolved: admin zoom pushed drawer footer below viewport; divide viewport height by shell zoom. Desktop and mobile bottom actions now visible.
- P2 resolved: nonexistent warning icon replaced with existing vendored help-circle SVG. No new icon system.
- P2 resolved: quantity validation restores the previous valid number instead of silently proceeding with a bad visible value; keyboard tab navigation and customer preview cannot bypass dirty-parts protection.
- Browser: memory change preserved when choosing SSD; 1,054,900 + 28,700 + 29,700 = 1,113,300 shown before saving; save closes dialog; reopening the rollback fixture shows RAM16/SSD512 and review-required copy. Search no-results, invalid quantity with actual keyboard, discard/keep, original/new save options verified. No console JS errors.
- Mobile: dialog left=0,width=390, document scrollWidth=390; table scrolls internally; candidate list stacks and actions remain accessible.
- Backend: 60 focused tests pass. Real-DB transaction tests cover update/new, history preservation, package capacity, unchanged assembly fee, recommendation exclusion and complete rollback. No QA mutations persisted. Four edited JS files pass syntax checks.
- Boundary: candidate sales display is not physical stock/dispatch confirmation; saving is not compatibility/publication approval. No unresolved P0/P1/P2 in this editor scope.

- Deployed verification 2026-09-30: main a7c40df, GitHub run36586903883 success. Authenticated server UI candidate comparison/preview verified; 1,054,900+28,700=1,083,600; canceled without persisting. Final screenshots parts-picker-live.png / parts-confirm-live.png show resolved icons; no console errors.

## 2026-09-30 · 현재 구성 검토와 추천 승인

- Existing approved detail layout retained: left product rail, ivory/charcoal/emerald tokens, three tabs. Current review editor extends the existing review tab; historical snapshot is collapsible rather than represented as current evidence.
- Backend: 74 focused tests. Real DB transaction verifies draft exclusion, approval inclusion, copy edit invalidation, reapproval, revoke and five history snapshots; all writes rolled back and original digest confirmed unchanged.
- Browser: current DB checks, required evidence validation, dirty close/keep, rollback-only approval, reopened approved result, blockers and disabled approval verified. P97909 has eight known rule results; P100866 shows two part explanation blockers. No JS errors during local verification.
- Mobile 390x844: no document horizontal overflow; rule table scrolls internally, review footer follows existing parts editor sticky action pattern. Original admin zoom retained.
- Bounds: rule pass is not physical assembly or dispatch certification. Missing specifications require human evidence, never fabricated pass/FPS. Approval only changes administrative recommendation eligibility; no real product was approved during QA.
