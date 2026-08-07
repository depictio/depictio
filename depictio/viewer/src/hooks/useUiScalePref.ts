import { useCallback, useEffect, useState } from 'react';
import { UI_SCALE_DEFAULT, UI_SCALE_STEPS } from 'depictio-react-core';

/**
 * Dashboard-wide font-size preference (issue #854), persisted per browser like
 * the dark-mode toggle. Two independent consumers read it — the Header control
 * and ThemeRoot (which rebuilds the Mantine theme with `scale`) — so writes go
 * through a module-level subscriber list to keep both in sync within the tab.
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
