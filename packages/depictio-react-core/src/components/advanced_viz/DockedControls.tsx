import React, { useLayoutEffect, useRef, useState } from 'react';
import { UnstyledButton } from '@mantine/core';
import { Icon } from '@iconify/react';

import { DOCK_ESSENTIALS, pickEssentials, type DockSide } from './controlsDock';

/** Whether a control does something now: it has an input, not every input
 *  is disabled, and a panel of toggles has at least one on. */
function isLive(item: HTMLElement): boolean {
  const inputs = Array.from(item.querySelectorAll('input, textarea')) as HTMLInputElement[];
  const usable = inputs.filter((i) => i.type !== 'hidden' || i.closest('.mantine-Slider-root'));
  if (usable.length === 0) return false;
  if (usable.every((i) => i.disabled)) return false;
  const toggles = usable.filter((i) => i.type === 'checkbox');
  if (toggles.length === usable.length && toggles.every((i) => !i.checked)) return false;
  return true;
}

/** The controls of one item of the panel: itself, or, for a titled group
 *  (`VizControlGroup`: a divider over a grid), the controls in its grid. A
 *  group counts as the controls it holds, so a panel of three groups no
 *  longer shows every control of all three before "More options". */
function controlsOf(item: HTMLElement): HTMLElement[] {
  const stack = item.firstElementChild as HTMLElement | null;
  const isGroup =
    stack?.classList.contains('mantine-Stack-root') &&
    stack.firstElementChild?.classList.contains('mantine-Divider-root');
  if (isGroup) {
    const grid = stack!.lastElementChild as HTMLElement | null;
    return grid ? (Array.from(grid.children) as HTMLElement[]) : [item];
  }
  // A renderer that hands every control over in one bare stack (the tree's
  // summary): its children are the controls. Two of them taking input tells
  // it from one control laid out as a stack (a label over a switch).
  if (item.classList.contains('mantine-Stack-root')) {
    const kids = Array.from(item.children) as HTMLElement[];
    if (kids.filter((k) => k.querySelector('input, textarea')).length >= 2) return kids;
  }
  return [item];
}

/**
 * A renderer's controls docked beside or above its plot (see controlsDock.ts),
 * showing a few and folding the rest under "More options": a panel listing all
 * of a sankey's dozen settings lost the reader before the plot did. The pick
 * is made when the panel mounts or its set of controls changes, not on every
 * change of value, so a control never jumps between the two while it is used.
 *
 * Titled, so the panel reads as the plot's settings rather than as part of the
 * figure. `lead` (a view switch) comes first and is never folded.
 */
const DockedControls: React.FC<{
  controls: React.ReactNode;
  side: DockSide;
  lead?: React.ReactNode;
}> = ({ controls, side, lead }) => {
  const ref = useRef<HTMLDivElement | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [extra, setExtra] = useState(0);

  useLayoutEffect(() => {
    const root = ref.current?.firstElementChild as HTMLElement | null;
    if (!root) return;
    let count = -1;
    const apply = () => {
      const items = Array.from(root.children) as HTMLElement[];
      const groups = items.map(controlsOf);
      const units = groups.flat();
      if (units.length === count) return;
      count = units.length;
      const keep = pickEssentials(units.map(isLive));
      const mark = (el: HTMLElement, extra: boolean) =>
        extra ? el.setAttribute('data-dock-extra', '') : el.removeAttribute('data-dock-extra');
      units.forEach((u, i) => mark(u, !keep[i]));
      // A group none of whose controls made the cut folds whole, its title
      // with it; one that keeps any stays, showing only those.
      items.forEach((it, i) => {
        if (groups[i][0] !== it) mark(it, groups[i].every((u) => u.hasAttribute('data-dock-extra')));
      });
      setExtra(keep.filter((k) => !k).length);
    };
    apply();
    // Subtree: a group's controls can come and go without the panel's own
    // children changing. Only the count of controls re-runs the pick.
    const mo = new MutationObserver(apply);
    mo.observe(root, { childList: true, subtree: true });
    return () => mo.disconnect();
  }, [controls]);

  // Above the plot the toggle shares the title's line, which the row of
  // controls leaves empty; in the column it follows the controls it unfolds.
  const more =
    extra > 0 ? (
      <UnstyledButton
        className="dpx-viz-dock__more"
        onClick={() => setExpanded((e) => !e)}
        aria-expanded={expanded}
        data-testid="viz-controls-more"
      >
        <Icon icon={expanded ? 'tabler:chevron-up' : 'tabler:chevron-down'} width={14} height={14} />
        {expanded ? 'Fewer options' : `More options (${extra})`}
      </UnstyledButton>
    ) : null;

  return (
    <div
      className={`dpx-viz-dock dpx-viz-dock--${side}${expanded ? ' is-expanded' : ''}`}
      data-testid="viz-controls-dock"
    >
      <div className="dpx-viz-dock__head">
        <span className="dpx-viz-dock__title">
          <Icon icon="tabler:adjustments-horizontal" width={13} height={13} />
          Controls
        </span>
        {side === 'top' ? more : null}
      </div>
      <div className="dpx-viz-dock__body">
        {lead ? <div className="dpx-viz-dock__lead">{lead}</div> : null}
        <div ref={ref} className="dpx-viz-dock__controls">
          {controls}
        </div>
      </div>
      {side === 'right' ? more : null}
    </div>
  );
};

export { DOCK_ESSENTIALS };
export default DockedControls;
