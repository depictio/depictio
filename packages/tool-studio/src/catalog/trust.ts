/**
 * Which code the Studio may run without asking.
 *
 * A code-mode figure (`code`) and a recipe are Python, and Python here runs
 * under Pyodide on the page's main thread: it can reach `window`, the DOM and
 * same-origin storage. Code the author wrote in this session (the builder,
 * the recipe editor) is theirs to run; code that arrived from outside — a
 * `#draft=` link, an imported zip/folder/draft JSON, `toolStudio.load*` — is
 * someone else's, and is only run after the author has seen it and pressed
 * "Run this code" on its card.
 *
 * The flag (`_untrusted`) is runtime state: it survives a reload (the render
 * stays untrusted), and is never written to an export, a draft or a link.
 */
import type { OutputMeta, RenderSpec } from '../types';

/** True when this render carries code that must not run until the author says so. */
export function needsConsent(render: RenderSpec): boolean {
  return render.component === 'figure' && Boolean(render.code?.trim()) && render._untrusted === true;
}

/** An incoming render, as the store should hold it: code-mode figures marked
 *  untrusted, and any executed preview the sender attached dropped (it is
 *  derived data, and not ours). */
export function untrustedRender<R extends Omit<RenderSpec, 'uid'> & { uid?: string }>(render: R): R {
  const r = { ...render } as R & { _previewFigure?: unknown; _untrusted?: boolean };
  delete r._previewFigure;
  delete r._untrusted;
  if (r.component === 'figure' && typeof (r as { code?: unknown }).code === 'string') r._untrusted = true;
  return r;
}

/** An incoming output: its recipe (if any) marked untrusted, raw samples kept. */
export function untrustedOutput(output: OutputMeta): OutputMeta {
  if (!output.recipe) return output;
  return { ...output, recipe: { ...output.recipe, _untrusted: true } };
}

/** Runtime-only render fields that never leave the app. */
export function stripRenderRuntime<R extends object>(render: R): Omit<R, 'uid' | '_previewFigure' | '_untrusted'> {
  const { uid: _u, _previewFigure: _p, _untrusted: _t, ...rest } = render as R & {
    uid?: unknown;
    _previewFigure?: unknown;
    _untrusted?: unknown;
  };
  return rest as Omit<R, 'uid' | '_previewFigure' | '_untrusted'>;
}

/** The output as it is shared (draft, link): no raw recipe samples, no flags. */
export function stripOutputRuntime(output: OutputMeta): OutputMeta {
  if (!output.recipe) return output;
  const { inputs: _i, _untrusted: _t, ...recipe } = output.recipe;
  return { ...output, recipe };
}
