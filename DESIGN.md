# Design: the daily weather chart

AetherGuard looks like the chart a weather service plots each morning, and behaves like one being plotted. Written from
the built interface (`dashboard/src`); the tokens in `dashboard/src/styles/tokens.css` are the source of truth.

## The world

A sheet of pale chart paper lying on a sea-tinted page. Everything on it is ink on paper: nothing glows, nothing is
added to the ground colour. Panels are slips of the same paper laid on the chart, with an ink hairline and a soft ink
shadow. The terrain is the protagonist; chrome steps back.

## Colour (seven, and their mixes only)

| Token | Hex | Role |
|---|---|---|
| `--paper` | `#EEF2EC` | the sheet: land, panels, text on the accent |
| `--ink` | `#17233D` | text, coastlines, borders, shadows (thinned with transparency) |
| `--slate` | `#2F6F8F` | the sea tint, height tint of the relief, the graticule, Normal |
| `--signal` | `#1746C7` | the plotting blue: the one accent (actions, focus, selection, rain) |
| `--yellow` | `#F0B400` | Watch |
| `--orange` | `#E8700C` | Warning |
| `--red` | `#C8201C` | Emergency |

The three warning hues are the weather service's own colour code and are used for levels only. On paper they are fills;
as text they are darkened with ink (`--level-watch-text`, `--warn`, `--danger`). `palette.test.ts` enforces that every
colour is one of the seven or a mix, that body text is at least 4.5:1 on every surface, and that yellow and orange
never set text.

## Type

- **National Park** (display): monoline, routed lettering, as on a drawn chart. Headings and the wordmark.
- **Atkinson Hyperlegible Next** (text): built for legibility; everything that is read.
- **Atkinson Hyperlegible Mono** (data, class `num`): ids, coordinates, probabilities, counts, dates, so a number
  never reads as a word.

All three are self-hosted variable fonts (weights 200 to 800) under the SIL Open Font License.

## The scene

- Relief: paper tinted with height, shadows laid in as a wash of ink, lit north-west slopes left bare. Contours in
  sepia. Neighbouring countries sink toward the sea tint.
- A 5-degree graticule lies over land and sea.
- Levels are draped on the terrain as flat colour and raised as columns for Warning and Emergency. Columns rise out of
  the ground; they never fade in.
- Rain is short strokes of the plotting blue where the day's field says it rained.

## Motion

One authored move: **scrolling plots the chart.** On the home page the camera follows the scroll along one pose per
chapter, and each chapter adds a layer (lines, relief, rain, levels). The last chapters rest on the live map's own
view, so entering the map moves nothing; leaving the story mid-chapter is a camera flight, never a cut. Copy settles
as its chapter reaches the reading position and lifts away as it leaves. Between views, the bar and terrain hold still
and only the view changes hands (view transitions); the navigation pill slides. Ease-out everywhere
(`cubic-bezier(0.16, 1, 0.3, 1)`), 160 / 260 / 520 ms. With reduced motion the layers appear at once, the camera
jumps, and copy is simply visible.

## Layout

A top bar (brand, three views, data status) with a ledger row of the day's counts under it. The story is full-height
chapters, one slip of copy on the left, the map drawn to the right of it, a margin scale of chapter ticks on the right
edge. Under 900 px the slip sits at the bottom of the chapter and the margin scale is hidden.

## Rules

- No invented numbers. Every figure comes from the API or a committed report.
- The research-prototype notice stays on the first screen.
- No glow, no gradients on text, no glass as decoration, no cards inside cards.
