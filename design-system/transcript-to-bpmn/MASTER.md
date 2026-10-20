# Transcript to BPMN: design system (MASTER)

Global source of truth for the web app (`web/`). Page-specific overrides go in `pages/<page>.md`.
Every decision below was chosen by the product owner from researched options, not defaulted;
the source of each is noted so it can be revisited deliberately.

## Direction: Process dossier

The product's output is process documentation, so the UI reads like a consulting deliverable or
SOP binder: paper, ink, a reviewer's red pen. Calm and editorial, never "dashboard SaaS".

- Style basis: **E-Ink / Paper**, inverted: the dossier read at night (warm near-black paper,
  warm light ink). Light version was built first; the owner preferred dark (2026-10-16).
- Users: **both, analyst-first**. Power and density where analysts work (tables, editor);
  review and export always obvious for occasional reviewers.
- Theme: **dark only**. No light mode, no theme switcher. Exports (BPMN/SOP/PNG/SVG) stay
  standard light styling; only the on-screen editor is themed.

## Minimal pass (2026-10-20): what changed, chosen by the owner

The tool is used by consultants, mostly alone while preparing, so it should be minimalist.
Decisions (each picked from options with the ui-ux-pro-max skill):

| Area | Decision |
|---|---|
| Starting point | Strip the dossier: keep its bones, remove ornament |
| Theme | Dark only (unchanged) |
| Type | **Lato only**; EB Garamond removed. Hierarchy by size and weight; no italics |
| Colour | **Monochrome + one signal**: greys; primary buttons light-on-dark (ink on paper); focus ring light. Oxblood only for what needs attention: open disagreements and policy differences (their numerals and counts), disputed steps on the diagram, errors, destructive actions |
| Numbering | Kept: roman numerals for disagreements, § for policy differences, ¶ for files, ? for gaps |
| Labels | Sentence case, small, muted (no small caps) |
| Lines | Only where they separate (list rows, under the page title, between folded sections); no boxed panels or decorative rules |
| Density | Airy page, compact lists |
| Process page | **One column, progressive**: every section is a row with a count; Points of disagreement and Meetings and files open by default; Against the policy, Gaps, Speakers, Sign-off folded |
| Editor | **Canvas first**: the diagram fills the width; the side panel opens only for a selected step, Questions (toolbar button with count) or Issues; one-line "Describe a change" under the diagram; Fit, History, Issues in the ⋯ menu |

Where this file below says serif, small caps or oxblood buttons, the table above wins.

## Colour (all contrast measured against paper #151311)

| Token | Value | Use | Contrast |
|---|---|---|---|
| `--paper` (background) | `#151311` | page | |
| `--sheet` (card) | `#1D1A17` | sheets, inputs, diagram shapes (set apart by hairline, not shadow) | ink 13.9:1 |
| `--paper-shade` (muted) | `#26221E` | hover, selected rows, inset areas | ink 12.7:1 |
| `--ink` (foreground) | `#ECE6DA` | text, diagram strokes | 14.9:1 |
| `--graphite` (muted-foreground) | `#A8A196` | secondary text, labels | 7.2:1 |
| `--oxblood` (accent) | `#D4716A` | **only** disagreements, focus ring, destructive outline, marks | 5.6:1 (on tint 4.7:1) |
| `--oxblood-deep` (primary) | `#8B2E2A` | filled primary button (hover `#9E3732`) | ink on it 6.7:1 |
| `--oxblood-tint` | `#33201D` | disagreement highlight background | |
| `--hairline` | `#2C2824` | decorative rules, sheet borders | decorative |
| `--rule` | `#3B3631` | stronger decorative rules (section dividers) | decorative |
| `--control` | `#7A7368` | form-control borders (meaningful boundary) | 4.0:1 (≥3:1) |

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

- bpmn-js renders on paper with ink strokes and EB Garamond labels; sheet (#1D1A17) fill for tasks, light ink strokes.
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
