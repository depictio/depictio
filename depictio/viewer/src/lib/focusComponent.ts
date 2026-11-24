import React from 'react';

/**
 * Scroll a dashboard component into view and pulse a highlight on it.
 *
 * Targets the `.react-grid-item` ancestor of `[data-component-id]` — the
 * absolutely-positioned grid cell — rather than the inner content wrapper, and
 * falls back to the element itself for components outside the grid (filter
 * panel rows, top panel). Waits two animation frames first so a component that
 * was just placed has been positioned by react-grid-layout.
 *
 * Returns false when no such component is on the page (e.g. it was removed).
 */
export function focusComponent(
  componentIndex: string,
  opts: { flashClass?: string; durationMs?: number; defer?: boolean } = {},
): boolean {
  const { flashClass = 'depictio-duplicate-flash', durationMs = 1500, defer = true } = opts;
  const selector = `[data-component-id="${CSS.escape(componentIndex)}"]`;
  if (!document.querySelector(selector)) return false;
  const run = () => {
    const inner = document.querySelector(selector) as HTMLElement | null;
    const el = (inner?.closest('.react-grid-item') as HTMLElement | null) || inner;
    if (!el) return;
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    // Restart the animation when the same component is focused twice in a row.
    el.classList.remove(flashClass);
    void el.offsetWidth;
    el.classList.add(flashClass);
    window.setTimeout(() => el.classList.remove(flashClass), durationMs);
  };
  if (defer) requestAnimationFrame(() => requestAnimationFrame(run));
  else run();
  return true;
}

/** The component a link asks the page to show (`?focus=<component id>`, the
 *  report editor's "Show in the dashboard"): scrolled to and pulsed once it
 *  is on the page, then dropped from the address so a reload does not repeat
 *  it. Gives up after `timeoutMs` (a component of another tab, or removed). */
export function useFocusFromUrl(ready: boolean, timeoutMs = 15000): void {
  React.useEffect(() => {
    if (!ready) return;
    const url = new URL(window.location.href);
    const target = url.searchParams.get('focus');
    if (!target) return;
    const started = Date.now();
    let timer = 0;
    const done = () => {
      url.searchParams.delete('focus');
      window.history.replaceState(window.history.state, '', url.toString());
    };
    const attempt = () => {
      if (focusComponent(target, { durationMs: 2400 })) return done();
      if (Date.now() - started > timeoutMs) return done();
      timer = window.setTimeout(attempt, 300);
    };
    attempt();
    return () => window.clearTimeout(timer);
  }, [ready]);
}
