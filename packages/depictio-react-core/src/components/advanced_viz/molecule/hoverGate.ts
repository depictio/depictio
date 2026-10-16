/**
 * What the 3D tile does with the hover callbacks of the viewer.
 *
 * 3Dmol reports "unhover" the moment the pointer leaves an atom and "hover"
 * for the next one a moment later, so a sweep across the structure would
 * clear the highlight, the tooltip and the other tiles' crosshair between
 * every two residues, and redraw the tile each time. The gate keeps what has
 * been applied and does two things:
 *
 * - a hover on the residue already applied does nothing (a residue has many
 *   atoms, and a variant mark sits on its alpha carbon), and
 * - a leave clears one frame later, unless another hover arrives first, so a
 *   move from one residue to the next never shows the gap between them.
 *
 * Pure apart from the scheduler it is given (animation frames in the browser),
 * unit-tested in `hoverGate.test.ts`.
 */

export interface HoverGate<T> {
  /** The pointer is over `value`, identified by `key` (what makes two hovers
   *  the same: entity, chain and residue). */
  enter(key: string, value: T): void;
  /** The pointer left what it was over; clears next frame unless `enter` comes first. */
  leave(): void;
  /** Clear now, dropping a pending clear (the pointer left the whole tile). */
  clear(): void;
  /** Cancel a pending clear and leave nothing applied, clearing if something was. */
  dispose(): void;
}

export interface HoverGateOptions<T> {
  onEnter(value: T): void;
  onClear(): void;
  schedule?(cb: () => void): unknown;
  cancel?(handle: unknown): void;
}

const frameSchedule = (cb: () => void): unknown =>
  typeof requestAnimationFrame === 'function' ? requestAnimationFrame(cb) : setTimeout(cb, 16);
const frameCancel = (handle: unknown): void => {
  if (typeof cancelAnimationFrame === 'function') cancelAnimationFrame(handle as number);
  else clearTimeout(handle as ReturnType<typeof setTimeout>);
};

export function createHoverGate<T>({
  onEnter,
  onClear,
  schedule = frameSchedule,
  cancel = frameCancel,
}: HoverGateOptions<T>): HoverGate<T> {
  let applied: string | null = null;
  let pending: unknown = null;
  let hasPending = false;

  const dropPending = () => {
    if (!hasPending) return;
    cancel(pending);
    pending = null;
    hasPending = false;
  };

  return {
    enter(key, value) {
      dropPending();
      if (key === applied) return;
      applied = key;
      onEnter(value);
    },
    leave() {
      if (applied === null || hasPending) return;
      hasPending = true;
      pending = schedule(() => {
        pending = null;
        hasPending = false;
        applied = null;
        onClear();
      });
    },
    clear() {
      dropPending();
      applied = null;
      onClear();
    },
    dispose() {
      dropPending();
      if (applied === null) return;
      applied = null;
      onClear();
    },
  };
}
