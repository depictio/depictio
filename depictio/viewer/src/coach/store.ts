import { useSyncExternalStore } from 'react';

import { CHAPTERS } from './chapters';

/**
 * What a visitor has seen of the coach, in this browser.
 *
 * Client-side only, like the landing card: storage can be missing (private
 * window, blocked site data) and every read and write is guarded, so the coach
 * then simply offers itself again on the next load.
 */

const KEY = 'depictio.coach.v1';
/** The tours this coach replaces. Someone who finished or skipped one is not
 *  welcomed again, nor offered the chapters it covered. */
const LEGACY_KEYS = ['depictio.walkthrough.builder', 'depictio.walkthrough.public'];
/** A chapter chosen on one page and started on the next (the welcome card's
 *  journeys navigate). Session-scoped: it never outlives the tab. */
const PENDING_KEY = 'depictio.coach.pending';

export const COACH_START_EVENT = 'depictio:coach:start';

export type ChapterStatus = 'done' | 'dismissed';

export interface CoachState {
  welcomeSeen: boolean;
  /** No offers anywhere. The compass and Account settings still start one. */
  tipsOff: boolean;
  chapters: Record<string, { status: ChapterStatus; version: number }>;
}

const EMPTY: CoachState = { welcomeSeen: false, tipsOff: false, chapters: {} };

function legacyFinished(): boolean {
  try {
    return LEGACY_KEYS.some((k) => {
      const raw = localStorage.getItem(k);
      if (!raw) return false;
      const status = (JSON.parse(raw) as { status?: string }).status;
      return status === 'completed' || status === 'skipped';
    });
  } catch {
    return false;
  }
}

function read(): CoachState {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<CoachState>;
      return {
        welcomeSeen: Boolean(parsed.welcomeSeen),
        tipsOff: Boolean(parsed.tipsOff),
        chapters: parsed.chapters && typeof parsed.chapters === 'object' ? parsed.chapters : {},
      };
    }
  } catch {
    return EMPTY;
  }
  if (legacyFinished()) {
    const chapters: CoachState['chapters'] = {};
    for (const c of CHAPTERS) chapters[c.id] = { status: 'dismissed', version: c.version };
    return { welcomeSeen: true, tipsOff: false, chapters };
  }
  return EMPTY;
}

let state: CoachState = typeof window === 'undefined' ? EMPTY : read();
const listeners = new Set<() => void>();

function commit(next: CoachState): void {
  state = next;
  try {
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    /* storage unavailable: kept for this page load only */
  }
  for (const l of listeners) l();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  const onStorage = (e: StorageEvent) => {
    if (e.key !== KEY) return;
    state = read();
    listener();
  };
  window.addEventListener('storage', onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener('storage', onStorage);
  };
}

export function useCoachState(): CoachState {
  return useSyncExternalStore(subscribe, () => state, () => EMPTY);
}

export function chapterSeen(s: CoachState, id: string, version: number): boolean {
  const entry = s.chapters[id];
  return Boolean(entry && entry.version === version);
}

export function markChapter(id: string, version: number, status: ChapterStatus): void {
  commit({ ...state, chapters: { ...state.chapters, [id]: { status, version } } });
}

export function markWelcomeSeen(): void {
  if (!state.welcomeSeen) commit({ ...state, welcomeSeen: true });
}

export function setTipsOff(off: boolean): void {
  commit({ ...state, tipsOff: off, welcomeSeen: true });
}

/** Everything back to a first visit: the welcome and every offer return. */
export function resetCoach(): void {
  commit(EMPTY);
}

/** Starts a chapter here, or the page's own chapter when `id` is omitted. */
export function startChapter(id?: string): void {
  window.dispatchEvent(new CustomEvent(COACH_START_EVENT, { detail: { id } }));
}

/** Starts `id` on the next page this tab loads, then goes to `href`. */
export function startChapterAt(id: string, href: string): void {
  try {
    sessionStorage.setItem(PENDING_KEY, id);
  } catch {
    /* the chapter is offered there instead */
  }
  window.location.assign(href);
}

/** The chapter on screen, if any: the landing card steps aside for it. */
let runningId: string | null = null;
const runningListeners = new Set<() => void>();

export function setRunningChapter(id: string | null): void {
  if (runningId === id) return;
  runningId = id;
  for (const l of runningListeners) l();
}

export function useRunningChapter(): string | null {
  return useSyncExternalStore(
    (l) => {
      runningListeners.add(l);
      return () => runningListeners.delete(l);
    },
    () => runningId,
    () => null,
  );
}

/** Read once per page load, outside React: StrictMode runs a state
 *  initializer twice, and the second run would find the request consumed. */
let pending: string | null | undefined;

/** The chapter a previous page asked to start here. Consumed on first read,
 *  then the same answer for the rest of this page load. */
export function takePendingChapter(): string | null {
  if (pending !== undefined) return pending;
  try {
    pending = sessionStorage.getItem(PENDING_KEY);
    if (pending) sessionStorage.removeItem(PENDING_KEY);
  } catch {
    pending = null;
  }
  return pending;
}
