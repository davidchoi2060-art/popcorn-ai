# MVP3 welcome and final assets

These assets are local to the customer MVP3 demo. Shared/admin assets are unchanged.

- `welcome-pc.png`: individual raster illustration generated with the built-in ImageGen tool from the approved welcome screenshot, 2026-10-03. Transparent PNG, pale mint three-fan tower, glass side, ground shadow, and three short accent rays on each side. Displayed in the welcome illustration slot; no UI text is embedded.
- `popcorn-mark.png`: individual transparent raster brand mark recreated with built-in ImageGen from the top-left symbol in that same reference. Used in the header and assistant avatars, with a CSS color filter for the white avatar variant.
- Existing `pc.png`, `gpu.png`, `ssd.png` were retained without changes.

Reference: `original-review-assets/a85d7409-cf8f-48bd-8084-2df77798bda2.png` in the customer UI workroom outputs. The screenshot is not rendered as a page background or UI substitute.

## Generation prompts

Welcome illustration: Reproduce only the reference region x855–1095, y342–522 from the 1487×1058 welcome design: centered three-quarter PC tower with pale mint three front fans, a glass side with faint components, thin gray-green outlines, a subtle floor shadow, and six short rays. Keep the flat pale watercolor/vector-like style, no lettering, no full interface, transparent square output. The visible drawing is fitted to a 290×190 desktop slot without stretching its aspect ratio.

Brand mark: Extract and faithfully recreate only the small PopcornAI symbol at x41–79, y22–56. Preserve the organic popped-corn silhouette, rounded dark forest-green outline, three rounded lobes, transparent background, and no text or shadows. Center one isolated mark with a small margin. It is rendered at header/avatar scale.

## UI icons

`icons/*.svg` are the regular Phosphor Icons assets, plus fill variants for the send arrow and unsaved warning. Source: https://github.com/phosphor-icons/core, downloaded 2026-10-03 from `assets/regular/` and `assets/fill/`. Selected for the reference's rounded line style and specific hardware symbols. Their MIT license is retained at `icons/LICENSE`. Icon path geometry is unmodified; colors and dimensions are applied through the consuming CSS. No icon library runtime or CDN is required.
