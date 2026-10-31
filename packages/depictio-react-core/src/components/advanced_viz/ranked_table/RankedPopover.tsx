import React, { useCallback, useLayoutEffect, useRef, useState } from 'react';
import { Icon } from '@iconify/react';
import { ActionIcon, Portal } from '@mantine/core';

import { placePopover, type PopoverPlacement } from './rankedTable';

export interface PopoverContent {
  rank: string;
  title: string;
  subtitle?: string;
  /** Label / value pairs, listed. */
  metrics: [string, string][];
  /** Labelled cells drawn side by side (the genotype of each family member). */
  grid: [string, string][];
}

interface Props {
  content: PopoverContent;
  /** Where the pointer was; the popover sits beside it, inside the viewport. */
  at: { x: number; y: number };
  /** A pinned popover takes the pointer and closes on Esc or an outside click;
   *  a hover one is click-through. */
  pinned: boolean;
  onClose?: () => void;
  /** Rendered under the list: the Family section of a pinned popover. */
  children?: React.ReactNode;
  /** A line under the grid, for the hover popover's "click to pin" hint. */
  hint?: string;
  /** Hover popover only: the pointer moving in and out, so the table keeps it
   *  open while it is reached. */
  onPointerEnter?: () => void;
  onPointerLeave?: () => void;
  /** Hover popover only: a click on it pins it. Without it the popover is
   *  click-through. */
  onActivate?: () => void;
}

/**
 * The popover of a ranked row: its fields as a label / value list and the
 * per-member grid, fixed to the viewport so the tile's scroll box cannot clip
 * it. Hover shows it beside the row; a click on the row or on the popover pins
 * it so its Family section can be used (Esc, the close button or a click
 * outside closes it).
 */
const RankedPopover: React.FC<Props> = ({
  content,
  at,
  pinned,
  onClose,
  children,
  hint,
  onPointerEnter,
  onPointerLeave,
  onActivate,
}) => {
  const ref = useRef<HTMLDivElement | null>(null);
  // The Portal mounts its children after the first commit: a state-held node
  // re-runs the placement once it exists, or a popover whose anchor never
  // moves would stay off-screen.
  const [node, setNode] = useState<HTMLDivElement | null>(null);
  const attach = useCallback((el: HTMLDivElement | null) => {
    ref.current = el;
    setNode(el);
  }, []);
  const [place, setPlace] = useState<PopoverPlacement | null>(null);

  // Placed from its measured size, and again whenever that changes (the Family
  // section opens and loads), so it never grows off the viewport edge.
  useLayoutEffect(() => {
    if (!node) return undefined;
    const update = () =>
      setPlace(
        placePopover(
          at,
          { width: node.offsetWidth, height: node.offsetHeight },
          { width: window.innerWidth, height: window.innerHeight },
        ),
      );
    update();
    if (typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(update);
    observer.observe(node);
    return () => observer.disconnect();
  }, [node, at.x, at.y]);

  useLayoutEffect(() => {
    if (!pinned || !onClose) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    const onDown = (e: PointerEvent) => {
      const target = e.target as Node | null;
      if (!target || ref.current?.contains(target)) return;
      // A click on a row re-pins in its own handler: leave it to that.
      if ((target as Element).closest?.('[data-rt-row]')) return;
      onClose();
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('pointerdown', onDown, true);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', onDown, true);
    };
  }, [pinned, onClose]);

  return (
    <Portal>
      <div
        ref={attach}
        className="dpx-rt__pop"
        role={pinned ? 'dialog' : 'tooltip'}
        aria-label={`${content.title} details`}
        onPointerEnter={pinned ? undefined : onPointerEnter}
        onPointerLeave={pinned ? undefined : onPointerLeave}
        onClick={pinned ? undefined : onActivate}
        style={{
          left: place?.left ?? -9999,
          top: place?.top ?? -9999,
          pointerEvents: pinned || onActivate ? 'auto' : 'none',
          cursor: !pinned && onActivate ? 'pointer' : undefined,
          maxHeight: 'calc(100vh - 16px)',
          overflowY: pinned ? 'auto' : 'hidden',
        }}
      >
        {pinned && onClose ? (
          <ActionIcon
            variant="subtle"
            color="gray"
            size="xs"
            onClick={onClose}
            aria-label="Close"
            style={{ position: 'absolute', top: 8, right: 8 }}
          >
            <Icon icon="mdi:close" width={14} />
          </ActionIcon>
        ) : null}
        <h3 className="dpx-rt__pop-title" style={{ paddingRight: pinned ? 22 : 0 }}>
          #{content.rank} &middot; {content.title}
        </h3>
        {content.subtitle ? <div className="dpx-rt__pop-sub">{content.subtitle}</div> : null}
        {content.metrics.length > 0 ? (
          <dl className="dpx-rt__pop-list">
            {content.metrics.map(([label, value]) => (
              <React.Fragment key={label}>
                <dt>{label}</dt>
                <dd>{value}</dd>
              </React.Fragment>
            ))}
          </dl>
        ) : null}
        {content.grid.length > 0 ? (
          <div className="dpx-rt__pop-grid">
            {content.grid.map(([label, value]) => (
              <span key={label} className="dpx-rt__pop-cell">
                {label}
                <b>{value}</b>
              </span>
            ))}
          </div>
        ) : null}
        {children}
        {hint && !pinned ? (
          <div style={{ marginTop: 8, color: 'var(--mantine-color-dimmed)', fontSize: 11 }}>
            {hint}
          </div>
        ) : null}
      </div>
    </Portal>
  );
};

export default RankedPopover;
