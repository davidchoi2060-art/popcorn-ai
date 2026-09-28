# RAM sales-bundle correction — 2026-09-28

Product 127555 is sold as `ESSENCORE KLEVV DDR5-5600 CL46 32GB [16G x 2]`.
The authenticated merchant admin page still carries a 16GB single-module text
in its spec/model fields. The explicit sales title gives the total and contents
of the bundle: 32GB = two 16GB modules. This is not an unresolved 16/32GB variant.

All 25 affected BOMs order exactly one such bundle. Their total RAM is 32GB.
Do not multiply the already-totalled 32GB by the two modules again.

Applied to the shared PopcornAI DB, with row preimages saved before mutation:

- `product_specs`: capacity_gb=32, mem_type=DDR5, clock_mhz=5600, field provenance.
- `products.locked_fields`: protect those three corrected fields from reimport.
- `product_explanations`: bundle metadata, total/module facts, useful FAQ; remove
  only the resolved capacity-conflict issue. Preserve images, prices, raw merchant
  text, source snapshot/fingerprint and customer publication status.
- Resolve the three corresponding missing-spec review rows.

The merchant source store itself was not edited. Historical migration seeds and
raw import evidence are preserved. Rebuild tools now derive facts from an explicit,
arithmetically consistent bundle title. Both catalog extraction entry points use
the same `api.ram_bundle.ram_bundle` function.

Validation: 7 focused unit tests passed; all 25 explanations regenerated to 32GB;
catalog capacity-conflict count is now zero; browser shows 16GB × 2 and 32GB total.
Local code changes have not been pushed/deployed. DB correction is already applied.

Local audit artifacts: workspace `outputs/ram-bundle-fix-20260928/`, including
`admin-evidence.json`, `db-before.json`, `db-after.json`, and the applied script.
Customer preview: `http://127.0.0.1:8766/pc-catalog/#P121265`.
