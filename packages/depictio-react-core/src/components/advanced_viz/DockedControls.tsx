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

/**
 * A renderer's controls docked beside or above its plot (see controlsDock.ts),
 * showing a few and folding the rest under "More options": a panel listing all
 * of a sankey's dozen settings lost the reader before the plot did. The pick
 * is made when the panel mounts or its set of controls changes, not on every
 * change of value, so a control never jumps between the two while it is used.
 *
 * Titled, so the panel reads as the plot's settings rather than as part of the
 * figure.
 */
const DockedControls: React.FC<{ controls: React.ReactNode; side: DockSide }> = ({
  controls,
  side,
}) => {
  const ref = useRef<HTMLDivElement | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [extra, setExtra] = useState(0);

  useLayoutEffect(() => {
    const root = ref.current?.firstElementChild as HTMLElement | null;
    if (!root) return;
    let count = -1;
    const apply = () => {
      const items = Array.from(root.children) as HTMLElement[];
      if (items.length === count) return;
      count = items.length;
      const keep = pickEssentials(items.map(isLive));
      items.forEach((it, i) => {
        if (keep[i]) it.removeAttribute('data-dock-extra');
        else it.setAttribute('data-dock-extra', '');
      });
      setExtra(keep.filter((k) => !k).length);
    };
    apply();
    const mo = new MutationObserver(apply);
    mo.observe(root, { childList: true });
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
