import { useUiStore } from '../../store/useUiStore';

/** Query parameter that deep-links a thread: `?thread=<id>` on a dashboard
 *  URL opens the comments drawer on it. */
export const THREAD_QUERY_PARAM = 'thread';

/** Opens the comments drawer on the whole tab with `threadId` focused and
 *  scrolled into view. The drawer reloads the tab's threads when the id is
 *  not among them yet (a thread an agent team just wrote). */
export function openCommentThread(threadId: string): void {
  useUiStore.setState((s) => ({
    commentsOpen: true,
    commentsScope: 'tab',
    focusedThreadId: threadId,
    threadScrollRequest: s.threadScrollRequest + 1,
  }));
}

/** The thread id of a `?thread=` deep link on the current URL, if any. */
export function threadFromUrl(): string | null {
  try {
    return new URLSearchParams(window.location.search).get(THREAD_QUERY_PARAM) || null;
  } catch {
    return null;
  }
}

/** Drops `?thread=` from the URL once served, so switching tabs or
 *  reloading does not reopen it. */
export function clearThreadFromUrl(): void {
  try {
    const url = new URL(window.location.href);
    if (!url.searchParams.has(THREAD_QUERY_PARAM)) return;
    url.searchParams.delete(THREAD_QUERY_PARAM);
    window.history.replaceState(window.history.state, '', url.toString());
  } catch {
    // An URL we cannot rewrite only means the link reopens on reload.
  }
}
