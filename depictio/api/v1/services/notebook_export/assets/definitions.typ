
#let dpx-well = luma(246)
#let dpx-zebra = luma(250)
#let dpx-svg(svg, h) = box(baseline: 12%, image(bytes(svg), height: h))
// A grid cell of the dashboard's rows (Quarto's layout draws each as a rect):
// a quiet card, as the page draws its tiles.
#show rect: it => block(width: 100%, stroke: 0.6pt + dpx-hair, radius: 6pt,
  inset: (x: 10pt, y: 8pt), it.body)
// A KPI card: its title and icon, the value, the caption, its numbers.
#let dpx-kpi(title, value, caption: none, icon: none, secondary: none) = block(
  width: 100%, stroke: 0.6pt + dpx-hair, radius: 6pt, inset: 9pt,
  breakable: false)[
  #grid(columns: (1fr, auto), align: (left + top, right + top),
    text(size: 8pt, weight: "semibold")[#title],
    if icon != none { image(bytes(icon), height: 14pt) })
  #v(1pt)
  #text(size: 17pt, weight: "bold", tracking: -0.02em)[#value]
  #if caption != none [ #v(-3pt) #text(size: 7.2pt, fill: dpx-muted)[#caption] ]
  #if secondary != none [ #v(3pt) #secondary ]
]
#let dpx-kpis(..cards) = {
  let n = cards.pos().len()
  grid(columns: (1fr,) * calc.min(n, 4), column-gutter: 7pt, row-gutter: 7pt, ..cards.pos())
}
#let dpx-bars(items, color) = grid(columns: (auto, 1fr, auto), column-gutter: 4pt,
  row-gutter: 3pt, align: (left + horizon, left + horizon, right + horizon),
  ..items.map(((name, frac, note)) => (
    text(size: 6.8pt)[#name],
    box(width: 100%, height: 4pt, radius: 2pt, fill: luma(232),
      box(width: frac * 100%, height: 4pt, radius: 2pt, fill: color)),
    text(size: 6.8pt, fill: dpx-muted)[#note])).flatten())
#let dpx-range(lo, mid, hi) = grid(columns: (1fr, auto, 1fr),
  align: (left, center, right), text(size: 7pt, fill: dpx-muted)[#lo],
  text(size: 7pt, weight: "semibold")[median #mid], text(size: 7pt, fill: dpx-muted)[#hi])
// A table: a header row on a well, zebra rows, a rule under the header.
#let dpx-table(columns: (), align: (), header: (), rows: (), note: none) = {
  set text(size: 7.3pt)
  set par(justify: false, leading: 0.5em)
  table(columns: columns, align: align, inset: (x: 4.5pt, y: 3.6pt), stroke: none,
    fill: (x, y) => if y == 0 { dpx-well } else if calc.even(y) { dpx-zebra } else { none },
    table.header(..header.map(h => text(weight: "semibold", fill: dpx-muted)[#h])),
    table.hline(stroke: 0.6pt + dpx-hair),
    ..rows.flatten().map(c => [#c]))
  if note != none { v(-4pt); text(size: 6.8pt, fill: dpx-muted, style: "italic")[#note] }
}
// A tile that could not be drawn: its name, one neutral sentence. It marks
// itself, so the caption under it does not claim to show data.
#let dpx-failed = state("dpx-failed", false)
#let dpx-note(title, detail) = block(width: 100%, inset: 8pt, radius: 4pt,
  stroke: (paint: dpx-hair, dash: "dashed"))[
  #text(size: 8pt, weight: "semibold")[#title] #text(size: 8pt, fill: dpx-muted)[#detail]
  #dpx-failed.update(true)]
// A caption's "Data: ... as of" badge, left out under a tile that failed;
// read once, so the next tile starts clear.
#let dpx-asof(badge) = {
  context if not dpx-failed.get() { text(fill: dpx-muted)[#badge] }
  dpx-failed.update(false)
}
#let dpx-tile-done = dpx-failed.update(false)
// The stepper (`::: steps`): a disc with the step's icon, the line to the
// next, the label over the step's text.
#let dpx-steps(steps, color) = grid(columns: (1fr,) * steps.len(), column-gutter: 6pt,
  ..steps.enumerate().map(((i, (icon, label, body))) => block[
    #box(width: 100%, height: 22pt)[
      #place(left + horizon, circle(radius: 11pt, fill: color, stroke: none,
        if icon != none { align(center + horizon, image(bytes(icon), height: 11pt)) }))
      #if i < steps.len() - 1 {
        place(left + horizon, dx: 27pt, line(length: 100% - 30pt,
          stroke: 1.2pt + color.lighten(55%)))
      }
    ]
    #v(2pt)
    #text(size: 6.8pt, weight: "bold", fill: dpx-muted, tracking: 0.06em)[#upper(label)]
    #v(-3pt)
    #text(size: 8.3pt, weight: "semibold")[#body]
  ]))
// A fact list ("The run"): a muted icon and label, then the value.
#let dpx-facts(rows) = grid(columns: (auto, auto, 1fr), column-gutter: 6pt,
  row-gutter: 0pt, align: left + top,
  ..rows.map(((icon, label, value)) => (
    if icon != none { box(inset: (y: 4pt), image(bytes(icon), height: 9pt)) } else [],
    box(inset: (y: 4pt), text(fill: dpx-muted)[#label]),
    box(inset: (y: 4pt), width: 100%, stroke: (bottom: 0.4pt + dpx-hair))[#value])).flatten())
