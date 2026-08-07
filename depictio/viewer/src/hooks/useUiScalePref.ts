import { useCallback, useEffect, useMemo, useState, type CSSProperties } from 'react';
import { DEFAULT_THEME } from '@mantine/core';
import { UI_SCALE_DEFAULT, UI_SCALE_STEPS } from 'depictio-react-core';

/**
 * Dashboard font-size preference (issue #854), persisted per browser like the
 * dark-mode toggle. It scales dashboard content only (figures, tables, cards,
 * interactive tiles) — never the app chrome (header, sidebar, drawers).
 * Several independent consumers read it — the SettingsDrawer control, the
 * content containers (via useContentScaleStyle) and UiScaleContext — so writes
 * go through a module-level subscriber list to keep them in sync within the tab.
 */

const STORAGE_KEY = 'depictio-ui-scale';

type Listener = (scale: number) => void;
const listeners = new Set<Listener>();

function clampToStep(value: number): number {
  // Snap to the nearest allowed step so a hand-edited or stale stored value
  // can't produce an off-scale UI.
  let best: number = UI_SCALE_DEFAULT;
  let bestDist = Infinity;
  for (const step of UI_SCALE_STEPS) {
    const dist = Math.abs(step - value);
    if (dist < bestDist) {
      best = step;
      bestDist = dist;
    }
  }
  return best;
}

export function readStoredUiScale(): number {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return UI_SCALE_DEFAULT;
    const parsed = Number(raw);
    if (!Number.isFinite(parsed)) return UI_SCALE_DEFAULT;
    return clampToStep(parsed);
  } catch {
    return UI_SCALE_DEFAULT;
  }
}

function writeStoredUiScale(scale: number): void {
  try {
    localStorage.setItem(STORAGE_KEY, String(scale));
  } catch {
    // ignore quota / disabled storage
  }
}

function broadcast(scale: number): void {
  writeStoredUiScale(scale);
  listeners.forEach((fn) => fn(scale));
  // Plotly and AG Grid size to their containers; a scale change moves text
  // metrics without a window resize, so fire the established reflow signal
  // (same idiom as the panel toggles — see DashboardGrid's resize dispatch).
  window.dispatchEvent(new Event('resize'));
}

export function useUiScalePref() {
  const [scale, setScale] = useState<number>(readStoredUiScale);

  useEffect(() => {
    const listener: Listener = (next) => setScale(next);
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  }, []);

  const stepIndex = UI_SCALE_STEPS.indexOf(scale as (typeof UI_SCALE_STEPS)[number]);
  const canIncrease = stepIndex < UI_SCALE_STEPS.length - 1;
  const canDecrease = stepIndex > 0;

  const increase = useCallback(() => {
    const idx = UI_SCALE_STEPS.indexOf(readStoredUiScale() as (typeof UI_SCALE_STEPS)[number]);
    if (idx < UI_SCALE_STEPS.length - 1) broadcast(UI_SCALE_STEPS[idx + 1]);
  }, []);

  const decrease = useCallback(() => {
    const idx = UI_SCALE_STEPS.indexOf(readStoredUiScale() as (typeof UI_SCALE_STEPS)[number]);
    if (idx > 0) broadcast(UI_SCALE_STEPS[idx - 1]);
  }, []);

  const reset = useCallback(() => {
    broadcast(UI_SCALE_DEFAULT);
  }, []);

  return { scale, increase, decrease, reset, canIncrease, canDecrease };
}

/**
 * CSS custom properties applying the font-size preference to a dashboard
 * content container (and nothing outside it).
 *
 * Two mechanisms compose:
 * - `--mantine-scale` cascades into the `calc(<rem> * var(--mantine-scale))`
 *   expressions Mantine emits per component (inline `rem()` conversions,
 *   component-level size vars), which resolve at the component element and so
 *   pick up the container override.
 * - The font-size / heading tokens are *precomputed* at `:root` (a custom
 *   property substitutes `var(--mantine-scale)` where it is declared, not
 *   where it is consumed), so they must be re-declared here with the scale
 *   baked in for `size="sm"` texts and `<Title>`s to follow.
 *
 * Returns `undefined` at 100% so the default renders untouched.
 */
export function useContentScaleStyle(): CSSProperties | undefined {
  const { scale } = useUiScalePref();
  return useMemo(() => {
    if (scale === 1) return undefined;
    const vars: Record<string, string> = { '--mantine-scale': String(scale) };
    for (const [size, value] of Object.entries(DEFAULT_THEME.fontSizes)) {
      vars[`--mantine-font-size-${size}`] = `calc(${value} * ${scale})`;
    }
    for (const [heading, spec] of Object.entries(DEFAULT_THEME.headings.sizes)) {
      vars[`--mantine-${heading}-font-size`] = `calc(${spec.fontSize} * ${scale})`;
    }
    return vars as CSSProperties;
  }, [scale]);
}
