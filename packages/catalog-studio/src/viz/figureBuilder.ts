/**
 * Build a Plotly `{data, layout}` from a render spec + in-memory fixture rows.
 *
 * IMPORTANT: this is a CLIENT-SIDE APPROXIMATION for preview only. depictio's
 * authoritative figure is built in Python (`_create_figure_from_data`, plotly-
 * express) and the advanced_viz renderers in depictio-react-core. We re-derive
 * the geometry here (lifting the pure logic from those renderers, minus the
 * backend fetch) so the designer sees a live plot. `dev catalog validate` /
 * depictio remain the source of truth for the real render.
 */
// Import the shared palette from its module directly (not the barrel) so we
// don't pull react-core's full renderer tree — and its heavy peers — into this
// backend-less bundle.
import { TAB10_PALETTE } from 'depictio-react-core/colors';
import type { AdvancedVizRender, FigureRender, ParsedFixture, RenderSpec } from '../types';

export interface PlotlyFigure {
  data: Record<string, unknown>[];
  layout: Record<string, unknown>;
}

/** Reason a render can't be previewed (heavy advanced_viz, missing binding). */
export interface PreviewUnavailable {
  unavailable: true;
  reason: string;
}

export type PreviewResult = PlotlyFigure | PreviewUnavailable;

export function isUnavailable(r: PreviewResult): r is PreviewUnavailable {
  return (r as PreviewUnavailable).unavailable === true;
}

// ── column accessors ───────────────────────────────────────────────────────

function col(rows: Record<string, unknown>[], name?: string): unknown[] {
  if (!name) return [];
  return rows.map((r) => r[name]);
}
function numCol(rows: Record<string, unknown>[], name?: string): number[] {
  return col(rows, name).map((v) => (v === '' || v == null ? NaN : Number(v)));
}
function isNumericColumn(fixture: ParsedFixture, name?: string): boolean {
  const c = fixture.columns.find((x) => x.name === name);
  return c ? c.dtype === 'Int64' || c.dtype === 'Float64' : false;
}

const baseLayout = (): Record<string, unknown> => ({
  autosize: true,
  margin: { l: 50, r: 20, t: 30, b: 45 },
  showlegend: true,
});

// ── basic figures (visu_type + dict_kwargs) ────────────────────────────────

function buildBasicFigure(fixture: ParsedFixture, render: FigureRender): PreviewResult {
  const { rows } = fixture;
  const kw = render.dict_kwargs;
  const x = kw.x;
  const y = kw.y;
  const color = kw.color;

  if (!x && render.visu_type !== 'box') {
    return { unavailable: true, reason: 'Set an x binding to preview.' };
  }

  const layout = baseLayout();
  layout.xaxis = { title: { text: x || '' } };
  layout.yaxis = { title: { text: y || '' } };

  // group rows by a categorical color column → one trace each.
  const grouping = color && !isNumericColumn(fixture, color);
  const groups = new Map<string, number[]>();
  if (grouping) {
    rows.forEach((r, i) => {
      const key = String(r[color] ?? '—');
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key)!.push(i);
    });
  } else {
    groups.set('all', rows.map((_, i) => i));
  }

  const pick = <T,>(arr: T[], idx: number[]) => idx.map((i) => arr[i]);
  const xs = col(rows, x);
  const ys = numCol(rows, y);
  const palette = TAB10_PALETTE;

  const data: Record<string, unknown>[] = [];
  let gi = 0;
  for (const [key, idx] of groups) {
    const traceColor = palette[gi % palette.length];
    const name = grouping ? key : y || x || '';
    const gx = pick(xs, idx);
    const gy = pick(ys, idx);
    switch (render.visu_type) {
      case 'histogram':
        data.push({ type: 'histogram', x: gx, name, marker: { color: traceColor }, opacity: grouping ? 0.7 : 1 });
        break;
      case 'bar':
        data.push({ type: 'bar', x: gx, y: gy, name, marker: { color: traceColor } });
        break;
      case 'line':
        data.push({ type: 'scatter', mode: 'lines+markers', x: gx, y: gy, name, line: { color: traceColor } });
        break;
      case 'box':
        data.push({ type: 'box', y: y ? gy : (gx as number[]), x: y && x ? gx : undefined, name, marker: { color: traceColor } });
        break;
      case 'heatmap':
        // density heatmap of x,y — Plotly 2d histogram.
        data.push({ type: 'histogram2d', x: gx, y: gy, colorscale: 'Blues' });
        layout.showlegend = false;
        break;
      case 'scatter':
      default:
        if (color && !grouping) {
          data.push({
            type: 'scattergl',
            mode: 'markers',
            x: gx,
            y: gy,
            marker: { color: numCol(rows, color), colorscale: 'Viridis', showscale: true },
            name: y || '',
          });
          layout.showlegend = false;
        } else {
          data.push({ type: 'scattergl', mode: 'markers', x: gx, y: gy, name, marker: { color: traceColor } });
        }
        break;
    }
    gi++;
  }
  if (grouping && (render.visu_type === 'histogram')) layout.barmode = 'overlay';
  return { data, layout };
}

// ── simple advanced_viz previews (lifted from react-core renderers) ─────────

function buildVolcano(fixture: ParsedFixture, roles: Record<string, string>): PreviewResult {
  const { rows } = fixture;
  const xs = numCol(rows, roles.effect_size);
  const pRaw = numCol(rows, roles.significance);
  const ids = col(rows, roles.feature_id);
  // significance assumed raw p/padj → -log10.
  const ys = pRaw.map((p) => (p == null || p <= 0 || Number.isNaN(p) ? null : -Math.log10(p)));
  const sigY = -Math.log10(0.05);
  const effT = 1.0;
  const colors = xs.map((x, i) => {
    const y = ys[i];
    if (y == null) return 'rgba(160,160,160,0.55)';
    const hit = y >= sigY && Math.abs(x) >= effT;
    return hit ? (x > 0 ? '#e64980' : '#1c7ed6') : 'rgba(160,160,160,0.55)';
  });
  return {
    data: [
      {
        type: 'scattergl',
        mode: 'markers',
        x: xs,
        y: ys,
        text: ids.map((v) => String(v ?? '')),
        marker: { color: colors, size: 6 },
        hovertemplate: `%{text}<br>${roles.effect_size}: %{x:.3f}<extra></extra>`,
      },
    ],
    layout: {
      ...baseLayout(),
      showlegend: false,
      xaxis: { title: { text: roles.effect_size }, zeroline: true },
      yaxis: { title: { text: `-log10(${roles.significance})` } },
    },
  };
}

function buildManhattan(fixture: ParsedFixture, roles: Record<string, string>): PreviewResult {
  const { rows } = fixture;
  const chr = col(rows, roles.chr).map((v) => String(v ?? ''));
  const pos = numCol(rows, roles.pos);
  const score = numCol(rows, roles.score);
  // order by chr then pos, assign a cumulative x so chromosomes tile left→right.
  const order = chr.map((_, i) => i).sort((a, b) => (chr[a] < chr[b] ? -1 : chr[a] > chr[b] ? 1 : pos[a] - pos[b]));
  const chrList = [...new Set(order.map((i) => chr[i]))];
  const colorFor = new Map(chrList.map((c, i) => [c, TAB10_PALETTE[i % TAB10_PALETTE.length]]));
  const x = order.map((_, k) => k);
  const y = order.map((i) => score[i]);
  const c = order.map((i) => colorFor.get(chr[i]));
  const text = order.map((i) => `${chr[i]}:${pos[i]}`);
  return {
    data: [{ type: 'scattergl', mode: 'markers', x, y, text, marker: { color: c, size: 5 }, hovertemplate: '%{text}<br>score %{y}<extra></extra>' }],
    layout: { ...baseLayout(), showlegend: false, xaxis: { title: { text: 'position (ordered)' }, showticklabels: false }, yaxis: { title: { text: roles.score } } },
  };
}

function buildScatterRoles(
  fixture: ParsedFixture,
  roles: Record<string, string>,
  xRole: string,
  yRole: string,
  categoryRole?: string,
): PreviewResult {
  const { rows } = fixture;
  const xs = isNumericColumn(fixture, roles[xRole]) ? numCol(rows, roles[xRole]) : col(rows, roles[xRole]);
  const ys = numCol(rows, roles[yRole]);
  const cat = categoryRole && roles[categoryRole] ? col(rows, roles[categoryRole]).map((v) => String(v ?? '—')) : null;
  const data: Record<string, unknown>[] = [];
  if (cat) {
    const groups = [...new Set(cat)];
    groups.forEach((g, gi) => {
      const idx = cat.map((v, i) => (v === g ? i : -1)).filter((i) => i >= 0);
      data.push({
        type: 'scattergl',
        mode: 'markers',
        x: idx.map((i) => xs[i]),
        y: idx.map((i) => ys[i]),
        name: g,
        marker: { color: TAB10_PALETTE[gi % TAB10_PALETTE.length], size: 7 },
      });
    });
  } else {
    data.push({ type: 'scattergl', mode: 'markers', x: xs, y: ys, marker: { size: 7 } });
  }
  return {
    data,
    layout: { ...baseLayout(), showlegend: !!cat, xaxis: { title: { text: roles[xRole] } }, yaxis: { title: { text: roles[yRole] } } },
  };
}

function buildQQ(fixture: ParsedFixture, roles: Record<string, string>): PreviewResult {
  // Observed -log10(p) vs expected under uniform null.
  const { rows } = fixture;
  const p = numCol(rows, roles.p_value).filter((v) => v > 0 && v <= 1);
  const obs = p.map((v) => -Math.log10(v)).sort((a, b) => a - b);
  const n = obs.length;
  const exp = obs.map((_, i) => -Math.log10((n - i) / (n + 1)));
  const lim = Math.max(...obs, ...exp, 1);
  return {
    data: [
      { type: 'scattergl', mode: 'markers', x: exp, y: obs, marker: { size: 5, color: '#1c7ed6' }, name: 'observed' },
      { type: 'scatter', mode: 'lines', x: [0, lim], y: [0, lim], line: { dash: 'dot', color: 'gray' }, name: 'null' },
    ],
    layout: { ...baseLayout(), showlegend: false, xaxis: { title: { text: 'expected -log10(p)' } }, yaxis: { title: { text: 'observed -log10(p)' } } },
  };
}

function buildAdvancedViz(fixture: ParsedFixture, render: AdvancedVizRender, heavy: boolean): PreviewResult {
  if (heavy) {
    return { unavailable: true, reason: 'Heavy visualization — preview only available in depictio.' };
  }
  const roles = render.roles;
  switch (render.kind) {
    case 'volcano':
      return buildVolcano(fixture, roles);
    case 'manhattan':
      return buildManhattan(fixture, roles);
    case 'ma':
      return buildScatterRoles(fixture, roles, 'avg_log_intensity', 'log2_fold_change');
    case 'lollipop':
      return buildScatterRoles(fixture, roles, 'position', 'feature_id', 'category');
    case 'dot_plot':
      return buildScatterRoles(fixture, roles, 'gene', 'cluster', 'cluster');
    case 'qq':
      return buildQQ(fixture, roles);
    default:
      return { unavailable: true, reason: `No client preview for "${render.kind}" — verify in depictio.` };
  }
}

// ── entry point ─────────────────────────────────────────────────────────────

export function buildPreview(
  fixture: ParsedFixture,
  render: RenderSpec,
  isHeavy: (kind: string) => boolean,
): PreviewResult {
  if (render.component === 'figure') return buildBasicFigure(fixture, render);
  if (render.component === 'advanced_viz') return buildAdvancedViz(fixture, render, isHeavy(render.kind));
  // card + table are rendered by dedicated components, not Plotly.
  return { unavailable: true, reason: 'Rendered without Plotly.' };
}
