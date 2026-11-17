/**
 * The coach: short, optional tours of one page each, drawn as cards that dim
 * nothing and block nothing. A chapter belongs to a page (its `route`) and to
 * the visitors it is written for (its `persona`).
 */

/** Who a chapter is written for. A guest explores a public or demo instance
 *  in a temporary session; a builder owns projects and dashboards. */
export type CoachPersona = 'guest' | 'builder';

/** What a chapter's text may depend on. */
export interface CoachContext {
  persona: CoachPersona;
  /** How long a guest's temporary session lasts, e.g. `24h`. */
  sessionTtl: string;
  /** A guest can sign in on this instance (see `canGuestSignIn`). */
  canSignIn: boolean;
}

export interface CoachStep {
  id: string;
  /** `data-tour-id` of the element the card points at. Null, or an element
   *  that is not on screen, draws the card on its own in the corner. */
  /** The element to point at, by `data-tour-id`; with several, the first
   *  drawn. None drawn floats the card. */
  target: string | readonly string[] | null;
  title: string;
  /** One or two sentences. `**bold**` and `` `code` `` are rendered. */
  body: string | ((ctx: CoachContext) => string);
  /** Kept only when this is true: a step about signing in needs a way to. */
  when?: (ctx: CoachContext) => boolean;
}

export interface CoachChapter {
  id: string;
  /** Bump to offer the chapter again to everyone who has seen it. */
  version: number;
  /** The page, as the eyebrow names it: "Dashboards", "Editor". */
  label: string;
  /** Iconify id of the chapter's mark. */
  icon: string;
  route: RegExp;
  persona: CoachPersona;
  /** The offer made on a first arrival: "New to Dashboards?". */
  offer: { title: string; body: string };
  /** Started only from the welcome card's journeys, never offered for its
   *  page: the page's own chapter is. */
  journeyOnly?: boolean;
  steps: CoachStep[];
}
