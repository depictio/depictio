/**
 * Shared dark-mode helpers for Plotly-based advanced-viz renderers.
 *
 * Strategy: every renderer builds its layout / traces however it wants, then
 * passes them through `applyLayoutTheme(...)` / `applyDataTheme(...)` at the
 * `<Plot>` prop level. The helpers explicitly retint every axis, scene
 * subaxis, legend, annotation, coloraxis, and trace colorbar so we don't
 * depend on Plotly's (unreliable) template-vs-layout precedence rules.
 *
 * All colour values come from the Mantine theme — no hardcoded literals.
 */
import type { MantineTheme } from '@mantine/core';

export interface PlotlyThemeColors {
  textColor: string;
  gridColor: string;
  zeroLineColor: string;
  bgColor: string;
}

export function plotlyThemeColors(isDark: boolean, theme: MantineTheme): PlotlyThemeColors {
  return {
    textColor: isDark ? theme.colors.gray[2] : theme.colors.gray[8],
    gridColor: isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)',
    zeroLineColor: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.35)',
    bgColor: 'rgba(0,0,0,0)',
  };
}

/** Baseline Plotly layout fragment to spread into a renderer's layout when it
 *  wants to set bg / template / font up-front (kept for backwards-compat with
 *  renderers that prefer the spread style; the post-pass below will overwrite
 *  whatever is set here so the two approaches converge). */
export function plotlyThemeFragment(isDark: boolean, theme: MantineTheme) {
  const c = plotlyThemeColors(isDark, theme);
  return {
    template: isDark ? 'plotly_dark' : 'plotly_white',
    plot_bgcolor: c.bgColor,
    paper_bgcolor: c.bgColor,
    font: { color: c.textColor },
  };
}

/** Per-axis theme overrides — same intent as the post-pass below but as an
 *  inline spread for renderers that build axes explicitly. */
export function plotlyAxisOverrides(isDark: boolean, theme: MantineTheme) {
  const c = plotlyThemeColors(isDark, theme);
  return {
    color: c.textColor,
    gridcolor: c.gridColor,
    zerolinecolor: c.zeroLineColor,
    linecolor: c.gridColor,
    tickfont: { color: c.textColor },
    title: { font: { color: c.textColor } },
  };
}

function retintAxis(axis: unknown, c: PlotlyThemeColors): Record<string, unknown> {
  const a = { ...((axis || {}) as Record<string, unknown>) };
  a.color = c.textColor;
  a.gridcolor = c.gridColor;
  a.zerolinecolor = c.zeroLineColor;
  a.linecolor = c.gridColor;
  const tickfont = (a.tickfont || {}) as Record<string, unknown>;
  a.tickfont = { ...tickfont, color: c.textColor };
  if (a.title != null) {
    if (typeof a.title === 'string') {
      a.title = { text: a.title, font: { color: c.textColor } };
    } else {
      const t = a.title as Record<string, unknown>;
      const tf = (t.font || {}) as Record<string, unknown>;
      a.title = { ...t, font: { ...tf, color: c.textColor } };
    }
  }
  return a;
}

function retintColorbar(holder: Record<string, unknown>, c: PlotlyThemeColors): Record<string, unknown> {
  const cb = ((holder.colorbar || {}) as Record<string, unknown>) ?? {};
  const tickfont = (cb.tickfont || {}) as Record<string, unknown>;
  const next: Record<string, unknown> = { ...cb, tickfont: { ...tickfont, color: c.textColor } };
  if (cb.title != null) {
    if (typeof cb.title === 'string') {
      next.title = { text: cb.title, font: { color: c.textColor } };
    } else {
      const t = cb.title as Record<string, unknown>;
      const tf = (t.font || {}) as Record<string, unknown>;
      next.title = { ...t, font: { ...tf, color: c.textColor } };
    }
  }
  return { ...holder, colorbar: next };
}

/** Post-pass over a Plotly figure's `layout` dict — retints every axis,
 *  scene subaxis, legend, annotation, coloraxis colorbar, and the global
 *  font so theme switching is reliable regardless of Plotly's template /
 *  layout merge order. Idempotent + safe to call on already-themed layouts. */
export function applyLayoutTheme(
  layout: Record<string, unknown> | undefined,
  isDark: boolean,
  theme: MantineTheme,
): Record<string, unknown> {
  const c = plotlyThemeColors(isDark, theme);
  const out: Record<string, unknown> = { ...(layout || {}) };

  for (const key of Object.keys(out)) {
    if (
      key.startsWith('xaxis') ||
      key.startsWith('yaxis') ||
      key.startsWith('zaxis')
    ) {
      out[key] = retintAxis(out[key], c);
    } else if (key === 'scene' || key.startsWith('scene')) {
      const scene = { ...((out[key] || {}) as Record<string, unknown>) };
      for (const sk of ['xaxis', 'yaxis', 'zaxis']) {
        if (scene[sk] != null) scene[sk] = retintAxis(scene[sk], c);
      }
      scene.bgcolor = c.bgColor;
      out[key] = scene;
    } else if (key === 'coloraxis' && typeof out[key] === 'object' && out[key] != null) {
      out[key] = retintColorbar(out[key] as Record<string, unknown>, c);
    } else if (key === 'annotations' && Array.isArray(out[key])) {
      out[key] = (out[key] as Array<Record<string, unknown>>).map((a) => {
        const font = (a.font || {}) as Record<string, unknown>;
        // Only retint annotations that didn't pick an explicit colour — leave
        // colour-coded ones (tier badges, signed-effect labels) untouched.
        if (font.color != null) return a;
        return { ...a, font: { ...font, color: c.textColor } };
      });
    } else if (key === 'legend' && typeof out[key] === 'object' && out[key] != null) {
      const legend = out[key] as Record<string, unknown>;
      const font = (legend.font || {}) as Record<string, unknown>;
      const titleObj = (legend.title || {}) as Record<string, unknown>;
      const titleFont = (titleObj.font || {}) as Record<string, unknown>;
      out[key] = {
        ...legend,
        font: { ...font, color: c.textColor },
        bgcolor: c.bgColor,
        title:
          legend.title != null
            ? { ...titleObj, font: { ...titleFont, color: c.textColor } }
            : legend.title,
      };
    } else if (key === 'title' && typeof out[key] === 'object' && out[key] != null) {
      const t = out[key] as Record<string, unknown>;
      const tf = (t.font || {}) as Record<string, unknown>;
      out[key] = { ...t, font: { ...tf, color: c.textColor } };
    }
  }

  // Theme-level overrides win — put them AFTER the per-key pass so explicit
  // theme values aren't clobbered by server-baked defaults from the input.
  return {
    ...out,
    template: isDark ? 'plotly_dark' : 'plotly_white',
    plot_bgcolor: c.bgColor,
    paper_bgcolor: c.bgColor,
    font: { ...((out.font || {}) as Record<string, unknown>), color: c.textColor },
  };
}

/** Trace-level retint — covers per-trace `colorbar` (heatmap, contour),
 *  `marker.colorbar` (scatter colour scales), and `textfont` (text-mode
 *  scatter labels). Used for server-built figures whose data array bakes
 *  in light-mode text colours that Plotly's template won't override. */
export function applyDataTheme(
  data: unknown[] | undefined,
  isDark: boolean,
  theme: MantineTheme,
): unknown[] {
  const c = plotlyThemeColors(isDark, theme);
  return (data || []).map((trace) => {
    if (!trace || typeof trace !== 'object') return trace;
    const t = { ...(trace as Record<string, unknown>) };
    if (t.colorbar != null) {
      const retinted = retintColorbar({ colorbar: t.colorbar }, c) as {
        colorbar: Record<string, unknown>;
      };
      t.colorbar = retinted.colorbar;
    }
    if (t.marker != null && typeof t.marker === 'object') {
      const marker = { ...(t.marker as Record<string, unknown>) };
      if (marker.colorbar != null) {
        const retinted = retintColorbar({ colorbar: marker.colorbar }, c) as {
          colorbar: Record<string, unknown>;
        };
        marker.colorbar = retinted.colorbar;
      }
      t.marker = marker;
    }
    if (t.textfont != null && typeof t.textfont === 'object') {
      const tf = t.textfont as Record<string, unknown>;
      // Only retint when the trace didn't pick a colour itself — preserves
      // tier-coloured labels (volcano UP/DN, manhattan HIT/MISS).
      if (tf.color == null) t.textfont = { ...tf, color: c.textColor };
    }
    return t;
  });
}

/** Backwards-compat alias — older renderers import `applyAxisThemeOverrides`. */
export const applyAxisThemeOverrides = applyLayoutTheme;
