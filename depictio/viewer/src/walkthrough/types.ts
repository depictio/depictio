/** Multi-page, route-aware walkthrough definitions used by `Walkthrough.tsx`.
 *  A walkthrough is an ordered list of steps; each step optionally anchors to
 *  a DOM element (via `data-tour-id`) and declares the route it expects.
 *
 *  When the next step's route ≠ the current route, the engine hides the
 *  popover and waits for natural navigation — see `useWalkthrough.ts`.
 */
export type StepPosition = 'top' | 'bottom' | 'left' | 'right';

export interface WalkthroughStep {
  /** Stable ID — used in analytics + storage debugging. */
  id: string;
  /** `data-tour-id` value to anchor to. `null` for centered welcome/end cards. */
  target: string | null;
  /** Route guard. When set, the step is only eligible on a matching path. */
  route?: RegExp;
  title: string;
  body: string;
  position?: StepPosition;
  /** When true, the spotlight cutout allows clicks through to the target so
   *  the user can complete the action themselves (e.g. clicking the
   *  "Create dashboard" button to advance). The popover stays open with a
   *  "waiting for click" hint. */
  awaitClick?: boolean;
}

export interface WalkthroughDefinition {
  /** Identifies the walkthrough in localStorage and the user menu. */
  id: 'public' | 'builder';
  /** Bump to force re-show after editing steps. */
  version: string;
  /** Human label for the user menu "Take the tour" item. */
  label: string;
  steps: WalkthroughStep[];
}

export type WalkthroughStatus = 'pending' | 'in-progress' | 'completed' | 'skipped';

export interface WalkthroughState {
  status: WalkthroughStatus;
  step: number;
  version: string;
}
