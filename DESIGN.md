---
name: Amdlxd
description: Apple Music Downloader Web Interface
colors:
  primary: "#ff375f"
  primary-hover: "#ff5277"
  primary-glow: "rgba(255, 55, 95, 0.25)"
  canvas-base: "#1a1a1e"
  surface-secondary: "#242428"
  surface-tertiary: "#2e2e34"
  surface-card: "#28282e"
  surface-input: "#2a2a30"
  surface-hover: "#34343c"
  text-primary: "#f5f5f7"
  text-secondary: "#a1a1a6"
  text-muted: "#9a9aa0"
  text-placeholder: "#8e8e93"
  status-success: "#30d158"
  status-warning: "#ffd60a"
  status-error: "#ff453a"
  border-subtle: "rgba(255, 255, 255, 0.08)"
  border-focus: "rgba(255, 55, 95, 0.5)"
typography:
  display:
    fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, sans-serif"
    fontSize: "2.5rem"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.02em"
  headline:
    fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, sans-serif"
    fontSize: "1.15rem"
    fontWeight: 700
    lineHeight: 1.3
  title:
    fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, sans-serif"
    fontSize: "1.1rem"
    fontWeight: 600
    lineHeight: 1.4
  body:
    fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, sans-serif"
    fontSize: "0.95rem"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, sans-serif"
    fontSize: "0.8rem"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "0.06em"
rounded:
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "20px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
  xl: "32px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.md}"
    padding: "0 28px"
    height: "42px"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
  button-secondary:
    backgroundColor: "{colors.surface-tertiary}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.sm}"
    padding: "0 20px"
    height: "44px"
  input-text:
    backgroundColor: "{colors.surface-input}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.md}"
    padding: "0 18px"
    height: "42px"
  card-preview:
    backgroundColor: "{colors.surface-card}"
    rounded: "{rounded.lg}"
    padding: "20px"
---

# Design System: Amdlxd

## Overview

**Creative North Star: "The Cupertino Studio Vault"**

Amdlxd is constructed as a precision nocturnal studio environment designed for audiophiles and music collectors. Set against an obsidian zinc canvas (`#1a1a1e`), interface elements sit in quiet, layered hierarchy, allowing vibrant cover artwork and media metadata to command visual priority. Rather than relying on loud marketing gradients or heavy ornamentation, the system channels Apple's industrial restraint: razor-thin ghost borders, deep surface contrast, and tactile physical feedback.

The interface centers on focused single-action workflows: pasting an Apple Music URL, inspecting rich track/album intelligence, and initiating high-fidelity downloads. Accent luminescence is strictly rationed: Electric Apple Raspberry (`#ff375f`) is preserved as a precious signal color, ignited only when user intent or active progress demands immediate focus.

**Key Characteristics:**
- **Obsidian Zinc Canvas**: Deep `#1a1a1e` base canvas with stepped tonal altitudes for cards, controls, and dialogs.
- **Electric Raspberry Signaling**: High-chroma `#ff375f` reserved exclusively for primary actions, active playback cues, and progress indicators.
- **Hairline Ghost Framing**: Subtle `rgba(255, 255, 255, 0.08)` borders that carve structure without competing for contrast.
- **Tactile Micro-Physics**: Snappy 150ms transitions paired with physical button compression (`scale(0.92)` to `scale(0.97)`) on interaction.

## Colors

The palette balances dark neutral zinc surfaces with rare, high-chroma Apple Music raspberry accents and clear status luminescence.

### Primary
- **Electric Apple Raspberry** (#ff375f): The primary brand accent and action color. Employed exclusively for call-to-action buttons, active track titles, focus rings, and live progress bars.
- **Electric Raspberry Hover** (#ff5277): Hover state for primary buttons and text links, providing responsive brightening.
- **Electric Raspberry Glow** (rgba(255, 55, 95, 0.25)): Soft ambient bloom accompanying active focus borders and hover halos.

### Neutral
- **Obsidian Base Canvas** (#1a1a1e): The root background across desktop and mobile viewports.
- **Secondary Zinc** (#242428): Surface background for nested containers, progress bar tracks, and header icon buttons.
- **Elevated Card Surface** (#28282e): Background for preview cards, toast notifications, and modal surfaces.
- **Tertiary Surface** (#2e2e34): Background for secondary buttons, modal close controls, and auth cards.
- **Input Fill** (#2a2a30): Specialized interior fill for URL inputs and configuration text fields.
- **Hover Surface** (#34343c): Interactive hover background for cards and secondary icon buttons.
- **Primary Text** (#f5f5f7): High-contrast pure white-zinc for headlines, active track names, and prominent labels.
- **Secondary Text** (#a1a1a6): Apple standard mid-tone gray for subtitles, secondary metadata, and inactive icons.
- **Muted Text** (#6e6e73): Low-prominence gray for genres, duration timestamps, and explanatory captions.
- **Placeholder Text** (#555560): Subdued gray for unfilled input states.
- **Hairline Ghost Border** (rgba(255, 255, 255, 0.08)): Universal 1px structural separator across cards, inputs, and modals.

### Status Luminescence
- **Success Green** (#30d158 / rgba(48, 209, 88, 0.12)): Connected session status, completed track checkmarks, and success toasts.
- **Warning Amber** (#ffd60a / rgba(255, 214, 10, 0.12)): Degraded auth state, account refresh alerts, and warnings.
- **Error Red** (#ff453a / rgba(255, 69, 58, 0.12)): Disconnected status, failed downloads, and invalid URL alerts.

### Named Rules
**The Rarity Rule.** Electric Apple Raspberry (`#ff375f`) is used on ≤10% of any given screen. Its scarcity is the point: when it appears, the eye knows instantly where execution happens.

**The Ghost Border Rule.** Surfaces are never divided with heavy solid lines or opaque gray strokes. Boundaries are always hairline ghost borders at `rgba(255, 255, 255, 0.08)`, preserving the illusion of seamless dark glass.

## Typography

**Display Font:** Inter (with -apple-system, BlinkMacSystemFont, sans-serif)
**Body Font:** Inter (with -apple-system, BlinkMacSystemFont, sans-serif)
**Label/Mono Font:** Inter (with -apple-system, BlinkMacSystemFont, sans-serif)

**Character:** Clean, geometric neo-grotesque typography mirroring Apple's San Francisco aesthetic, delivering immaculate legibility at both tiny track metadata sizes (11px-12px) and grand display scales.

### Hierarchy
- **Display** (700 weight, 2.5rem / 40px, line-height 1.2, letter-spacing -0.02em): App title hero headline featuring a continuous metallic shimmer animation.
- **Headline** (700 weight, 1.15rem / 18.4px, line-height 1.3): Track and album titles inside preview cards; clamped to 2 lines.
- **Title** (600 weight, 1.1rem / 17.6px, line-height 1.4): Modal dialog headers and major section dividers.
- **Body** (400 weight, 0.95rem / 15.2px, line-height 1.5): Standard prose, subtitle descriptions, and URL input text.
- **Label** (600 weight, 0.8rem / 12.8px, line-height 1.2, letter-spacing 0.06em, uppercase): Settings category headers, explicit badge markers, and status labels.

### Named Rules
**The Contrast Guarantee Rule.** All text sitting on obsidian or zinc surfaces must strictly maintain WCAG AA contrast ratios (minimum 4.5:1 for body text, 3:1 for large display titles). Subdued labels never drop below `#a1a1a6` when interactive.

## Layout

Amdlxd operates on a centered single-column layout with a fixed maximum width of `600px` (`.app`), engineered to provide an intimate, focused desktop experience while flowing seamlessly into full-width mobile viewports.

- **Vertical Cadence**: Spaced in harmonious 4px/8px increments (4px, 8px, 12px, 16px, 20px, 24px, 30px, 40px).
- **Responsive Adaptations**:
  - Desktop (>480px): The URL input (`42px` height) and "Preview" action button (`42px` height) sit side-by-side in a horizontal row.
  - Mobile (≤480px): The layout shifts to a vertical ergonomic stack with generous thumb touch targets: URL input expands to `60px` height and the download button expands to `56px` height.
- **Dialog Geometry**: Modals cap at `520px` width (or `400px` for small alerts) with `max-height: 85dvh`, featuring scrollable bodies and sticky headers/footers.

## Elevation & Depth

Surfaces achieve spatial separation through stepped tonal altitudes rather than heavy drop shadows. As components rise in hierarchy or receive interaction, their background lightness steps upward: `#1a1a1e` (canvas) → `#242428` (controls) → `#28282e` (cards) → `#34343c` (hover).

### Shadow Vocabulary
- **Subtle Elevation** (`box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2)`): Used on chips, tags, and small utility badges.
- **Card Depth** (`box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3)`): Used on album artwork tiles, preview cards, and toast notifications.
- **Modal Float** (`box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4)`): Used on centered modal overlays to decouple dialogs from the frosted background.
- **Raspberry Bloom** (`box-shadow: 0 0 20px rgba(255, 55, 95, 0.25)`): Applied to primary buttons on hover and active input focus rings.

### Named Rules
**The Tonal Altitude Rule.** Surfaces rise toward light. Base canvas is always darkest (`#1a1a1e`), containers are elevated (`#28282e`), and interactive hovers brighten (`#34343c`). Shadows only accentuate this tonal separation, never replace it.

## Shapes

The form language uses smooth, continuous curves that grow in radius proportionally with the component's footprint.

- **Small Controls (8px radius):** Text inputs, secondary buttons, restart buttons, and status cards.
- **Medium Actions (12px radius):** Primary URL input, download action buttons, and toast messages.
- **Large Containers (16px radius):** Preview cards, mobile modal corners, and media wrappers.
- **Modals (20px radius):** Floating desktop modal containers.
- **Full Circles (50% radius):** Modal close icons, status traffic-light dots, and avatar badges.

### Named Rules
**The Proportional Curve Rule.** The corner radius scales with container area. Tight buttons never wear 20px pill radiuses, and massive dialog cards never wear sharp 4px corners.

## Components

### Buttons
- **Primary Button:**
  - Shape: Rounded rectangle (12px radius on desktop, 12px on mobile).
  - Background: Gradient `linear-gradient(135deg, #ff375f 0%, #ff6482 100%)`.
  - Dimensions: Height `42px` (`56px` mobile), padding `0 28px`.
  - States: Hover lifts `translateY(-1px)` with bloom shadow; Active compresses `scale(0.97)`.
- **Secondary Button:**
  - Shape: Rounded rectangle (8px radius).
  - Background: Solid zinc (`#2e2e34`), border `1px solid rgba(255, 255, 255, 0.08)`.
  - Dimensions: Height `44px`, padding `0 20px`.
  - States: Hover shifts to `#34343c`; Active compresses `scale(0.97)`.
- **Icon Button:**
  - Shape: Rounded square (8px radius) or circular.
  - Dimensions: `44px × 44px`.
  - States: Hover shifts background to `#34343c`; Active compresses `scale(0.92)`.

### Inputs / Fields
- **URL Input Field:**
  - Shape: Rounded rectangle (12px radius), height `42px` (`60px` mobile), padding `0 42px 0 18px`.
  - Background: Deep input zinc (`#2a2a30`) with hairline border (`rgba(255, 255, 255, 0.08)`).
  - States: Focus shifts border to `rgba(255, 55, 95, 0.5)` with `box-shadow: 0 0 0 3px rgba(255, 55, 95, 0.25)`.
- **Select Dropdown:**
  - Shape: Rounded rectangle (8px radius), height `44px`, padding `0 14px`, custom Apple chevron icon.

### Cards & Media Containers
- **Preview Card:**
  - Shape: Rounded rectangle (16px radius), background `#28282e`, border `1px solid rgba(255, 255, 255, 0.08)`.
  - Header: Dynamic 180° vertical gradient overlay seeded by artwork dominant tones.
  - Media: Square artwork tile (`130px × 130px`, radius 12px) with quick-action hover buttons.
- **Traffic Light Auth Badge:**
  - Signature 3-dot status cluster (`10px` circles: red, yellow, green) with active-state glow pulses and floating backdrop-blurred tooltip.

### Signature Component: Apple Event Splash Screen
- Fullscreen pure black overlay (`#000`) hosting a rotating 500px conic mesh-gradient aura (`#FA4D9C` to `#00E5FF`), 6 concentric ribbon svg layers, and gradient outline Apple logo transitioning out with `scale(1.08)` and `opacity: 0`.

## Do's and Don'ts

### Do:
- **Do** maintain the `#1a1a1e` obsidian background as the bedrock canvas of the application.
- **Do** preserve the hairline ghost border pattern (`rgba(255, 255, 255, 0.08)`) on all elevated cards and inputs.
- **Do** limit Electric Apple Raspberry (`#ff375f`) to primary call-to-actions, focus states, and active progress fills.
- **Do** apply tactile micro-compression (`scale(0.92)` to `scale(0.97)`) on button press for immediate physical feedback.
- **Do** adapt inputs to full-width generous touch targets (56px-60px height) on mobile viewports (≤480px).

### Don't:
- **Don't** use opaque high-contrast gray borders (e.g. `#555` or `#777`) that slice up dark surfaces into harsh boxes.
- **Don't** introduce generic corporate blue, purple, or green accents for brand identity; color belongs to music artwork.
- **Don't** clutter the single-column focused workflow with multi-column sidebars, banner widgets, or promotional badges.
- **Don't** sacrifice WCAG AA text contrast on dark backgrounds; never set body or secondary text below `#a1a1a6`.
- **Don't** strip away tactile active press states or transition timings on interactive buttons.
