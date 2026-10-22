# Transcript to BPMN: design system (MASTER)

Source of truth for the web app. Tokens live in `web/src/index.css`. Page-specific overrides would go
in `pages/`; there are none.

## Direction: Swiss workbench (2026-10-23)

Chosen by the user after "the page looks too cluttered". Minimalism & Swiss style, dark only:
generous white space, a strict grid, large clear type, near-black text surfaces, and **one** strong accent.
It replaces the "process dossier" look (serif, small caps, oxblood, roman numerals); all of that ornament is gone.

## Structure: guided steps

- A process is four steps: **1 Meetings → 2 Review → 3 Improve → 4 Share**, one on screen at a time.
  - Meetings: meetings, policy documents, speakers, the live interview.
  - Review: disagreements, policy differences, gaps, and checking the AI's draft.
  - Improve: improvement suggestions.
  - Share: sign-off, exports, the next meeting's agenda, and deleting the process.
- The step bar shows each step's state in words: done (✓ filled box), **needs you** (signal red), or not started.
- **Open where you're needed.** With no `?step=`, the page opens on the first step that needs action and pins it in the
  URL, so polling never moves the person off the step they're on.
- Every step ends with **Next: … →**. "Open the map" always sits in the page header.
- **Review is a short list; open one item.** Each row is a kind label, a one-line question and a one-line subtitle
  (the options, or what to ask). Opening a row shows the evidence and the choices. Only one row is open at a time.

## Colour (contrast measured against bg #0F0F0F)

| Token         | Hex     | Use                                                    | Contrast       |
| ------------- | ------- | ------------------------------------------------------ | -------------- |
| `bg`          | #0F0F0F | page                                                   |                |
| `surface`     | #171717 | hover rows, current step, cards, the diagram's shapes  |                |
| `raised`      | #202020 | menus, skeletons, selected                             |                |
| `fg`          | #F4F4F2 | text                                                   | 17.4           |
| `fg-muted`    | #B3B3AF | secondary text, labels                                 | 9.1            |
| `fg-subtle`   | #94948F | tertiary (quote numbers, arrows)                       | 6.3            |
| `control`     | #77776F | input and outline-button borders                       | 4.2 (≥3 UI)    |
| `line`        | #2B2B2A | dividers (decorative)                                  |                |
| `line-strong` | #3D3D3B | stronger dividers (decorative)                         |                |
| `signal`      | #FF5A45 | **the one accent**                                     | 6.2            |
| `signal-tint` | #2E1714 | text selection                                         |                |

**Signal red is used only** for "needs you" counts, the current step, the main button (one per view, dark #0F0F0F text
on red, 6.2:1), the focus ring, and disputed steps on the map. Never for decoration. Status is always given as glyph +
words, never as colour alone.

## Typography

- Headings and labels: **Lexend** (variable, self-hosted via @fontsource-variable/lexend 5.3.0). Weight 600,
  tracking -0.015em.
- Text: **Source Sans 3** (variable, @fontsource-variable/source-sans-3 5.3.0). 16px base, line-height 1.55.
- Page title 36px, or 48px from sm up. Step heading 28px. Review row question 18px, Lexend 500.
- `.label`: Lexend 12px, weight 500, uppercase, tracking 0.08em, fg-muted. It replaces the old small caps.
- No serif, no italics, no roman numerals: points are plain numbers.

## Layout

- Content max-width 1120px with a 16px gutter on mobile and 32px from sm up. Steps' content max-width 880px.
- Space separates the groups (56px between sections); 1px `line` dividers, not boxes.
- Corners are near-square: 2–4px radius.
- No horizontal scroll at 375px (checked).

## Motion

150ms in and 100ms out, on colour and opacity only. Honour `prefers-reduced-motion`.

## The diagram

bpmn-js is themed for rendering only: surface-coloured shapes, fg strokes and Source Sans labels. Disputed steps have a
signal outline and a small numbered tag. Saved XML and exports keep standard BPMN styling.

## Accessibility

- Text contrast is ≥ 4.5:1 everywhere (see the table); UI borders are ≥ 3:1.
- One visible focus style: a 2px signal outline with a 2px offset.
- Expandable review rows use `aria-expanded` and `aria-controls`; the step bar uses `aria-current="step"`.
- Every icon is `aria-hidden` next to visible text; the touch target is ≥ 36px, and the step and row buttons span the
  full width.
- Visible labels on every field; errors sit next to the field (`role="alert"`).

## Avoid

- Showing every section at once. One step per screen.
- More than one red element competing in a view, other than "needs you" counts.
- Chips, pills and gradients; the "generic SaaS" slate-and-teal look that was rejected.
- Long explanatory text on list rows: one line, and the detail goes in the opened item.
