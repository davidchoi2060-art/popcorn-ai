---
name: Advise & Build
colors:
  surface: '#f7f9fb'
  surface-dim: '#d8dadc'
  surface-bright: '#f7f9fb'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f2f4f6'
  surface-container: '#eceef0'
  surface-container-high: '#e6e8ea'
  surface-container-highest: '#e0e3e5'
  on-surface: '#191c1e'
  on-surface-variant: '#45464d'
  inverse-surface: '#2d3133'
  inverse-on-surface: '#eff1f3'
  outline: '#76777d'
  outline-variant: '#c6c6cd'
  surface-tint: '#565e74'
  primary: '#000000'
  on-primary: '#ffffff'
  primary-container: '#131b2e'
  on-primary-container: '#7c839b'
  inverse-primary: '#bec6e0'
  secondary: '#505f76'
  on-secondary: '#ffffff'
  secondary-container: '#d0e1fb'
  on-secondary-container: '#54647a'
  tertiary: '#000000'
  on-tertiary: '#ffffff'
  tertiary-container: '#002113'
  on-tertiary-container: '#009668'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#dae2fd'
  primary-fixed-dim: '#bec6e0'
  on-primary-fixed: '#131b2e'
  on-primary-fixed-variant: '#3f465c'
  secondary-fixed: '#d3e4fe'
  secondary-fixed-dim: '#b7c8e1'
  on-secondary-fixed: '#0b1c30'
  on-secondary-fixed-variant: '#38485d'
  tertiary-fixed: '#6ffbbe'
  tertiary-fixed-dim: '#4edea3'
  on-tertiary-fixed: '#002113'
  on-tertiary-fixed-variant: '#005236'
  background: '#f7f9fb'
  on-background: '#191c1e'
  surface-variant: '#e0e3e5'
typography:
  headline-lg:
    fontFamily: Geist
    fontSize: 32px
    fontWeight: '600'
    lineHeight: 40px
    letterSpacing: -0.02em
  headline-lg-mobile:
    fontFamily: Geist
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.01em
  headline-md:
    fontFamily: Geist
    fontSize: 20px
    fontWeight: '500'
    lineHeight: 28px
  body-lg:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  body-sm:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  label-caps:
    fontFamily: Geist
    fontSize: 12px
    fontWeight: '600'
    lineHeight: 16px
    letterSpacing: 0.05em
  mono-spec:
    fontFamily: Geist
    fontSize: 13px
    fontWeight: '500'
    lineHeight: 18px
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  container-max: 1280px
  gutter: 24px
  margin-desktop: 40px
  margin-mobile: 16px
  stack-gap: 12px
  section-gap: 48px
---

## Brand & Style

The design system is rooted in the persona of a **Reliable Advisor**. It moves away from the typical "black-box AI" aesthetic—no glowing orbs, complex code snippets, or mysterious gradients. Instead, it embraces a **Modern Professional** style that prioritizes transparency, clarity, and data integrity. 

The emotional response should be one of confidence and calm. We achieve this through a minimalist, card-based interface that feels structured and intentional. The "Adaptive Flow" philosophy ensures that the user is never overwhelmed by technical specifications; instead, data is revealed through purposeful filtering and "set-based" visualizations that show the logic behind every recommendation.

## Colors

The palette is anchored in trust and clarity.
- **Primary (Deep Navy):** Used for typography, navigation, and structural elements to establish authority.
- **Secondary (Slate Gray):** Utilized for metadata, borders, and secondary descriptions, providing a professional, balanced backdrop.
- **Tertiary (Emerald Green):** A functional highlight color reserved exclusively for "In-Stock" indicators, "Verified" badges, and "Expert Recommendation" callouts.
- **Neutral (Off-White/Slate):** Used for the background and surface areas to keep the interface feeling light and accessible.

The interface maintains a high-contrast ratio to ensure technical specs are effortlessly readable.

## Typography

This design system uses a dual-font approach to balance technical precision with approachability. 

**Geist** is used for headlines, labels, and technical specifications. Its geometric nature reflects the "data-driven" persona and ensures that part numbers and performance metrics are legible. **Inter** is used for all body copy and narrative descriptions, providing a humanist touch that feels like a conversation with a human expert.

Hierarchy is strictly enforced: bold labels for "Fact-based Reason" headers, and a dedicated `mono-spec` style for technical attributes (RAM, Clock Speed, TDP) to give them a distinct, structured look without resorting to "code-block" styling.

## Layout & Spacing

The layout utilizes a **Fixed Grid** on desktop to maintain a centered, authoritative "Adaptive Flow." 

1.  **Central Flow:** The main input and "Reasoning" reports occupy the central column (8 columns wide).
2.  **Candidate Pool (Sidebar):** A persistent 4-column sidebar on the right visualizes the filtering process. As users adjust preferences, items move in or out of this pool with smooth, non-linear transitions.
3.  **Adaptive Transitions:** On mobile, the Sidebar collapses into a bottom-sheet "Drawer" that can be pulled up to view the current candidate list.

Spacing follows an 8px base unit. Internal card padding is generous (24px) to prevent data density from feeling cluttered.

## Elevation & Depth

To emphasize the "Advisor" persona, the design uses **Tonal Layers** combined with **Ambient Shadows**.

- **Level 0 (Background):** Slate-50 (#F8FAFC).
- **Level 1 (Main Cards):** Pure White with a soft, 15% opacity Slate-200 shadow. This is the primary surface for the adaptive flow components.
- **Level 2 (Active/Selected):** 1px Slate-200 border with a slightly deeper shadow (25% opacity) to indicate focus or a "Recommended" part.

Avoid heavy blurs or frosted glass. The depth should feel physical and grounded, like paper reports neatly organized on a professional desk.

## Shapes

The design system uses a **Rounded** shape language (8px / 0.5rem base) to soften the technical nature of PC hardware. 

- **Primary Cards:** 16px (rounded-lg) for a substantial, modern feel.
- **Inputs & Buttons:** 8px (base roundedness) to maintain a professional, sturdy appearance.
- **Status Pills:** Fully pill-shaped (rounded-full) to distinguish them from interactive buttons.

## Components

### Buttons
- **Primary:** Deep Navy background, White text. High-contrast, no gradient.
- **Secondary:** White background, 1px Slate border, Deep Navy text.
- **Actionable Icons:** Minimalist 20px icons with 40px hit states.

### Spec Cards
Each hardware component card must feature a "Reasoning Indicator"—a small Emerald highlight that links the part's spec to the user's specific requirement (e.g., "Supports 4K Editing").

### Adaptive Filtering Sidebar
A vertical list of "Candidate" cards. Use micro-animations to show items being "Filtered Out" (fading and sliding right) as criteria are narrowed.

### Fact-based Reason Reports
A specialized component for the advisor's logic. Use a light Slate-100 background with a left-hand Emerald border. It should look like an authoritative summary, using `label-caps` for the "FACT" header.

### Input Fields
Large, clean input areas with 16px padding. Replace "AI Prompts" with structured "Attribute Selectors" (e.g., a multi-select chip group for "Workload Type" or "Budget Range").