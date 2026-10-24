# Transcript to BPMN: design system (MASTER)

Source of truth for the web app. Tokens live in `web/src/index.css`.

## Direction: Industrial print (2026-10-25)

Chosen by the user via the industrial-brutalist-ui skill: **Swiss Industrial Print**, light only. Unbleached paper,
carbon ink, one aviation red. Rigid compartments drawn with ink rules, huge uppercase headings, mono telemetry. Light
only: never mix in a dark substrate. It replaces the dark "Swiss workbench" look; the structure below is unchanged.

## Structure: guided steps (kept)

- A process is four steps, **01 Meetings → 02 Review → 03 Improve → 04 Share**, one on screen at a time.
- The page opens on the first step that needs you and pins it in `?step=`. Every step ends with `>>> NEXT: … →`.
- **Review is a short list; open one.** Each row: hazard stripe on the left edge, `[ KIND ] · #01` label, the one-line
  question, then a one-line subtitle. Opening a row shows the evidence and the choices. One row open at a time.
- "Open the map" is always in the page header.

## Colour (contrast measured against paper #F4F4F0)

| Token         | Hex     | Use                                                 | Contrast       |
| ------------- | ------- | --------------------------------------------------- | -------------- |
| `bg`          | #F4F4F0 | paper                                               |                |
| `surface`     | #EAE8E3 | hover rows, current step                            |                |
| `raised`      | #FFFFFF | fields, menus, opened review row, diagram shapes    |                |
| `fg`          | #111111 | ink: text, compartment rules, focus ring            | 17.1           |
| `fg-muted`    | #3A3A36 | secondary text, labels                              | 10.4           |
| `fg-subtle`   | #5C5C56 | telemetry, inactive numerals                        | 6.1            |
| `control`     | #76766F | disabled borders                                    | 4.2 (≥3 UI)    |
| `line`        | #C9C7C0 | soft row dividers (decorative)                      |                |
| `line-strong` | #111111 | structural rules                                    |                |
| `signal`      | #C41414 | red **text** and the main button (white type 6.1)   | 5.5            |
| `hazard`      | #E61919 | stripes, big numerals, disputed steps on the map    | 4.2: never small text |

Red means exactly three things: **needs you** (counts, stripes, review labels), the **current step's numeral**, and the
**one main button** per view. Focus is a 2px **ink** outline. Status is always glyph + words, never colour alone.

## Typography (self-hosted, @fontsource 5.3.0)

- **Archivo Black** for macro type (`.macro`): uppercase, tracking -0.04em, leading 0.9. Page title
  `clamp(2.75rem, 8vw, 7rem)`. Step and section headings `clamp(2rem, 5vw, 3.5rem)`. Numerals 01–04 at up to 4rem.
- **IBM Plex Mono** for labels, telemetry, nav, buttons and tabs (`.label`): 12–13px, uppercase, tracking 0.06–0.08em.
- **Inter** for sentences: questions, quotes, descriptions and help. 16px, normal case, line-height 1.55. Long text
  is never set in uppercase mono.

## Layout & ornament

- Compartments: 2px ink rules. The step bar is a `gap-[2px]` grid on ink. Square corners everywhere (all radius 0).
- Page header: a telemetry strip between two ink rules, with `+` registration marks on its corners. On the left, the
  back link or `///`; on the right, real data such as `UNIT / P-1388 · REV 2`.
- ASCII framing: `[ SECTION ]`, `>>>`, `///`. The brackets and arrows are `aria-hidden`.
- Hazard stripes (`.stripes`) appear only next to words that say "needs you". The barcode rule (`.barcode`) sits in the footer.
- Texture: one fixed, 5%-opacity SVG grain over the page, with `pointer-events: none`. No scanlines or halftone; the
  user chose subtle.
- Width: max 1120px, gutter 16px on phones and 32px from sm up. No horizontal scroll at 375px; checked. Phones show the
  short wordmark `T2B`, with "Transcript to BPMN" kept for screen readers.

## Motion

120ms in, 80ms out, colour and opacity only. Honour `prefers-reduced-motion`.

## The diagram

bpmn-js is themed for rendering only: white shapes with ink strokes on paper, and Inter labels. Disputed steps get a
hazard outline and a numbered tag with white text (4.65:1). Saved XML and exports keep standard BPMN styling.

## Avoid

- Gradients, shadows, translucency and rounded corners.
- Hazard red as small text (use `signal`), or red used for decoration.
- Uppercase or mono for sentences.
- Showing every section at once: one step per screen.
