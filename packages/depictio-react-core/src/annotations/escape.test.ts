import { describe, expect, it } from 'vitest';

import { ANNOTATE_UI_ATTR, FOREIGN_OVERLAY_SELECTOR, isAnnotateEscape } from './escape';

/** Minimal element stub: a chain of ancestors, each matching some selectors. */
interface Node {
  matches: string[];
  parent: Node | null;
}
function el(matches: string[], parent: Node | null = null): Node & {
  closest: (s: string) => unknown;
  contains: (o: unknown) => boolean;
} {
  const node: Node = { matches, parent };
  const wrap = (n: Node | null): any =>
    n && {
      ...n,
      closest(selector: string) {
        const wanted = selector.split(',').map((x) => x.trim());
        for (let cur: Node | null = n; cur; cur = cur.parent) {
          if (cur.matches.some((m) => wanted.includes(m))) return wrap(cur);
        }
        return null;
      },
      contains(other: any) {
        for (let cur: Node | null = other?.__node ?? null; cur; cur = cur.parent) {
          if (cur === n) return true;
        }
        return false;
      },
      __node: n,
    };
  return wrap(node);
}

const esc = (target: unknown, defaultPrevented = false) => ({ key: 'Escape', defaultPrevented, target });

describe('isAnnotateEscape', () => {
  const body = el([]);
  it('only reacts to unhandled Escape', () => {
    expect(isAnnotateEscape({ key: 'Enter', defaultPrevented: false, target: body })).toBe(false);
    expect(isAnnotateEscape(esc(body, true))).toBe(false);
    expect(isAnnotateEscape(esc(body))).toBe(true);
    expect(isAnnotateEscape(esc(null))).toBe(true);
  });
  it('ignores Escape inside another open overlay', () => {
    const menu = el(['.mantine-Menu-dropdown']);
    const item = el(['button'], (menu as any).__node);
    expect(isAnnotateEscape(esc(item))).toBe(false);
    const dialog = el(['[role="dialog"]']);
    expect(isAnnotateEscape(esc(dialog))).toBe(false);
  });
  it('handles Escape in the annotate toolbar or its label popover', () => {
    const popover = el([`[${ANNOTATE_UI_ATTR}]`, '.mantine-Popover-dropdown', '[role="dialog"]']);
    const input = el(['input'], (popover as any).__node);
    expect(isAnnotateEscape(esc(input))).toBe(true);
  });
  it('handles Escape in the overlay that hosts the annotated component', () => {
    const modal = el(['.mantine-Modal-content']);
    const plot = el(['div'], (modal as any).__node);
    expect(isAnnotateEscape(esc(plot), plot)).toBe(true);
    expect(isAnnotateEscape(esc(plot), body)).toBe(false);
  });
  it('lists the Mantine overlays', () => {
    expect(FOREIGN_OVERLAY_SELECTOR).toContain('.mantine-Popover-dropdown');
    expect(FOREIGN_OVERLAY_SELECTOR).toContain('[role="dialog"]');
  });
});
