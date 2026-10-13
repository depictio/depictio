/**
 * The floating action dock: the page's keys in a pill the reader can move.
 *
 * A grip at its leading edge drags it; on release it springs to the nearest
 * of four anchors (foot centre, foot left, foot right, head centre). The
 * anchors are CSS (`.hy-anchor[data-anchor]` in layout.css), so the dock
 * keeps following the canvas as the sidebar, the filters drawer and the
 * Analysis panel come and go; JS only measures. While dragging, a ghost at
 * each anchor shows where it can land, and the nearest one lights.
 *
 * Moving the anchor is a FLIP: the dock is at its old place, the CSS puts it
 * at the new one, and a translate that cancels the difference springs to
 * zero. A drag lands the same way, from wherever the pointer left it.
 *
 * Hovering a key names it in one ink label that glides from key to key
 * (useDockTip): it waits a beat before the first name, so passing over the
 * dock shows nothing, then follows the pointer at once. Keys say what to
 * show with `data-tip` (Button.tsx); a key already showing its name gets none.
 *
 * The first time a browser opens a dashboard the dock introduces itself
 * (rises in, names its keys, pulses a halo twice, says what it is for); the
 * look is all CSS, keyed on `data-hint` / `data-labels`.
 */
import React from 'react';
import { VisuallyHidden } from '@mantine/core';
import { AnimatePresence, animate, motion, useMotionValue, useReducedMotion } from 'motion/react';
import type { MotionValue } from 'motion/react';
import { GripVertical } from 'lucide-react';

import { STROKE } from './icons';
import {
  ANCHOR_NAME,
  ANCHOR_STEP,
  DOCK_ANCHORS,
  DOCK_HOME,
  useDockIntro,
} from './useDockPlacement';
import type { DockAnchor } from './useDockPlacement';

/** Glass's spring, a little softer for a bigger move. */
const SETTLE = { type: 'spring', stiffness: 380, damping: 32, mass: 0.8 } as const;
const RISE = { type: 'spring', stiffness: 220, damping: 26 } as const;
/** Pointer travel before a press on the grip becomes a drag. */
const DRAG_PX = 4;
const ARROWS = ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'] as const;
/** The hover label: a beat before the first name, a grace across the gaps
 *  between keys, and a quick spring from one key to the next. */
const TIP_IN_MS = 110;
const TIP_OUT_MS = 140;
const GLIDE = { type: 'spring', stiffness: 560, damping: 40, mass: 0.6 } as const;

interface Point {
  left: number;
  top: number;
}
interface Press {
  id: number;
  px: number;
  py: number;
  /** The dock's box when the press began (its transform included). */
  rect: DOMRect;
  /** The canvas box the dock must stay in. */
  box: DOMRect;
  x0: number;
  y0: number;
  moved: boolean;
}

const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), Math.max(lo, hi));

/** A key that already shows its name: engaged (its name opened out), the
 *  welcome's named keys, or Save. */
const named = (el: HTMLElement) =>
  !!el.closest('[data-hy-name]') ||
  Array.from(el.querySelectorAll<HTMLElement>('.hy-key-label')).some((l) => l.offsetWidth > 0);

/** The dock's hover label: which key it names, and where (its centre, in the
 *  dock's own coordinates). `quiet` hides it (a drag, a move, the welcome). */
function useDockTip(nav: React.RefObject<HTMLElement | null>, quiet: boolean) {
  const reduce = useReducedMotion();
  const x = useMotionValue(0);
  const [text, setText] = React.useState<TipText | null>(null);
  const on = React.useRef<HTMLElement | null>(null);
  // The key just pressed: it is in use, so it is not named again until the
  // pointer moves on.
  const pressed = React.useRef<HTMLElement | null>(null);
  const timer = React.useRef(0);

  const hide = React.useCallback((now = false) => {
    window.clearTimeout(timer.current);
    const go = () => {
      on.current = null;
      setText(null);
    };
    if (now) go();
    else timer.current = window.setTimeout(go, TIP_OUT_MS);
  }, []);

  const show = (el: HTMLElement, at = false) => {
    const tip = el.dataset.tip;
    if (quiet || !tip || el === pressed.current || named(el)) return hide();
    window.clearTimeout(timer.current);
    if (el === on.current) return;
    const go = () => {
      const n = nav.current;
      if (!n) return;
      const r = el.getBoundingClientRect();
      const cx = r.left + r.width / 2 - n.getBoundingClientRect().left;
      // From key to key it glides; the first name just appears there.
      if (on.current && !reduce) animate(x, cx, GLIDE);
      else x.set(cx);
      on.current = el;
      setText({ name: tip, keys: el.dataset.tipKeys });
    };
    if (on.current || at) go();
    else timer.current = window.setTimeout(go, TIP_IN_MS);
  };

  const keyAt = (t: EventTarget | null) => {
    const el = (t as Element | null)?.closest?.<HTMLElement>('[data-tip]') ?? null;
    return el && nav.current?.contains(el) ? el : null;
  };

  React.useEffect(() => {
    if (quiet) hide(true);
  }, [quiet, hide]);
  React.useEffect(() => () => window.clearTimeout(timer.current), []);

  const handlers = {
    onPointerOver: (e: React.PointerEvent) => {
      if (e.pointerType === 'touch') return;
      const el = keyAt(e.target);
      if (el !== pressed.current) pressed.current = null;
      if (el) show(el);
      else hide();
    },
    onPointerLeave: () => {
      pressed.current = null;
      hide();
    },
    onPointerDownCapture: (e: React.PointerEvent) => {
      pressed.current = keyAt(e.target);
      hide(true);
    },
    onFocus: (e: React.FocusEvent) => {
      const el = keyAt(e.target);
      if (el && el.matches(':focus-visible')) show(el, true);
    },
    onBlur: () => hide(true),
  };
  return { text, x, handlers };
}

interface TipText {
  name: string;
  /** A shortcut, drawn as a key cap. */
  keys?: string;
}

/** The label itself: it fades in where it first lands, then only its text
 *  changes while it glides. */
const DockTip: React.FC<{ text: TipText | null; x: MotionValue<number>; top: boolean }> = ({
  text,
  x,
  top,
}) => (
  <AnimatePresence>
    {text !== null && (
      <motion.span
        key="tip"
        className="hy-dock-tip"
        style={{ x }}
        initial={{ opacity: 0, scale: 0.9, y: top ? -4 : 4 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.96, transition: { duration: 0.1 } }}
        transition={{ duration: 0.16, ease: [0.2, 0.8, 0.2, 1] }}
        aria-hidden
      >
        <AnimatePresence initial={false}>
          <motion.span
            key={text.name}
            initial={{ opacity: 0, y: 3 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -3 }}
            transition={{ duration: 0.12 }}
          >
            {text.name}
            {text.keys && <kbd>{text.keys}</kbd>}
          </motion.span>
        </AnimatePresence>
      </motion.span>
    )}
  </AnimatePresence>
);

export const Dock: React.FC<{
  anchor: DockAnchor;
  onAnchor: (next: DockAnchor) => void;
  children: React.ReactNode;
}> = ({ anchor, onAnchor, children }) => {
  const reduce = useReducedMotion();
  const intro = useDockIntro();
  const top = anchor === 'top-center';
  const nav = React.useRef<HTMLElement>(null);
  const ghosts = React.useRef(new Map<DockAnchor, HTMLElement>());
  const press = React.useRef<Press | null>(null);
  const near = React.useRef<DockAnchor>(anchor);
  // Set when the anchor is about to change: where the dock was, and (after a
  // drag) where the new anchor's ghost sits, read before the ghosts unmount.
  const flip = React.useRef<{ from: Point; base?: Point } | null>(null);

  // Rendered through `transform`; the anchors position with `left`/`top`.
  const x = useMotionValue(0);
  const y = useMotionValue(intro.on && !reduce ? (top ? -28 : 28) : 0);
  const [drag, setDrag] = React.useState<{ near: DockAnchor; w: number; h: number } | null>(null);
  const [settling, setSettling] = React.useState(false);
  const [note, setNote] = React.useState('');
  // Whether the keys can all show their names without outgrowing the canvas.
  const [roomy, setRoomy] = React.useState(true);

  const began = React.useRef(intro.on);
  const moving = drag !== null || settling;
  // The names stay out until a move lands, or the dock would shrink under
  // the pointer that is carrying it.
  const labels = roomy && (intro.on || (began.current && moving));
  const tip = useDockTip(nav, moving || intro.on);

  React.useEffect(() => {
    if (!intro.on || reduce) return;
    const rise = animate(y, 0, RISE);
    return () => rise.stop();
    // Once, on arrival.
  }, []);

  // With every name out the dock is wide: on a narrow canvas skip the names
  // and keep the halo and the caption.
  React.useLayoutEffect(() => {
    const el = nav.current;
    const host = el?.parentElement;
    if (!intro.on || !el || !host) return;
    const padR = parseFloat(getComputedStyle(host).getPropertyValue('--gl-pad-r')) || 0;
    setRoomy(el.offsetWidth <= host.clientWidth - padR - 48);
    // Once, on arrival.
  }, []);

  /** Bring the dock from where it was (`from`) to its anchor (`base`, the
   *  untransformed position there) with a spring. */
  const settle = (from: Point, base: Point) => {
    x.stop();
    y.stop();
    x.set(from.left - base.left);
    y.set(from.top - base.top);
    if (reduce) {
      x.set(0);
      y.set(0);
      setSettling(false);
      return;
    }
    let left = 2;
    const done = () => {
      left -= 1;
      if (left === 0) setSettling(false);
    };
    animate(x, 0, { ...SETTLE, onComplete: done });
    animate(y, 0, { ...SETTLE, onComplete: done });
  };

  React.useLayoutEffect(() => {
    const f = flip.current;
    const el = nav.current;
    flip.current = null;
    if (!f || !el) return;
    const r = el.getBoundingClientRect();
    settle(f.from, f.base ?? { left: r.left - x.get(), top: r.top - y.get() });
    // Runs when the anchor changes.
  }, [anchor]);

  const moveTo = (next: DockAnchor) => {
    const el = nav.current;
    if (!el || next === anchor) return;
    const r = el.getBoundingClientRect();
    flip.current = { from: { left: r.left, top: r.top } };
    setSettling(true);
    setNote(`Toolbar moved to ${ANCHOR_NAME[next]}`);
    if (intro.on) intro.end();
    onAnchor(next);
  };

  const nearest = (cx: number, cy: number): DockAnchor => {
    let best = near.current;
    let bestD = Infinity;
    ghosts.current.forEach((el, a) => {
      const r = el.getBoundingClientRect();
      const d = Math.hypot(cx - (r.left + r.width / 2), cy - (r.top + r.height / 2));
      if (d < bestD) {
        bestD = d;
        best = a;
      }
    });
    return best;
  };

  /** End a drag: land on the nearest anchor, or (cancelled) go back. */
  const finish = (commit: boolean) => {
    const s = press.current;
    press.current = null;
    if (!s || !s.moved) return;
    const from = { left: s.rect.left + x.get() - s.x0, top: s.rect.top + y.get() - s.y0 };
    const target = commit ? near.current : anchor;
    if (intro.on) intro.end();
    setSettling(true);
    setDrag(null);
    if (target === anchor) {
      settle(from, { left: s.rect.left - s.x0, top: s.rect.top - s.y0 });
      return;
    }
    const g = ghosts.current.get(target)?.getBoundingClientRect();
    flip.current = { from, base: g && { left: g.left, top: g.top } };
    setNote(`Toolbar moved to ${ANCHOR_NAME[target]}`);
    onAnchor(target);
  };
  const finishRef = React.useRef(finish);
  finishRef.current = finish;

  // Esc drops the dock back where it was (and is not for anything else then).
  const dragging = drag !== null;
  React.useEffect(() => {
    if (!dragging) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      e.preventDefault();
      e.stopPropagation();
      finishRef.current(false);
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [dragging]);

  const onPointerDown = (e: React.PointerEvent<HTMLButtonElement>) => {
    const el = nav.current;
    if (e.button !== 0 || !el?.parentElement) return;
    x.stop();
    y.stop();
    setSettling(false);
    e.currentTarget.setPointerCapture(e.pointerId);
    near.current = anchor;
    press.current = {
      id: e.pointerId,
      px: e.clientX,
      py: e.clientY,
      rect: el.getBoundingClientRect(),
      box: el.parentElement.getBoundingClientRect(),
      x0: x.get(),
      y0: y.get(),
      moved: false,
    };
  };
  const onPointerMove = (e: React.PointerEvent<HTMLButtonElement>) => {
    const s = press.current;
    if (!s || e.pointerId !== s.id) return;
    let dx = e.clientX - s.px;
    let dy = e.clientY - s.py;
    if (!s.moved) {
      if (Math.hypot(dx, dy) < DRAG_PX) return;
      s.moved = true;
      setDrag({ near: anchor, w: s.rect.width, h: s.rect.height });
    }
    // Stay inside the canvas.
    dx = clamp(dx, s.box.left - s.rect.left, s.box.right - s.rect.right);
    dy = clamp(dy, s.box.top - s.rect.top, s.box.bottom - s.rect.bottom);
    x.set(s.x0 + dx);
    y.set(s.y0 + dy);
    const next = nearest(s.rect.left + dx + s.rect.width / 2, s.rect.top + dy + s.rect.height / 2);
    if (next !== near.current) {
      near.current = next;
      setDrag((d) => (d ? { ...d, near: next } : d));
    }
  };
  const onPointerUp = (e: React.PointerEvent<HTMLButtonElement>) => {
    if (press.current?.id === e.pointerId) finish(true);
  };
  const onPointerCancel = (e: React.PointerEvent<HTMLButtonElement>) => {
    if (press.current?.id === e.pointerId) finish(false);
  };

  const onGripKey = (e: React.KeyboardEvent<HTMLButtonElement>) => {
    if (e.key === 'Home') {
      e.preventDefault();
      moveTo(DOCK_HOME);
    } else if ((ARROWS as readonly string[]).includes(e.key)) {
      e.preventDefault();
      const next = ANCHOR_STEP[anchor][e.key as (typeof ARROWS)[number]];
      if (next) moveTo(next);
    }
  };

  return (
    <>
      {drag &&
        DOCK_ANCHORS.map((a) => (
          <div
            key={a}
            ref={(el) => {
              if (el) ghosts.current.set(a, el);
              else ghosts.current.delete(a);
            }}
            className="hy-anchor hy-dock-ghost"
            data-anchor={a}
            data-near={drag.near === a || undefined}
            data-moving=""
            style={{ width: drag.w, height: drag.h }}
            aria-hidden
          />
        ))}
      <motion.nav
        ref={nav}
        className="hy-dock hy-anchor"
        aria-label="Dashboard actions"
        data-anchor={anchor}
        data-moving={moving ? '' : undefined}
        data-dragging={dragging ? '' : undefined}
        data-hint={intro.on ? '' : undefined}
        data-labels={labels ? '' : undefined}
        style={{ x, y }}
        // The click that uses a key ends the introduction after it lands, so
        // the names do not fold away between the press and the release.
        onClickCapture={intro.on ? intro.end : undefined}
        onKeyDownCapture={intro.on ? (e) => e.key !== 'Tab' && intro.end() : undefined}
        {...tip.handlers}
      >
        <button
          type="button"
          className="hy-dock-grip"
          aria-label="Move the toolbar"
          data-testid="dock-grip"
          data-tip="Drag to move, double-click to reset"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerCancel}
          onKeyDown={onGripKey}
          onDoubleClick={() => moveTo(DOCK_HOME)}
        >
          <GripVertical size={16} strokeWidth={STROKE} aria-hidden />
        </button>
        {children}
        <DockTip text={tip.text} x={tip.x} top={top} />
        {intro.on && (
          <span className="hy-dock-hint" role="status">
            Search, analyse and edit from here. Drag the grip to move it.
          </span>
        )}
        <VisuallyHidden role="status">{note}</VisuallyHidden>
      </motion.nav>
    </>
  );
};
