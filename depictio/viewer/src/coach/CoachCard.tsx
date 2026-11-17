import React, { useEffect, useRef, useState } from 'react';
import { Box, CloseButton, Group, Popover, Stack, Text } from '@mantine/core';
import type { PopoverProps } from '@mantine/core';
import { Z_LAYERS } from 'depictio-react-core';

import './coach.css';

/** Above the map card and page furniture, below drawers and modals: a modal
 *  the visitor opens (New dashboard, a component's settings) covers the card
 *  rather than the other way round. */
export const COACH_Z = Z_LAYERS.overlay - 10;

/** The element a `data-tour-id` names, on the screen it is drawn on: the same
 *  id can sit in the desktop rail and the phone's list, and only one has a box. */
export function visibleTarget(id: string): HTMLElement | undefined {
  // A `data-tour-id`, or a CSS selector for what carries none (a chrome
  // variant's button, a tile's action row).
  const selector = /^[.[#]/.test(id) ? id : `[data-tour-id="${id}"]`;
  return Array.from(document.querySelectorAll<HTMLElement>(selector)).find(
    (e) => e.getClientRects().length > 0,
  );
}

function sameRect(a: DOMRect | null, b: DOMRect | null): boolean {
  if (!a || !b) return a === b;
  return a.top === b.top && a.left === b.left && a.width === b.width && a.height === b.height;
}

type Position = NonNullable<PopoverProps['position']>;

interface Found {
  /** Which of the ids asked for is drawn. */
  id: string | null;
  el: HTMLElement | null;
  rect: DOMRect | null;
}

/** Where the first drawn of `ids` is, followed as the page scrolls, resizes
 *  or re-renders. Null while none is on the page. */
function useTargetRect(ids: readonly string[]): Found {
  const [found, setFound] = useState<Found>({ id: null, el: null, rect: null });
  const key = ids.join('|');
  useEffect(() => {
    const list = key ? key.split('|') : [];
    if (list.length === 0) {
      setFound({ id: null, el: null, rect: null });
      return;
    }
    let frame = 0;
    const measure = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        let id: string | null = null;
        let el: HTMLElement | null = null;
        for (const candidate of list) {
          el = visibleTarget(candidate) ?? null;
          if (el) {
            id = candidate;
            break;
          }
        }
        const rect = el ? el.getBoundingClientRect() : null;
        setFound((prev) => (prev.el === el && sameRect(prev.rect, rect) ? prev : { id, el, rect }));
      });
    };
    measure();
    const mo = new MutationObserver(measure);
    mo.observe(document.body, { childList: true, subtree: true, attributes: true });
    window.addEventListener('resize', measure);
    window.addEventListener('scroll', measure, true);
    return () => {
      cancelAnimationFrame(frame);
      mo.disconnect();
      window.removeEventListener('resize', measure);
      window.removeEventListener('scroll', measure, true);
    };
  }, [key]);
  return found;
}

const RING_PAD = 4;

/** A target this large (the editor's whole canvas) leaves no room around it:
 *  it is ringed, and the card stands on its own. */
function isLarge(rect: DOMRect): boolean {
  return rect.height > window.innerHeight * 0.6 || rect.width > window.innerWidth * 0.85;
}

/** A pulsing ring around the element, drawn on <body> so no `overflow:
 *  hidden` parent clips it. */
const TargetRing: React.FC<{ rect: DOMRect }> = ({ rect }) => (
  <div
    className="depictio-coach-ring"
    aria-hidden
    data-walkthrough="ring"
    style={{
      top: rect.top - RING_PAD,
      left: rect.left - RING_PAD,
      width: rect.width + RING_PAD * 2,
      height: rect.height + RING_PAD * 2,
      zIndex: COACH_Z,
    }}
  />
);

/** `**bold**` and `` `code` `` in one sentence of coach text. */
export function renderCoachText(text: string): React.ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={i}>{part.slice(2, -2)}</strong>;
    if (part.startsWith('`') && part.endsWith('`')) return <code key={i}>{part.slice(1, -1)}</code>;
    return <React.Fragment key={i}>{part}</React.Fragment>;
  });
}

/** Progress as dots: the current one long, the done ones lighter. */
export const CoachDots: React.FC<{ total: number; current: number }> = ({ total, current }) => (
  <span className="depictio-coach-dots" role="img" aria-label={`Step ${current + 1} of ${total}`}>
    {Array.from({ length: total }, (_, i) => (
      <span
        key={i}
        className="depictio-coach-dot"
        data-active={i === current || undefined}
        data-done={i < current || undefined}
      />
    ))}
  </span>
);

export interface CoachCardProps {
  /** `data-tour-id` to point at, or several in order of preference (the
   *  first drawn wins). Null, or none on screen, draws the card on its own in
   *  the bottom-right corner (a sheet on a phone). */
  target: string | readonly string[] | null;
  /** Where the card sits around its target: one side, or one per target id. */
  position?: Position | Readonly<Record<string, Position>>;
  /** The card's mark: an icon or the Depictio rose. */
  mark: React.ReactNode;
  /** Small caps above the title, e.g. "Dashboards · 2 of 3". */
  eyebrow?: string;
  title: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
  onClose: () => void;
  closeLabel?: string;
  /** Ring the target while the card is up. */
  ring?: boolean;
  /** Take the focus when shown: for a card the visitor asked for, never for
   *  an offer they did not. */
  autoFocus?: boolean;
  width?: number;
  testId?: string;
  /** Changes with each step, so the focus and scroll follow it. */
  stepKey?: string;
}

/**
 * One coach card. It dims nothing and blocks nothing: the page stays usable
 * beneath it, and Esc closes it.
 */
const CoachCard: React.FC<CoachCardProps> = ({
  target,
  position = 'bottom',
  mark,
  eyebrow,
  title,
  children,
  footer,
  onClose,
  closeLabel = 'Close',
  ring = false,
  autoFocus = false,
  width = 360,
  testId,
  stepKey,
}) => {
  const ids = target === null ? [] : typeof target === 'string' ? [target] : target;
  const { id: drawnId, el, rect } = useTargetRect(ids);
  const side: Position =
    typeof position === 'string' ? position : ((drawnId && position[drawnId]) || 'bottom');
  const cardRef = useRef<HTMLDivElement>(null);

  // A target below the fold: bring it up once per step.
  useEffect(() => {
    if (!el) return;
    const r = el.getBoundingClientRect();
    if (!isLarge(r) && (r.top < 0 || r.bottom > window.innerHeight)) {
      el.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
  }, [el, stepKey]);

  useEffect(() => {
    if (autoFocus) cardRef.current?.focus({ preventScroll: true });
  }, [autoFocus, stepKey]);

  const card = (
    <div
      ref={cardRef}
      className="depictio-coach-card depictio-walkthrough-popover"
      role="dialog"
      aria-modal={false}
      aria-label={title}
      tabIndex={-1}
      data-testid={testId}
      onKeyDown={(e) => {
        if (e.key === 'Escape') {
          e.stopPropagation();
          onClose();
        }
      }}
    >
      <Stack gap="sm" p="md">
        <Group align="flex-start" wrap="nowrap" gap="sm">
          <span className="depictio-coach-mark" aria-hidden>
            {mark}
          </span>
          <Stack gap={2} style={{ minWidth: 0, flex: 1 }}>
            {eyebrow && <span className="depictio-coach-eyebrow">{eyebrow}</span>}
            <Text fw={650} size="md" lh={1.3}>
              {title}
            </Text>
          </Stack>
          <CloseButton size="sm" aria-label={closeLabel} onClick={onClose} data-testid="coach-close" />
        </Group>
        <Box className="depictio-coach-body" fz="sm" lh={1.55}>
          {children}
        </Box>
        {footer}
      </Stack>
    </div>
  );

  if (!rect || isLarge(rect)) {
    return (
      <>
        {ring && rect && <TargetRing rect={rect} />}
        <div className="depictio-coach-floating" data-walkthrough="card" style={{ width, zIndex: COACH_Z }}>
          {card}
        </div>
      </>
    );
  }

  return (
    <>
      {ring && <TargetRing rect={rect} />}
      <Popover
        opened
        position={side}
        withArrow
        arrowSize={12}
        offset={14}
        width={width}
        withinPortal
        zIndex={COACH_Z}
        middlewares={{ flip: true, shift: { padding: 12 } }}
        transitionProps={{ transition: 'pop', duration: 180 }}
        styles={{
          dropdown: { padding: 0, border: 'none', background: 'transparent' },
          arrow: {
            borderColor: 'var(--mantine-primary-color-filled)',
            borderWidth: 1.5,
            background:
              'color-mix(in srgb, var(--mantine-primary-color-filled) 9%, var(--mantine-color-body))',
          },
        }}
      >
        <Popover.Target>
          {/* An invisible proxy over the real element: anchors without touching it. */}
          <Box
            aria-hidden
            data-walkthrough="anchor"
            style={{
              position: 'fixed',
              top: rect.top,
              left: rect.left,
              width: rect.width,
              height: rect.height,
              pointerEvents: 'none',
            }}
          />
        </Popover.Target>
        <Popover.Dropdown>{card}</Popover.Dropdown>
      </Popover>
    </>
  );
};

export default CoachCard;
