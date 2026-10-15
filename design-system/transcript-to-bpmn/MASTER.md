# Transcript to BPMN: design system (MASTER)

Global source of truth for the web app (`web/`). Page-specific overrides go in `pages/<page>.md`.
Every decision below was chosen by the product owner from researched options, not defaulted;
the source of each is noted so it can be revisited deliberately.

## Direction: Process dossier

The product's output is process documentation, so the UI reads like a consulting deliverable or
SOP binder: paper, ink, a reviewer's red pen. Calm and editorial, never "dashboard SaaS".

- Style basis: **E-Ink / Paper** (ui-ux-pro-max style DB: off-white #FDFBF7, ink #1A1A1A).
- Users: **both, analyst-first**. Power and density where analysts work (tables, editor);
  review and export always obvious for occasional reviewers.
- Theme: **light only** (DB guidance for the product type: avoid dark by default; diagrams and
  exports are light). No dark mode, no theme switcher.

## Colour (all contrast measured against paper #FDFBF7)

| Token | Value | Use | Contrast |
|---|---|---|---|
| `--paper` (background) | `#FDFBF7` | page | |
| `--sheet` (card) | `#FFFFFF` | sheets/cards on paper (set apart by hairline, not shadow) | |
| `--paper-shade` (muted) | `#F4F0E8` | hover, selected rows, inset areas | ink 15.3:1 |
| `--ink` (foreground) | `#1A1A1A` | text, diagram strokes | 16.8:1 |
| `--graphite` (muted-foreground) | `#5C5A55` | secondary text, labels | 6.7:1 |
| `--oxblood` (primary/accent) | `#8B2E2A` | **only** disagreements, the primary action, focus ring, destructive outline | 8.1:1 (paper text on it 8.3:1) |
| `--oxblood-tint` | `#F6E9E6` | disagreement highlight background | oxblood on it 7.0:1 |
| `--hairline` | `#E4DED3` | decorative rules, sheet borders | decorative |
| `--rule` | `#CFC8BB` | stronger decorative rules (section dividers) | decorative |
| `--control` | `#8C867B` | form-control borders (meaningful boundary) | 3.5:1 (≥3:1) |

Rules
- Oxblood is scarce on purpose: if everything is red, nothing is. Never use it for decoration.
- **Statuses are monochrome + glyphs** (Lucide SVG, never emoji): done = check, processing =
  half-filled circle (Contrast icon) + "Processing…", failed = X, not processed = empty circle.
  Text always accompanies the glyph (colour/shape never the only signal).
- Destructive actions: oxblood outline + confirmation step (type-to-confirm for projects).

## Typography

Pairing **"Legal Professional"** (ui-ux-pro-max typography DB: formal documents, contracts):

- Headings / titles / wordmark / quotes: **EB Garamond** (500–600; italic for quoted speech).
- Body / UI / tables: **Lato** (400, 700; italic 400).
- Self-hosted via @fontsource (CSP: `font-src 'self'`), `font-display: swap`.
- Key material that must be character-exact (API keys) uses the system monospace stack.

Scale (px): 12 · 13 · 14 · 16 · 20 · 28 · 40. Body 14–16 / line-height 1.5; headings 1.15–1.25.

Details ("full dossier", owner's choice)
- Section labels in **small caps** (`font-variant-caps: all-small-caps`, tracking +0.06em, graphite).
- **Hairline rules** under page titles and between sections; no drop shadows anywhere.
- Disagreements numbered with **lower-case roman numerals** (i., ii., iii.); the same numeral
  marks the disputed step on the diagram.
- Meetings listed with a **pilcrow ¶**.
- Source quotes shown **footnote-style**: italic serif quote, small-caps attribution
  (speaker · timestamp · meeting).
- Page headers carry a **revision line**: "Two meetings · revised 14 Oct 2026 · v12".
- Data columns use **tabular figures** (`font-variant-numeric: tabular-nums`).
- Prose is capped at **~68ch** per line.

## Layout & density

- **Top-bar masthead** (owner's choice): wordmark left, Projects / Settings in small caps,
  account right; a hairline beneath. No sidebar.
- **Compact tables inside airy pages** (owner's choice): generous page margins and headings;
  tables with 36–40px rows for scanning.
- Page width: 1120px for document pages; the editor uses the full width.
- Corner radius: 2–4px (paper, not pills).

## Motion: minimal

- Only colour/opacity transitions, **150ms** (enter) / **100ms** (exit), ease-out on enter.
- Dialogs and menus fade; no zoom, no bounce, no decorative movement. The sheet (version
  history) may slide because it shows where it came from.
- `prefers-reduced-motion: reduce` → all transitions off.

## The diagram ("themed to match")

- bpmn-js renders on paper with ink strokes and EB Garamond labels; white sheet fill for tasks.
- Steps involved in an open disagreement get an oxblood outline and the disagreement's numeral.
- **Exports stay standard BPMN** (server-side renderer is untouched).

## Accessibility (pre-delivery, from ui-ux-pro-max quick reference)

- Text ≥4.5:1, meaningful non-text ≥3:1 (values above are measured).
- Visible focus: 2px oxblood ring with 2px offset on every interactive element.
- Pointer targets ≥24×24 CSS px (buttons 36px tall); icon-only buttons have labels.
- Real heading hierarchy, labelled fields, live regions for job status and chat replies.
- Reduced motion honoured.

## Avoid

- Slate/blue SaaS palettes, gradients, glassmorphism, drop shadows, pill-shaped everything.
- Dark mode, theme toggles.
- Colour as the only signal; emoji as icons; oxblood used decoratively.
