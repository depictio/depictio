/**
 * Opening the run's parameters from inside a dashboard.
 *
 * The parameters live in the viewer's chrome (the Run parameters dialog, fed
 * by the project's run provenance), out of reach of the components a
 * dashboard draws. A text tile's `[All parameters](params:)` link dispatches
 * this event and the viewer's RunParametersHost answers it — the same
 * component-to-chrome path the panel toggles take.
 */
export const OPEN_RUN_PARAMETERS_EVENT = 'depictio:open-run-parameters';

export interface OpenRunParametersDetail {
  /** What to search the parameters for on opening (`params:dada2`); null for all. */
  query: string | null;
}

export function openRunParameters(query?: string | null): void {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(
    new CustomEvent<OpenRunParametersDetail>(OPEN_RUN_PARAMETERS_EVENT, {
      detail: { query: query || null },
    }),
  );
}
