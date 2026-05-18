import { useCallback, useEffect, useRef, useState } from 'react';
import type { WalkthroughDefinition, WalkthroughState } from './types';

const STORAGE_PREFIX = 'depictio.walkthrough.';
/** Custom event used by the user-menu "Take the tour" item to restart a
 *  walkthrough from anywhere in the app without lifting state. */
export const RESTART_EVENT = 'depictio:walkthrough:restart';

function storageKey(id: string): string {
  return `${STORAGE_PREFIX}${id}`;
}

function readState(def: WalkthroughDefinition): WalkthroughState {
  try {
    const raw = localStorage.getItem(storageKey(def.id));
    if (!raw) return { status: 'pending', step: 0, version: def.version };
    const parsed = JSON.parse(raw) as Partial<WalkthroughState>;
    if (parsed.version !== def.version) {
      return { status: 'pending', step: 0, version: def.version };
    }
    return {
      status: (parsed.status as WalkthroughState['status']) ?? 'pending',
      step: typeof parsed.step === 'number' ? parsed.step : 0,
      version: def.version,
    };
  } catch {
    return { status: 'pending', step: 0, version: def.version };
  }
}

function writeState(def: WalkthroughDefinition, next: WalkthroughState): void {
  try {
    localStorage.setItem(storageKey(def.id), JSON.stringify(next));
  } catch {
    // ignore quota / private mode
  }
}

export interface UseWalkthroughResult {
  state: WalkthroughState;
  /** Index of the step that should be visible right now on this route. `-1`
   *  means no step matches (engine renders nothing — waiting for navigation
   *  or fully completed). */
  visibleStep: number;
  next: () => void;
  back: () => void;
  skip: () => void;
  finish: () => void;
  restart: () => void;
}

/** Drives a single walkthrough. The hook is route-aware: it advances the
 *  *stored* step counter on Next, but only renders a step whose `route`
 *  matches the current pathname.
 */
export function useWalkthrough(
  def: WalkthroughDefinition,
  /** Whether this walkthrough is eligible to run at all (mode/auth gating). */
  enabled: boolean,
  pathname: string,
): UseWalkthroughResult {
  const [state, setState] = useState<WalkthroughState>(() => readState(def));

  const update = useCallback(
    (patch: Partial<WalkthroughState>) => {
      setState((prev) => {
        const merged: WalkthroughState = { ...prev, ...patch, version: def.version };
        writeState(def, merged);
        return merged;
      });
    },
    [def],
  );

  useEffect(() => {
    const onRestart = (e: Event) => {
      const detail = (e as CustomEvent<{ id?: string }>).detail;
      if (detail?.id && detail.id !== def.id) return;
      update({ status: 'in-progress', step: 0 });
    };
    window.addEventListener(RESTART_EVENT, onRestart);
    return () => window.removeEventListener(RESTART_EVENT, onRestart);
  }, [def.id, update]);

  // First-visit auto-start: flip pending → in-progress so the engine renders.
  useEffect(() => {
    if (enabled && state.status === 'pending') {
      update({ status: 'in-progress', step: 0 });
    }
  }, [enabled, state.status, update]);

  // Auto-advance on real pathname changes only. When the user clicks a
  // target with `awaitClick: true` (or hits a step with `navigateTo`), the
  // page changes but the stored step counter doesn't always advance to
  // exactly the right step — we scan forward from the current step for the
  // first step whose route guard matches the new pathname.
  //
  // The pathname-changed gate is load-bearing: without it, calling `next()`
  // synchronously before `window.location.href = …` triggers a re-render of
  // this effect with the new `state.step` but the *old* pathname, and the
  // scan-forward leapfrogs to whatever later step's route happens to match
  // the page we're navigating *away* from. With the ref-based guard, the
  // effect only does work when the route actually changed.
  //
  // Route-less steps (welcome, done) are skipped as landing targets — they're
  // only reachable by explicit Next clicks. Otherwise `matchesRoute(undefined,
  // anyPath)` would happily return true and the scan would land on "done".
  const lastSeenPathRef = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (!enabled || state.status !== 'in-progress') return;
    if (state.step >= def.steps.length) return;
    const isPathChange = lastSeenPathRef.current !== pathname;
    lastSeenPathRef.current = pathname;
    if (!isPathChange) return;
    const current = def.steps[state.step];
    if (matchesRoute(current.route, pathname)) return;
    for (let i = state.step + 1; i < def.steps.length; i++) {
      const candidate = def.steps[i];
      if (!candidate.route) continue;
      if (matchesRoute(candidate.route, pathname)) {
        update({ step: i });
        return;
      }
    }
  }, [enabled, pathname, state.status, state.step, def, update]);

  const stepCount = def.steps.length;

  const next = useCallback(() => {
    setState((prev) => {
      const nextIdx = prev.step + 1;
      const merged: WalkthroughState =
        nextIdx >= stepCount
          ? { ...prev, status: 'completed', step: stepCount, version: def.version }
          : { ...prev, step: nextIdx, status: 'in-progress', version: def.version };
      writeState(def, merged);
      return merged;
    });
  }, [def, stepCount]);

  const back = useCallback(() => {
    setState((prev) => {
      const merged: WalkthroughState = {
        ...prev,
        step: Math.max(0, prev.step - 1),
        status: 'in-progress',
        version: def.version,
      };
      writeState(def, merged);
      return merged;
    });
  }, [def]);

  const skip = useCallback(
    () => update({ status: 'skipped', step: stepCount }),
    [stepCount, update],
  );
  const finish = useCallback(
    () => update({ status: 'completed', step: stepCount }),
    [stepCount, update],
  );
  const restart = useCallback(() => update({ status: 'in-progress', step: 0 }), [update]);

  // Decide which step to render right now. Only "in-progress" walkthroughs
  // render anything. If the stored step has a route guard that doesn't match
  // the current path, the popover hides — the user is mid-navigation.
  const visibleStep =
    enabled && state.status === 'in-progress' && state.step < stepCount
      ? matchesRoute(def.steps[state.step].route, pathname)
        ? state.step
        : -1
      : -1;

  return { state, visibleStep, next, back, skip, finish, restart };
}

function matchesRoute(route: RegExp | undefined, pathname: string): boolean {
  if (!route) return true;
  return route.test(pathname);
}

/** Fires a restart event for the walkthrough with the given id. Called by
 *  the ProfileBadge menu item. Without an id, restarts whichever walkthrough
 *  the host currently exposes. */
export function dispatchWalkthroughRestart(id?: 'public' | 'builder'): void {
  window.dispatchEvent(new CustomEvent(RESTART_EVENT, { detail: { id } }));
}
