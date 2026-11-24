// The HTML report's marker divs (``data-depictio-*``, read by the editor's
// live preview) reach typst as bare ``#block[...]``: a container, and a page
// configuration (a landscape page) is refused inside one. A block with no
// argument but its body draws nothing of its own, so it is its body here;
// every block that asks for something keeps typst's own.
#let block(..args) = if args.named().len() == 0 and args.pos().len() == 1 {
  args.pos().at(0)
} else {
  std.block(..args)
}

#let dpx-well = luma(246)
#let dpx-zebra = luma(240)
// A table's header row and its cell rules: dark enough to follow a row or a
// column across the page, as in a spreadsheet.
#let dpx-table-head = luma(222)
#let dpx-table-rule = luma(200)
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
// A value the dashboard colours: tinted with its colour, as in the report's
// HTML tables and the dashboard's filters.
#let dpx-chip(t, c) = box(fill: c.lighten(85%), inset: (x: 3.6pt, y: 1.3pt), outset: (y: 0.4pt),
  radius: 5pt)[#text(fill: c.darken(32%), weight: "medium")[#t]]
// A table read like a spreadsheet: a bold header row on a darker band, rows
// alternating grey and white, a rule around every cell.
// A value over its data bar (MultiQC's General Statistics): the bar runs the
// cell's share, in the column's colour, the value on it.
#let dpx-bar-cell(t, share, c) = box(width: 100%)[
  #place(left + horizon, dx: -3pt, box(width: share * 100% + 3pt, height: 1.15em, fill: c, radius: 1pt))
  #t
]
#let dpx-table(columns: (), align: (), header: (), rows: (), note: none) = {
  set text(size: 7.3pt)
  set par(justify: false, leading: 0.5em)
  table(columns: columns, align: align, inset: (x: 4.5pt, y: 3.6pt),
    stroke: 0.5pt + dpx-table-rule,
    fill: (x, y) => if y == 0 { dpx-table-head } else if calc.even(y) { dpx-zebra } else { white },
    table.header(..header.map(h => text(weight: "bold", fill: dpx-ink)[#h])),
    table.hline(y: 1, stroke: 1pt + dpx-muted),
    ..rows.flatten().map(c => if type(c) == dictionary {
      if "bar" in c { dpx-bar-cell(c.text, c.bar, rgb(c.color)) } else { dpx-chip(c.chip, rgb(c.color)) }
    } else [#c]))
  if note != none { v(-4pt); text(size: 6.8pt, fill: dpx-muted, style: "italic")[#note] }
}
// A wide tile (a table with more columns than a portrait page holds, a figure
// wider than the page is tall): marked so the show rule below turns its page.
// A tile's output sits inside its float, and page configuration is allowed
// only at the top level of the flow, so the mark rides in the float's body
// and the rule -- itself top level -- does the flipping for it. The mark is
// zero-size text: the rule reads the body's evaluated source (``repr``),
// which keeps text but not the names of the functions that drew it.
#let dpx-wide-mark = box[#text(size: 0pt)[dpx-wide]]
#let dpx-wide(body) = block(width: 100%)[#dpx-wide-mark #body]
#let dpx-is-wide(it) = (
  it.func() == figure and str(it.kind).starts-with("quarto-float")
    and repr(it.body).contains("dpx-wide")
)
// What reads next to (or before) an element in the flow. A heading whose next
// element is a wide float would be left alone at the foot of a portrait page
// by the page turn, so it moves onto the landscape page instead: drawn as
// nothing where it was (the rule doing that comes last in the body, after the
// report's own heading rules, so it sees the heading first; the element stays,
// so the contents still list it), and drawn again above the float as plain
// styled text: a copy that is not a heading takes no tab page
// break and no sticky block, either of which would leave a blank page.
#let dpx-flow = selector(heading).or(figure).or(par).or(table).or(image)
#let dpx-next(loc) = query(dpx-flow.after(loc)).find(e => e.location() != loc)
#let dpx-prev(loc) = query(dpx-flow.before(loc)).filter(e => e.location() != loc).last(default: none)
#let dpx-heading-size = (18pt, 15pt, 12pt, 10.5pt, 9.5pt)
#let dpx-heading-copy(h) = align(left, block(below: 0.65em, text(font: dpx-sans, weight: "bold",
  fill: dpx-ink, size: dpx-heading-size.at(calc.min(h.level, 5) - 1))[#h.body]))
// Typst refuses a page configuration inside a container (block, grid, box),
// so a wide figure in one (a row of the dashboard's grid, a callout) stays on
// its portrait page rather than failing the whole PDF. The flag is a style
// (a highlight extent nothing else sets), not a state: a style is known on the
// first layout pass, a state only once the layout converges, and the refused
// page would already have failed the compile.
#show std.block: set highlight(extent: 0.01pt)
#show grid: set highlight(extent: 0.01pt)
#show box: set highlight(extent: 0.01pt)
// Whether a wide figure did turn its page: the heading before it moves onto
// that page only then.
#let dpx-flips(it) = query(<dpx-flip>).any(m => m.value == it.location())
#show figure: it => context {
  if not dpx-is-wide(it) or highlight.extent != 0pt { return it }
  let prev = dpx-prev(it.location())
  page(flipped: true)[
    #metadata(it.location()) <dpx-flip>
    #if prev != none and prev.func() == heading { dpx-heading-copy(prev) }
    #it
  ]
}
// A table taller than a page breaks across pages instead of being cut off.
#show figure.where(kind: "quarto-float-tbl"): set std.block(breakable: true)
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
// next, the label over the step's text. A step's links (the tab showing its
// result, its run parameters) are small icons after its label, as live.
#let dpx-steps(steps, color) = grid(columns: (1fr,) * steps.len(), column-gutter: 6pt,
  ..steps.enumerate().map(((i, step)) => {
    let (icon, label, body, ..rest) = step
    let links = rest.at(0, default: ())
    block[
      #box(width: 100%, height: 22pt)[
        #place(left + horizon, circle(radius: 11pt, fill: color, stroke: none,
          if icon != none { align(center + horizon, image(bytes(icon), height: 11pt)) }))
        #if i < steps.len() - 1 {
          place(left + horizon, dx: 27pt, line(length: 100% - 30pt,
            stroke: 1.2pt + color.lighten(55%)))
        }
      ]
      #v(2pt)
      #text(size: 6.8pt, weight: "bold", fill: dpx-muted, tracking: 0.06em)[#upper(label)]#for l in links [#h(3pt)#box(image(bytes(l), height: 7.5pt), baseline: 1pt)]
      #v(-3pt)
      #text(size: 8.3pt, weight: "semibold")[#body]
    ]
  }))
// A findings list: the figure large in its tab's colour, the claim in bold
// over its dimmed context, the tab on the right. Rows are (stat, claim,
// context, link, colour); an empty context or link, or no colour, is left out.
#let dpx-findings(rows) = grid(columns: (86pt, 1fr, auto),
  stroke: (x, y) => if y > 0 { (top: 0.4pt + dpx-hair) },
  inset: (x, y) => (y: 6pt, right: if x < 2 { 10pt } else { 0pt }), align: horizon,
  ..rows.map(((stat, claim, ctx, link, color)) => (
    text(size: 17pt, weight: "bold", tracking: -0.02em,
      fill: if color == none { dpx-ink } else { color })[#stat],
    [#text(size: 8.6pt, weight: "bold")[#claim]#if ctx != "" [ \ #text(size: 8pt, fill: dpx-muted)[#ctx]]],
    if link != "" { text(size: 8pt, fill: dpx-accent)[#link] } else [])).flatten())
// Tab tiles (a list of links to tabs): a framed card each, the tab's name and
// the question it answers, its icon resting faint on the right. A numbered
// list leads each tile with its number. Tiles are (icon, colour, name, line, num).
#let dpx-tab-tiles(tiles) = grid(columns: (1fr,) * 3, column-gutter: 8pt, row-gutter: 8pt,
  ..tiles.map(((icon, color, name, line, num)) => std.block(width: 100%, breakable: false,
    stroke: 0.6pt + dpx-hair, radius: 6pt, inset: 9pt)[
    #grid(columns: (1fr, auto), column-gutter: 6pt, align: (left + top, right + top),
      [#if num != "" [#text(size: 14pt, weight: "bold", fill: color)[#num]#linebreak()]
       #text(size: 9pt, weight: "bold")[#name]#if line != "" [#linebreak()#text(size: 8pt, fill: dpx-muted)[#line]]],
      if icon != none { image(bytes(icon), height: 16pt) })]))
// A fact list ("The run"): a muted icon and label, then the value.
#let dpx-facts(rows) = grid(columns: (auto, auto, 1fr), column-gutter: 6pt,
  row-gutter: 0pt, align: left + top,
  ..rows.map(((icon, label, value)) => (
    if icon != none { box(inset: (y: 4pt), image(bytes(icon), height: 9pt)) } else [],
    box(inset: (y: 4pt), text(fill: dpx-muted)[#label]),
    box(inset: (y: 4pt), width: 100%, stroke: (bottom: 0.4pt + dpx-hair))[#value])).flatten())
