/**
 * Serve Monaco from the app itself, for the figure Code Mode editor.
 *
 * `@monaco-editor/react` fetches Monaco from cdn.jsdelivr.net unless it is handed
 * an instance. The CSP the API and nginx send (`script-src 'self'`) refuses that
 * script, so the editor stayed on "Loading..." forever: no code shown, and
 * Execute Code had nothing to run. The Vite dev server sends no CSP, which is
 * why it only broke on a served bundle.
 *
 * Only the editor core and the Python grammar are bundled, not the ~80 other
 * languages. Python needs no language worker (its highlighting runs in the
 * main thread), so the editor worker is the only one started. It is a
 * same-origin chunk, which `worker-src 'self' blob:` allows.
 */
import { loader } from '@monaco-editor/react';
import * as monaco from 'monaco-editor/esm/vs/editor/editor.api';
import 'monaco-editor/esm/vs/basic-languages/python/python.contribution';
import EditorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker';

(self as unknown as { MonacoEnvironment: { getWorker: () => Worker } }).MonacoEnvironment = {
  getWorker: () => new EditorWorker(),
};

loader.config({ monaco });
