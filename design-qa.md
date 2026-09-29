# 조립PC 제품군 관리자 화면 QA · 2026-09-29

final result: passed

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
