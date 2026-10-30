import { getChromeStyle } from './chromeStyle';
import type { ChromeStyle } from './chromeStyle';

type Obj = Record<string, unknown>;

const isObj = (v: unknown): v is Obj => typeof v === 'object' && v !== null && !Array.isArray(v);

function deepMerge(base: unknown, patch: Obj): Obj {
  const out: Obj = { ...(isObj(base) ? base : {}) };
  for (const [k, v] of Object.entries(patch)) {
    out[k] = isObj(v) && isObj(out[k]) ? deepMerge(out[k], v) : v;
  }
  return out;
}

/** `xaxis`, `xaxis2`, ... : the axis keys a patch's `xaxis` / `yaxis` covers. */
function axisKeys(layout: Obj, axis: 'xaxis' | 'yaxis'): string[] {
  const keys = Object.keys(layout).filter(
    (k) => k === axis || (k.startsWith(axis) && /^\d+$/.test(k.slice(axis.length))),
  );
  return keys.includes(axis) ? keys : [axis, ...keys];
}

/**
 * Merges `patch` into `layout`. `over` decides who wins a key both set: the
 * patch (true) or the layout (false). A patch's `xaxis` / `yaxis` apply to
 * every x / y axis of the figure (facets included).
 */
function mergeLayout(layout: Obj, patch: Obj, over: boolean): Obj {
  const out: Obj = { ...layout };
  const merge = (cur: unknown, v: unknown): unknown => {
    if (!isObj(v)) return over || cur === undefined ? v : cur;
    if (!isObj(cur)) return over || cur === undefined ? v : cur;
    return over ? deepMerge(cur, v) : deepMerge(v, cur);
  };
  for (const [k, v] of Object.entries(patch)) {
    if ((k === 'xaxis' || k === 'yaxis') && isObj(v)) {
      for (const key of axisKeys(out, k)) out[key] = merge(out[key], v);
    } else {
      out[k] = merge(out[k], v);
    }
  }
  return out;
}

/** What an axis that draws its own line keeps from the figure. */
const OWN_AXIS_KEYS = ['showline', 'linewidth', 'linecolor', 'mirror', 'showgrid', 'ticks'];

/**
 * Hands back the axis furniture of every axis the figure draws a line on
 * (`showline: true`): a style patch that drops axis lines (Glass) would
 * otherwise turn a figure's explicit "axis lines" look into a no-op. Axes
 * that say nothing of their line keep the style's look.
 */
function keepOwnAxisLines(out: Obj, layout: Obj): Obj {
  for (const key of Object.keys(layout)) {
    if (!/^[xy]axis\d*$/.test(key)) continue;
    const own = layout[key];
    if (!isObj(own) || own.showline !== true || !isObj(out[key])) continue;
    const axis: Obj = { ...(out[key] as Obj) };
    for (const k of OWN_AXIS_KEYS) if (k in own) axis[k] = own[k];
    out[key] = axis;
  }
  return out;
}

/**
 * Applies the active chrome style's Plotly theme to a figure layout: its
 * `plotlyDefaults` fill what the figure leaves unset, then its `plotly` patch
 * overrides, except on the axes the figure draws its own lines on
 * (`keepOwnAxisLines`). The layout comes back untouched when the style has
 * neither.
 */
export function applyChromePlotly(
  layout: Obj,
  scheme: 'light' | 'dark',
  style: ChromeStyle = getChromeStyle(),
): Obj {
  const defaults = style.plotlyDefaults?.(scheme, layout);
  const patch = style.plotly?.(scheme);
  let out = layout;
  if (defaults) out = mergeLayout(out, defaults, false);
  if (patch) out = keepOwnAxisLines(mergeLayout(out, patch, true), layout);
  return out;
}
