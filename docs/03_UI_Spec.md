# 03 — UI Specification and Design System

**Product:** ClassVoice  
**Document status:** Baseline v1.0  
**Last updated:** 2026-10-27

## 1. Design principles

1. **Calm studio, not a toy:** academic work should feel focused and trustworthy.
2. **Audio is tangible:** playback, waveform, duration, and processing status are always clear.
3. **Safety is visible:** consent and synthetic provenance are understandable without being alarmist.
4. **Progressive disclosure:** beginners see a small set of controls; advanced controls are expandable.
5. **Keyboard first:** every essential flow works without a pointer.

## 2. Color tokens

All values are exact sRGB hex values. Semantic tokens, not raw colors, must be used in components.

### 2.1 Light theme

| Token | Hex | Usage |
|---|---|---|
| `--color-bg` | `#F8FAFC` | App background |
| `--color-surface` | `#FFFFFF` | Cards, panels |
| `--color-surface-raised` | `#F1F5F9` | Hovered/raised surfaces |
| `--color-border` | `#CBD5E1` | Default borders |
| `--color-border-strong` | `#94A3B8` | Focus/active borders |
| `--color-text` | `#0F172A` | Primary text |
| `--color-text-muted` | `#475569` | Secondary text |
| `--color-text-subtle` | `#64748B` | Helper text |
| `--color-brand-500` | `#4F46E5` | Primary action |
| `--color-brand-600` | `#4338CA` | Primary hover |
| `--color-brand-100` | `#E0E7FF` | Brand tint |
| `--color-accent-500` | `#0D9488` | Audio/progress accent |
| `--color-success-600` | `#15803D` | Success text/icon |
| `--color-success-100` | `#DCFCE7` | Success surface |
| `--color-warning-600` | `#B45309` | Warning text/icon |
| `--color-warning-100` | `#FEF3C7` | Warning surface |
| `--color-danger-600` | `#B91C1C` | Destructive/error text |
| `--color-danger-100` | `#FEE2E2` | Error surface |
| `--color-focus` | `#7C3AED` | 2 px focus ring |

### 2.2 Dark theme

| Token | Hex | Usage |
|---|---|---|
| `--color-bg` | `#0B1120` | App background |
| `--color-surface` | `#111827` | Cards, panels |
| `--color-surface-raised` | `#1F2937` | Hovered/raised surfaces |
| `--color-border` | `#334155` | Default borders |
| `--color-border-strong` | `#64748B` | Focus/active borders |
| `--color-text` | `#F8FAFC` | Primary text |
| `--color-text-muted` | `#CBD5E1` | Secondary text |
| `--color-text-subtle` | `#94A3B8` | Helper text |
| `--color-brand-500` | `#818CF8` | Primary action |
| `--color-brand-600` | `#A5B4FC` | Primary hover/active |
| `--color-brand-100` | `#312E81` | Brand tint |
| `--color-accent-500` | `#2DD4BF` | Audio/progress accent |
| `--color-success-600` | `#4ADE80` | Success text/icon |
| `--color-success-100` | `#14532D` | Success surface |
| `--color-warning-600` | `#FBBF24` | Warning text/icon |
| `--color-warning-100` | `#78350F` | Warning surface |
| `--color-danger-600` | `#F87171` | Destructive/error text |
| `--color-danger-100` | `#7F1D1D` | Error surface |
| `--color-focus` | `#C4B5FD` | 2 px focus ring |

Contrast requirement: text and essential controls must meet WCAG 2.2 AA. If a token pair fails automated contrast checks, use the semantic high-contrast variant rather than changing a single component ad hoc.

## 3. Typography

### 3.1 Font families

- UI and body: `Inter`, fallback `ui-sans-serif, system-ui, sans-serif`.
- Monospace/API/code: `JetBrains Mono`, fallback `ui-monospace, SFMono-Regular, monospace`.
- Load only the weights used: 400, 500, 600, 700.

### 3.2 Type scale

| Token | Size | Line height | Weight | Use |
|---|---:|---:|---:|---|
| `text-xs` | 12 px | 16 px | 500 | Labels, metadata |
| `text-sm` | 14 px | 20 px | 400/500 | Body compact, controls |
| `text-md` | 16 px | 24 px | 400 | Default body |
| `text-lg` | 18 px | 28 px | 500 | Section heading |
| `text-xl` | 20 px | 28 px | 600 | Card heading |
| `text-2xl` | 24 px | 32 px | 600 | Page heading |
| `text-3xl` | 30 px | 36 px | 700 | Hero heading |
| `text-4xl` | 36 px | 40 px | 700 | Marketing-only display |

Use sentence case. Do not use all caps for labels except short status pills.

## 4. Spacing, sizing, and layout

- Base spacing unit: 4 px.
- Allowed spacing tokens: 0, 1 (4), 2 (8), 3 (12), 4 (16), 5 (20), 6 (24), 8 (32), 10 (40), 12 (48), 16 (64), 20 (80).
- Minimum interactive target: 44 × 44 px.
- Input/control height: 40 px default, 48 px comfortable.
- Desktop app shell: 240 px sidebar + fluid content, max content width 1,280 px.
- Mobile breakpoint: 640 px; tablet: 768 px; desktop: 1,024 px; wide: 1,440 px.
- Page padding: 16 px mobile, 24 px tablet, 32 px desktop.
- Grid gap: 16 px default; 24 px for major sections.
- Card padding: 16 px default; 24 px for feature panels.

## 5. Shape, elevation, and motion

- Radius: `sm=6 px`, `md=10 px`, `lg=14 px`, `xl=20 px`, pill=999 px.
- Border: 1 px solid semantic border token.
- Light shadow: `0 1px 2px rgb(15 23 42 / 0.06), 0 8px 24px rgb(15 23 42 / 0.06)`.
- Dark shadow: `0 1px 2px rgb(0 0 0 / 0.35), 0 8px 24px rgb(0 0 0 / 0.2)`.
- Motion durations: fast 120 ms, normal 180 ms, slow 280 ms.
- Easing: `cubic-bezier(0.2, 0.8, 0.2, 1)` for enter; `cubic-bezier(0.4, 0, 1, 1)` for exit.
- Respect `prefers-reduced-motion: reduce`; remove decorative movement and use instant state changes.

## 6. Theme rules

- Default theme follows OS preference; user can choose Light, Dark, or System.
- Theme is set before hydration to avoid flash of incorrect theme.
- Audio waveform uses accent token in both themes and must remain distinguishable from the surface.
- Do not encode status solely through color; use icon + label + optional color.
- Images/illustrations are optional and must not compete with the editor.

## 7. Component contracts and states

### Button

Variants: Primary, Secondary, Ghost, Destructive, Link.  
States: Default, Hover, Focus-visible, Pressed, Disabled, Loading, Success (transient).

- Loading preserves width and shows a spinner plus accessible label.
- Destructive buttons require confirmation for delete/revoke actions.
- Primary button uses brand token; do not use red for ordinary errors.

### Text input / textarea

States: Empty, Filled, Hover, Focus, Invalid, Disabled, Read-only.

- Label is always visible; placeholder is not a label.
- Error text sits below the control and includes a correction.
- Character counter appears at 80% of the configured maximum.
- Textarea supports a visible resize affordance unless layout would break.

### Select / combobox

States: Closed, Open, Focused, Loading options, Empty options, Invalid, Disabled.

- Searchable when more than 8 options.
- Voice options show name, language, status, and owner; revoked voices are not selectable.

### Card / panel

States: Default, Hoverable, Selected, Disabled, Loading skeleton, Error.

- Hover is never the only way to discover clickability.
- Error card includes a request ID in a copyable details disclosure.

### Status badge

Statuses: Draft, Processing, Ready, Rejected, Revoked, Archived, Queued, Failed, Canceled.

Each status has an icon, text label, semantic color, and optional tooltip explaining next action.

### Upload dropzone

States: Idle, Drag-over, Selected, Uploading with percent, Validating, Invalid, Complete, Disabled.

- Must expose a regular `Choose audio` button.
- Shows file name, size, duration when known, cancel, and replace.
- Never echo raw object keys or server paths.

### Audio player

States: Loading, Ready, Playing, Paused, Buffering, Error, Expired URL.

- Controls: play/pause, seek, current/total duration, volume, playback speed, download.
- Keyboard: Space toggles play; arrows seek when focused; all controls have labels.

### Progress / job row

States: Queued, Processing, Cancel requested, Succeeded, Failed, Canceled.

- Show a determinate progress only when backend provides a truthful estimate; otherwise use an indeterminate bar.
- Never imply progress from elapsed time alone.

### Modal / confirmation dialog

States: Opening, Open, Submitting, Success, Error, Closing.

- Destructive dialogs state exact cascade effects and require a typed confirmation for permanent deletion.
- Escape closes only non-destructive dialogs.

### Toast / alert

Variants: Info, Success, Warning, Error.

- Toasts are supplementary; form errors remain inline.
- Error toasts include `Retry` when safe and a request ID details toggle.

## 8. Audio-specific visual rules

- Waveform color: `--color-accent-500`; played portion uses brand token.
- Display duration as `m:ss`; use a long form in screen-reader text.
- Show “AI-generated” provenance label next to every downloadable output.
- Quality warnings appear before generation, not after an unusable file is produced.

## 9. Content and copy rules

- Prefer “voice sample” and “voice profile” over “clone” in user-facing copy.
- Say what happened and what to do next: “Sample is too quiet. Record or upload a clearer sample.”
- Never promise an exact likeness or imply consent can be bypassed.
- Use “Generate audio” rather than “Synthesize” in primary buttons.

## 10. QA checklist

- Keyboard-only pass for auth, voice creation, studio, player, and deletion.
- Light/dark screenshot comparison at 375, 768, 1,024, and 1,440 px widths.
- Automated contrast check for every semantic token pair.
- Screen-reader pass for async job updates and modal focus.
- Reduced-motion pass with no loss of status information.
