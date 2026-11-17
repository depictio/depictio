import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { ActionIcon, Group, Popover, Text, UnstyledButton } from '@mantine/core';
import { Icon } from '@iconify/react';

import { useFullscreenPortalTarget } from '../chrome/useFullscreenPortalTarget';
import {
  DOCK_ESSENTIALS,
  DOCK_TOP_MAX,
  fitInline,
  pickEssentials,
  type DockSide,
} from './controlsDock';
import { VIZ_ROW_GAP_PX, VizControlsGrid } from './controls/VizControls';

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

/** An element a control renders beside itself that is not a control: the
 *  hidden input a Mantine Select keeps next to its box. Counted as one, it
 *  added a phantom to "More options (n)" for every dropdown. */
function isControlElement(el: Element): el is HTMLElement {
  if (el instanceof HTMLInputElement && el.type === 'hidden') return false;
  return !['STYLE', 'SCRIPT', 'TEMPLATE'].includes(el.tagName);
}

function controlChildren(el: Element): HTMLElement[] {
  return Array.from(el.children).filter(isControlElement);
}

/** The controls of one item of the panel: itself, or, for a titled group
 *  (`VizControlGroup`, marked `data-viz-group`), the controls in its body. A
 *  group counts as the controls it holds, so a panel of three groups no
 *  longer shows every control of all three before "More options". */
function controlsOf(item: HTMLElement): HTMLElement[] {
  if (item.hasAttribute('data-viz-group')) {
    const body = item.querySelector('[data-viz-group-body]');
    return body ? controlChildren(body) : [item];
  }
  // A renderer that hands every control over in one bare stack (the tree's
  // summary): its children are the controls. Two of them taking input tells
  // it from one control laid out as a stack (a label over a switch).
  if (item.classList.contains('mantine-Stack-root')) {
    const kids = controlChildren(item);
    if (kids.filter((k) => k.querySelector('input, textarea')).length >= 2) return kids;
  }
  return [item];
}

interface Units {
  items: HTMLElement[];
  groups: HTMLElement[][];
  units: HTMLElement[];
}

/** A panel's items, and the controls each holds, in order. The line and the
 *  overflow popover draw the same controls, so the same position names the
 *  same control in both. */
function unitsOf(root: HTMLElement): Units {
  const items = controlChildren(root);
  const groups = items.map(controlsOf);
  return { items, groups, units: groups.flat() };
}

/** Marks with `attr` the controls `folded` names, and every group none of
 *  whose controls is left: it folds whole, its title with it. */
function markFolded({ items, groups, units }: Units, folded: readonly boolean[], attr: string) {
  const mark = (el: HTMLElement, on: boolean) =>
    on ? el.setAttribute(attr, '') : el.removeAttribute(attr);
  units.forEach((u, i) => mark(u, Boolean(folded[i])));
  items.forEach((it, i) => {
    if (groups[i][0] !== it) mark(it, groups[i].every((u) => u.hasAttribute(attr)));
  });
}

/** Room kept for the "More (n)" button on the line before it has been drawn. */
const MORE_RESERVE_PX = 80;

function sameFlags(a: readonly boolean[], b: readonly boolean[]): boolean {
  return a.length === b.length && a.every((v, i) => v === b[i]);
}

/**
 * The controls the top line left out, in the "More options" popover: the
 * panel drawn again as a column, with the ones already on the line hidden.
 * Matched by position (see `unitsOf`); if the two copies ever disagree on how
 * many controls there are, the popover shows them all rather than hide the
 * wrong ones.
 */
const OverflowBody: React.FC<{ controls: React.ReactNode; inline: readonly boolean[] }> = ({
  controls,
  inline,
}) => {
  const ref = useRef<HTMLDivElement | null>(null);
  useLayoutEffect(() => {
    const root = ref.current?.firstElementChild as HTMLElement | null;
    if (!root) return;
    const apply = () => {
      const found = unitsOf(root);
      const hide = found.units.length === inline.length ? inline : found.units.map(() => false);
      markFolded(found, hide, 'data-dock-inline');
    };
    apply();
    const mo = new MutationObserver(apply);
    mo.observe(root, { childList: true, subtree: true });
    return () => mo.disconnect();
  }, [controls, inline]);
  return (
    <div ref={ref} className="dpx-viz-dock-overflow">
      <VizControlsGrid layout="column">{controls}</VizControlsGrid>
    </div>
  );
};

/**
 * A renderer's controls docked beside or above its plot (see controlsDock.ts),
 * showing a few and folding the rest under "More options": a panel listing all
 * of a sankey's dozen settings lost the reader before the plot did. The pick
 * is made when the panel mounts or its set of controls changes, not on every
 * change of value, so a control never jumps between the two while it is used.
 *
 * Beside the plot (`right`) the panel is a titled column: the first few live
 * controls, the rest unfolded in place by "More options".
 *
 * Above it (`top`) the panel is one line, no title: as many controls as fit,
 * compact (`VizControlsGrid` `row`: short inline labels, narrow inputs, group
 * captions dissolved), then "More options", which opens the rest in a
 * popover rather than unfolding them, and the placement picker last. A line
 * that grew into a form ate a third of a half-width tile. Which controls fit
 * is measured (`fitInline`) and measured again when the tile is resized.
 *
 * `lead` (a view switch) comes first and is never folded. `headerAction` is
 * the placement picker every other controls block heads with, so a docked
 * panel can be moved into a rail or under the title like the popover can:
 * while docked, the chrome's settings icon only folds the panel and opens no
 * popover to pick from.
 */
const DockedControls: React.FC<{
  controls: React.ReactNode;
  side: DockSide;
  lead?: React.ReactNode;
  headerAction?: React.ReactNode;
}> = ({ controls, side, lead, headerAction }) => {
  const top = side === 'top';
  const dockRef = useRef<HTMLDivElement | null>(null);
  const lineRef = useRef<HTMLDivElement | null>(null);
  const leadRef = useRef<HTMLDivElement | null>(null);
  const ref = useRef<HTMLDivElement | null>(null);
  const moreRef = useRef<HTMLButtonElement | null>(null);
  const actionRef = useRef<HTMLSpanElement | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [keep, setKeep] = useState<boolean[]>([]);
  const portalTarget = useFullscreenPortalTarget();

  useLayoutEffect(() => {
    const root = ref.current?.firstElementChild as HTMLElement | null;
    const dock = dockRef.current;
    if (!root || !dock) return;
    let count = -1;
    const pickTop = (units: HTMLElement[], live: boolean[]): boolean[] => {
      // Every control's own width, measured with all of them shown.
      dock.setAttribute('data-measuring', '');
      const widths = units.map((u) => u.getBoundingClientRect().width);
      dock.removeAttribute('data-measuring');
      const width = (el: HTMLElement | null) => (el ? el.getBoundingClientRect().width : 0);
      const lineW = lineRef.current?.clientWidth ?? 0;
      const leadW = width(leadRef.current);
      const actionW = width(actionRef.current);
      const moreW = width(moreRef.current);
      const beside = (w: number) => (w > 0 ? w + VIZ_ROW_GAP_PX : 0);
      const available = lineW - beside(leadW) - beside(actionW);
      return fitInline(widths, live, available, {
        gap: VIZ_ROW_GAP_PX,
        reserve: (moreW > 0 ? moreW : MORE_RESERVE_PX) + VIZ_ROW_GAP_PX,
        max: DOCK_TOP_MAX,
      });
    };
    const apply = (force: boolean) => {
      const found = unitsOf(root);
      if (!force && found.units.length === count) return;
      count = found.units.length;
      const live = found.units.map(isLive);
      const next = top ? pickTop(found.units, live) : pickEssentials(live, DOCK_ESSENTIALS);
      const folded = next.map((k) => !k);
      markFolded(found, folded, 'data-dock-extra');
      setKeep((prev) => (sameFlags(prev, next) ? prev : next));
    };
    apply(true);
    // Subtree: a group's controls can come and go without the panel's own
    // children changing. Only the count of controls re-runs the pick.
    const mo = new MutationObserver(() => apply(false));
    mo.observe(root, { childList: true, subtree: true });
    // On the line, a resized tile has room for more controls or fewer.
    let ro: ResizeObserver | null = null;
    if (top && lineRef.current && typeof ResizeObserver !== 'undefined') {
      let lastW = lineRef.current.clientWidth;
      ro = new ResizeObserver(() => {
        const w = lineRef.current?.clientWidth ?? 0;
        if (Math.abs(w - lastW) < 1) return;
        lastW = w;
        apply(true);
      });
      ro.observe(lineRef.current);
    }
    return () => {
      mo.disconnect();
      ro?.disconnect();
    };
  }, [controls, top]);

  const extra = keep.filter((k) => !k).length;
  const [overflowOpen, setOverflowOpen] = useState(false);
  useEffect(() => {
    if (extra === 0) setOverflowOpen(false);
  }, [extra]);

  const grid = <VizControlsGrid layout={top ? 'row' : 'column'}>{controls}</VizControlsGrid>;

  if (top) {
    const moreLabel = `More options (${extra})`;
    return (
      <div
        ref={dockRef}
        className="dpx-viz-dock dpx-viz-dock--top"
        role="group"
        aria-label="Controls"
        data-testid="viz-controls-dock"
      >
        <div ref={lineRef} className="dpx-viz-dock__line">
          {lead ? (
            <div ref={leadRef} className="dpx-viz-dock__lead">
              {lead}
            </div>
          ) : null}
          <div ref={ref} className="dpx-viz-dock__controls">
            {grid}
          </div>
          {extra > 0 || headerAction ? (
            <span className="dpx-viz-dock__end">
              {extra > 0 ? (
                // Not closed by a click outside: the controls inside include
                // dropdowns whose own menus are portaled out of the popover
                // (as in the settings popover). Escape, the button and the
                // close icon close it.
                <Popover
                  opened={overflowOpen}
                  onChange={setOverflowOpen}
                  position="bottom-end"
                  shadow="md"
                  withArrow
                  closeOnClickOutside={false}
                  closeOnEscape
                  portalProps={{ target: portalTarget }}
                >
                  <Popover.Target>
                    <UnstyledButton
                      ref={moreRef}
                      className="dpx-viz-dock__more"
                      onClick={() => setOverflowOpen((o) => !o)}
                      aria-expanded={overflowOpen}
                      aria-haspopup="dialog"
                      title={moreLabel}
                      data-testid="viz-controls-more"
                    >
                      <Icon icon="tabler:adjustments-horizontal" width={14} height={14} />
                      {`More (${extra})`}
                    </UnstyledButton>
                  </Popover.Target>
                  <Popover.Dropdown
                    p="sm"
                    style={{ minWidth: 260, maxWidth: 340 }}
                    data-testid="viz-controls-overflow"
                  >
                    <Group justify="space-between" wrap="nowrap" gap="xs" mb={8}>
                      <Text size="xs" fw={600} c="dimmed">
                        More options
                      </Text>
                      <ActionIcon
                        variant="subtle"
                        size="xs"
                        color="gray"
                        aria-label="Close more options"
                        title="Close"
                        onClick={() => setOverflowOpen(false)}
                      >
                        <Icon icon="tabler:x" width={14} height={14} />
                      </ActionIcon>
                    </Group>
                    <div
                      style={{ maxHeight: 'min(60vh, 480px)', overflowY: 'auto', overflowX: 'hidden' }}
                    >
                      <OverflowBody controls={controls} inline={keep} />
                    </div>
                  </Popover.Dropdown>
                </Popover>
              ) : null}
              {headerAction ? (
                <span ref={actionRef} className="dpx-viz-dock__action">
                  {headerAction}
                </span>
              ) : null}
            </span>
          ) : null}
        </div>
      </div>
    );
  }

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
      ref={dockRef}
      className={`dpx-viz-dock dpx-viz-dock--${side}${expanded ? ' is-expanded' : ''}`}
      data-testid="viz-controls-dock"
    >
      <div className="dpx-viz-dock__head">
        <span className="dpx-viz-dock__title">
          <Icon icon="tabler:adjustments-horizontal" width={13} height={13} />
          Controls
        </span>
        {headerAction ? <span className="dpx-viz-dock__head-end">{headerAction}</span> : null}
      </div>
      <div className="dpx-viz-dock__body">
        {lead ? <div className="dpx-viz-dock__lead">{lead}</div> : null}
        <div ref={ref} className="dpx-viz-dock__controls">
          {grid}
        </div>
      </div>
      {more}
    </div>
  );
};

export { DOCK_ESSENTIALS };
export default DockedControls;
