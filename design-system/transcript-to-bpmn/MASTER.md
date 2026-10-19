# Transcript to BPMN: design system (MASTER)

Second direction (2026-10-20), chosen by the owner question by question with the
ui-ux-pro-max skill. Replaces the "process dossier" (serif, oxblood, paper/ink), which read
like a document; this one should feel unmistakably like software.

## Decisions

| Area | Decision |
|---|---|
| Direction | **Modern product UI** (skill style DB: Flat/Minimal, dark supported): layered slate surfaces, bordered panels, chips; Linear/Height family, not generic teal-SaaS marketing |
| Theme | **Dark only** |
| Type | **Inter only** ("Modern Dark Cinema" pairing), self-hosted variable font; tabular numbers for counts, versions, times |
| Accent | **Teal** (#2DD4BF) for primary actions, links and focus only |
| Meaning colour | **Tinted chips, always icon + word**: done green, processing teal, failed red, disagreement amber, policy violet, gap slate |
| Item ids | **D1, D2…** disagreements · **P1…** policy differences · **G1…** gaps; the same id on the diagram marker and in the agenda |
| Navigation | **Collapsible left sidebar**: process list with open counts, + new process, Settings; drawer on small screens |
| Home | **Inbox of open work** across processes |
| Process page | **Tabs**: Review · Sources · Sign-off · Settings (in the URL: `?tab=`) |
| Editor | **Full-bleed canvas + collapsible, resizable right inspector + floating "Describe a change" bar** |
| Canvas | **Light sheet on dark** (looks like the export stakeholders get) |
| Density | **Comfortable**: 14px UI text, 36px controls, 40px rows, 16px panel padding |
| Shortcuts | **None** (point-and-click only) |
| Shape & motion | **8px panels, 6px controls; 150–200ms colour/opacity fades**, nothing under reduced motion |

## Palette (contrast vs panel #181B21 unless noted)

| Token | Value | Use | Contrast |
|---|---|---|---|
| `app` | #111318 | page background, inset inputs | |
| `panel` | #181B21 | panels, sidebar | |
| `raised` | #20242C | hover, menus, selected rows | |
| `line` / `line-strong` | #2B3039 / #3B414D | decorative borders | decorative |
| `control` | #69717F | form-control borders | 3.5:1 (≥3, on raised 3.2) |
| `fg` | #E7E9ED | text | 14.2:1 |
| `fg-muted` | #A1A8B3 | secondary text, labels | 7.2:1 |
| `fg-subtle` | #8A92A0 | tertiary text | 5.5:1 (4.96 on raised) |
| `brand` | #2DD4BF | actions, focus ring | 9.3:1; text on it #062A26 8.3:1 |
| chips | text on 14% tint | ok #4ADE80 7.4 · bad #F87171 5.1 · warn #FBBF24 7.6 · policy #A78BFA 5.1 · gap #94A3B8 5.3 |
| `sheet` / `sheet-ink` | #F7F8FA / #111827 | diagram sheet | 16.7:1 |

## Rules

- One primary (teal) button per view. Disabled buttons go neutral, never faded teal.
- Destructive: red outline + a confirmation step (type-to-confirm for deleting a process).
- Quotes are evidence: speaker · role · meeting @ time under every quote.
- Focus: 2px teal outline, 2px offset, everywhere. Targets ≥ 24px (controls 32–36px).
- No shadows except menus/dialogs; no gradients; no glow.
- Layout must work at 375px with no horizontal scroll (sidebar becomes a drawer).
- Exports stay standard BPMN; only the on-screen canvas is themed.
