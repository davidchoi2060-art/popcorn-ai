# Customer home/list implementation QA — 2026-10-17

Approved reference: `2026-10-16-첫화면-새로구성된PC-v1`, selected option 3 and its Claude handoff. Existing MVP3 workflow and brand styles were retained.

Result: the implemented photo-absent home/list layout passed the bounded fixture checks below. This is not production acceptance or a claim of full photographic fidelity.

## Reference and capture evidence

Evidence root: `D:/WORK/코덱스-검수/2026-10-16-고객단-임시개발-v1/화면`.

| Surface | CSS viewport | Capture pixels | Evidence |
| --- | --- | --- | --- |
| Desktop home | 1440 × 1024 | 1440 × 1024 | PC1440-첫화면-v1.png |
| Mobile home | 390 × 844 | 375 × 812 | M390-첫화면-v1.png |
| Narrow mobile home | 360 × 800 | 345 × 767 | M360-첫화면-v2.png |
| Desktop list | 1440 × 1024 | 1440 × 1024 | PC1440-전체목록-v1.png |
| Narrow mobile list | 360 × 800 | 345 × 767 | M360-전체목록-v1.png |

Mobile capture dimensions and CSS viewport differ in this browser. They are recorded separately, not interpreted as CSS widths. Captures are viewport captures, not full-page fixed-bar evidence. `PC1440-비교.png` and `M390-비교.png` place the approved and implemented captures side by side; both were visually inspected.

## Fidelity and behavior

- Layout: desktop home shows two cards plus a full-width third card; mobile puts product content before the collapsed consultation area. The list uses two desktop columns and one mobile column. No horizontal overflow was observed.
- Type and color: existing MVP3 typography, green brand color, card treatment and controls were reused. Product data remains readable at the checked widths.
- Hierarchy and content: the home shows at most three real entries; all seven fixture entries remain reachable in the list. CPU/GPU/RAM/SSD names and quantities come from the response. Unknown price reads `금액 확인 중`; zero is not converted to unknown.
- Assets: the public customer API has no verified product-photo mapping. The handoff explicitly permits omitting images and forbids generated product photos. The implementation therefore omits the image region; photographic matching remains unverified.
- Interaction: existing consultation DOM and inquiry form were preserved. Async cards and desktop/mobile resizing preserve draft text, selection and focus. Empty or failed home loading keeps consultation available. The failed list shows retry; retry re-fetches and leaves the control usable on another failure.

Intentional differences from the prototype: no synthetic product photographs; the existing consultation navigation/copy remains. These preserve the handoff constraints and working customer flow.

## Verification and limits

Read-only local fixture preview: `http://127.0.0.1:8891/mvp3/`. No upstream API is called; mutations are rejected. Home 0/1/2/7 entries, list 7 entries, empty/failure/retry, viewport transitions and draft preservation were checked. Browser console error entries were empty after the checked retry. `홈-상태검사.json` and `모바일-초안보존.json` preserve the observations.

Final MVP3 tests: **291 passed, 0 failed**, sequential file execution. An earlier parallel run had one render-timeout failure and is retained diagnostically; the final sequential run covered all files. The actual welcome-loader-to-consultation-request integration checks only the three displayed configuration IDs and their order.

Not run: production rendering, real customer contact entry, quote saving, HO/PI creation, orders/payments, actual consultation receipt, real LLM/provider calls, database migration, deployment. Previous PR288 UI evidence gaps remain separate and unresolved by this preview. No new actionable layout defect was found in the bounded fixture states above.
