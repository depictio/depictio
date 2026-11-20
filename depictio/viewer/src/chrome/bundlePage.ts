/**
 * The project page of a serverless static bundle, as the dashboard chrome sees it.
 *
 * A bundle has no `/projects/<id>` route, so the static runtime draws a
 * read-only project page itself, over the canvas, the way the Guide is drawn.
 * The runtime's entry provides this context; the chrome reads it to offer the
 * page (the sidebar's project row, the Settings drawer's project link) and App
 * reads it to lay the page over the canvas.
 *
 * Only the context lives here, so the server build carries a `createContext`
 * and nothing else: the page itself is imported by the static entry alone, and
 * outside a bundle `useBundleProjectPage()` is null and every reader is inert.
 */
import { createContext, useContext, type ReactNode } from 'react';

export interface BundleProjectPage {
  /** The project's name, for the row that opens the page. */
  name: string;
  open: boolean;
  openPage: () => void;
  closePage: () => void;
  /** The page, laid over the canvas while open. `tabName` names the way back. */
  render: (props: { tabName: string; onClose: () => void }) => ReactNode;
}

export const BundleProjectPageContext = createContext<BundleProjectPage | null>(null);

/** The bundle's project page, or null (a server build, or a bundle without a project). */
export function useBundleProjectPage(): BundleProjectPage | null {
  return useContext(BundleProjectPageContext);
}
