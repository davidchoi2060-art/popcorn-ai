---
name: Vibrant Horizon
colors:
  surface: '#f6f5ff'
  surface-dim: '#c7d3ff'
  surface-bright: '#f6f5ff'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#eef0ff'
  surface-container: '#e3e7ff'
  surface-container-high: '#dbe1ff'
  surface-container-highest: '#d3dcff'
  on-surface: '#212d51'
  on-surface-variant: '#4e5a81'
  inverse-surface: '#000b2e'
  inverse-on-surface: '#909cc6'
  outline: '#6a769e'
  outline-variant: '#a0acd7'
  surface-tint: '#005ab3'
  primary: '#005ab3'
  on-primary: '#eff2ff'
  primary-container: '#64a1ff'
  on-primary-container: '#00224b'
  inverse-primary: '#3e90ff'
  secondary: '#3155b7'
  on-secondary: '#f1f2ff'
  secondary-container: '#c4d0ff'
  on-secondary-container: '#153fa2'
  tertiary: '#853d97'
  on-tertiary: '#ffeefc'
  tertiary-container: '#e795f7'
  on-tertiary-container: '#570a6a'
  error: '#b31b25'
  on-error: '#ffefee'
  error-container: '#fb5151'
  on-error-container: '#570008'
  primary-fixed: '#64a1ff'
  primary-fixed-dim: '#4593ff'
  on-primary-fixed: '#000000'
  on-primary-fixed-variant: '#002b5c'
  secondary-fixed: '#c4d0ff'
  secondary-fixed-dim: '#b1c2ff'
  on-secondary-fixed: '#002c83'
  on-secondary-fixed-variant: '#2349ac'
  tertiary-fixed: '#e795f7'
  tertiary-fixed-dim: '#d888e8'
  on-tertiary-fixed: '#330041'
  on-tertiary-fixed-variant: '#611874'
  primary-dim: '#004e9d'
  secondary-dim: '#2248ab'
  tertiary-dim: '#78308a'
  error-dim: '#9f0519'
  background: '#f6f5ff'
  on-background: '#212d51'
  surface-variant: '#d3dcff'
typography:
  headline-lg:
    fontFamily: Inter
    fontSize: 32px
    fontWeight: '700'
    lineHeight: 40px
  headline-md:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
  body-md:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  label-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '500'
    lineHeight: 20px
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  base: 8px
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 32px
  gutter: 16px
  margin: 24px
---

# Design System: Vibrant Horizon

## Brand & Style
The brand personality has shifted from a warm, earthy, and utility-focused aesthetic to one that is energetic, professional, and tech-forward. By moving from a "fidelity" approach with orange tones to a "vibrant" approach with blue and violet tones, the UI now evokes feelings of innovation, clarity, and digital precision.

The design style is **Corporate / Modern** with a touch of **Minimalism**. It prioritizes high readability and a clean, balanced interface that feels reliable yet modern. The transition to a "vibrant" color palette ensures that key interactions stand out with high energy while maintaining a professional structure.

## Colors
The color palette is anchored by a vibrant blue primary color, signifying trust and technological fluency. The transition from the previous orange-heavy palette to this cool-toned spectrum creates a more calm and focused user experience.

*   **Primary (#0082fd):** A bright, energetic blue used for main actions and brand identifiers.
*   **Secondary (#5071d5):** A muted periwinkle-blue used for supporting elements and tonal variance.
*   **Tertiary (#a459b5):** A soft violet used for accents, highlights, or categorizing distinct features.
*   **Neutral (#6a769e):** A cool-grey blue used for text, borders, and surfaces to maintain harmony with the vibrant palette.

The system uses a `light` color mode by default, emphasizing whitespace and a clean, airy feel.

## Typography
The system has transitioned from Public Sans to **Inter**, a typeface specifically designed for user interfaces. Inter provides superior legibility at small sizes and a modern, neutral tone that complements the vibrant color palette.

The type scale is highly structured:
*   **Headlines:** Use Bold or Semi-Bold weights to create a strong visual hierarchy.
*   **Body Text:** Set in Inter Regular for maximum readability across long-form content.
*   **Labels:** Use Medium weights to differentiate metadata and small UI controls from body text.

For mobile devices, larger headlines scale down slightly to ensure they fit within narrower viewports without excessive line breaks.

## Layout & Spacing
The layout follows a **Fluid Grid** philosophy with a consistent 8px spatial rhythm. This ensures that all components and containers align perfectly across different screen sizes.

*   **Grid:** A 12-column grid is used for desktop, collapsing to 4 columns for mobile.
*   **Gutters & Margins:** Standard 16px gutters keep elements separated, while 24px outer margins provide breathable space at the edges of the viewport.
*   **Rhythm:** All vertical and horizontal padding should be multiples of 4px or 8px to maintain a cohesive visual structure.

## Elevation & Depth
The system utilizes **Tonal Layers** and **Ambient Shadows** to convey depth. Unlike the previous flat, sharp-edged design, this iteration uses soft, diffused shadows to lift interactive elements like cards and buttons.

Backgrounds use very subtle tints of the neutral blue (#6a769e) to create tiered surfaces (e.g., a slightly darker background for the main canvas and pure white for foreground cards).

## Shapes
The shape language has evolved from sharp 0px corners to a **Rounded** aesthetic. This softening of the UI makes the interface feel more approachable and modern.

*   **Standard Elements:** Buttons, inputs, and chips use a 0.5rem (8px) corner radius.
*   **Containers:** Large cards and modals use a `rounded-lg` 1rem (16px) or `rounded-xl` 1.5rem (24px) radius to create a distinct container hierarchy.

## Components
*   **Buttons:** Feature 8px rounded corners. Primary buttons use the vibrant blue (#0082fd) with white text.
*   **Inputs:** Use the neutral blue for borders with a 2px focus ring in the primary color.
*   **Cards:** Elevated with soft ambient shadows and 16px rounded corners.
*   **Chips:** Highly rounded (pill-shaped) to distinguish them from buttons, utilizing secondary or tertiary light tints for background fills.
*   **Lists:** Clean separation using subtle neutral-tinted dividers.