import { useEffect, useMemo, useState } from 'react';
import { allOutputs, useStudioStore } from '../state/useStudioStore';
import { parseIndex, sha256Hex, validateTool, type Diagnostic, type ExistenceIndices } from '../catalog/diagnostics';
import type { CatalogManifest } from '../catalog/catalog';
import type { KindsMap } from '../types';

let indicesPromise: Promise<ExistenceIndices> | null = null;

/** The vendored nf-core / EDAM indices, fetched once per session. A failed
 *  fetch yields empty sets, which skip the existence checks (as the CLI does
 *  with a missing index) rather than flagging every term. */
function loadIndices(): Promise<ExistenceIndices> {
  if (!indicesPromise) {
    const get = (name: string) =>
      fetch(`${import.meta.env.BASE_URL}${name}`)
        .then((r) => (r.ok ? r.text() : ''))
        .then(parseIndex)
        .catch(() => new Set<string>());
    indicesPromise = Promise.all([get('nf_core_modules.txt'), get('edam_terms.txt')]).then(
      ([nfCoreModules, edamTerms]) => ({ nfCoreModules, edamTerms }),
    );
  }
  return indicesPromise;
}

/** Live diagnostics for the current draft (see catalog/diagnostics.ts). */
export function useDiagnostics(kinds: KindsMap, catalog?: CatalogManifest): Diagnostic[] {
  const tool = useStudioStore((s) => s.tool);
  const output = useStudioStore((s) => s.output);
  const fixture = useStudioStore((s) => s.fixture);
  const renders = useStudioStore((s) => s.renders);
  const siblings = useStudioStore((s) => s.siblings);
  const activeIndex = useStudioStore((s) => s.activeIndex);
  const existing = useStudioStore((s) => s.existing);
  const [indices, setIndices] = useState<ExistenceIndices>({});
  // fixture text → sha256, for the cross-tool copy check.
  const [shas, setShas] = useState<Record<string, string>>({});

  useEffect(() => {
    let live = true;
    loadIndices().then((i) => live && setIndices(i));
    return () => {
      live = false;
    };
  }, []);

  const outputs = useMemo(
    () => allOutputs({ output, fixture, renders, siblings, activeIndex }),
    [output, fixture, renders, siblings, activeIndex],
  );

  useEffect(() => {
    let live = true;
    if (typeof crypto === 'undefined' || !crypto.subtle) return;
    for (const o of outputs) {
      const raw = o.fixture?.raw;
      if (raw && !(raw in shas))
        sha256Hex(raw)
          .then((h) => live && setShas((m) => ({ ...m, [raw]: h })))
          .catch(() => undefined);
    }
    return () => {
      live = false;
    };
  }, [outputs, shas]);

  return useMemo(
    () =>
      validateTool(
        { tool, kinds, catalog, indices, appendMode: Boolean(existing) },
        outputs.map((o) => ({ ...o, fixtureSha256: o.fixture?.raw ? shas[o.fixture.raw] : undefined })),
      ),
    [tool, kinds, catalog, indices, existing, outputs, shas],
  );
}
