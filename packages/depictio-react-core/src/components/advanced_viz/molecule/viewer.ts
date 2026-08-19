// 3D molecular viewer behind a strict interface (adapted from the
// weber8thomas/claurdalie StructureViewer adapter).
//
// Dynamically imported (heavy, WebGL) so the main viewer bundle/cold-start
// are untouched, and swappable (Mol*/NGL) without touching the renderer.
// Prototype scope: a single static model with color-mode / representation
// switching, live theme sync, reset view and PNG snapshot. Multi-model
// comparison, residue picking/highlighting and deviation colouring exist in
// the prior-work adapter and can be ported when needed — the interface keeps
// the array-of-models signature so that stays a drop-in.

import { TAB10_PALETTE } from '../../../colors';

export interface ViewerModel {
  id: string;
  /** Raw structure text (PDB or mmCIF — see `format`). */
  data: string;
  format: 'pdb' | 'mmcif';
}

export type ColorMode = 'spectrum' | 'chain' | 'plddt';
export type Representation = 'cartoon' | 'trace' | 'stick' | 'sphere';

export interface StructureViewer {
  /** Reconcile the displayed set of models. `fit` re-centers the camera. */
  setModels(models: ViewerModel[], fit?: boolean): void;
  setColorMode(mode: ColorMode): void;
  setRepresentation(rep: Representation): void;
  /** Live theme sync — the dashboard can toggle light/dark after creation. */
  setDark(dark: boolean): void;
  resetView(): void;
  /** PNG data URL of the current view, or null if unavailable. */
  snapshot(): string | null;
  resize(): void;
  dispose(): void;
}

/** AlphaFold-style pLDDT confidence bands (blue = high, orange = very low).
 *  Domain-standard ramp (EBI/DeepMind convention) — deliberately not themed. */
function plddtColor(b: number): string {
  if (b >= 90) return '#0053d6';
  if (b >= 70) return '#65cbf3';
  if (b >= 50) return '#ffdb13';
  return '#ff7d45';
}

function hslHex(h: number, s = 0.7, l = 0.5): string {
  const f = (n: number) => {
    const k = (n + h * 12) % 12;
    const c = l - s * Math.min(l, 1 - l) * Math.max(-1, Math.min(k - 3, 9 - k, 1));
    return Math.round(255 * c)
      .toString(16)
      .padStart(2, '0');
  };
  return `#${f(0)}${f(8)}${f(4)}`;
}

const CHAIN_COLORS = TAB10_PALETTE.slice(0, 6);

// 3Dmol canvas backgrounds for the two Mantine color schemes. The canvas is
// WebGL — CSS variables can't reach it — so these mirror the Mantine body
// backgrounds (dark.7 / white) rather than introducing a new color.
const BG_DARK = '#1a1b1e';
const BG_LIGHT = '#ffffff';

interface Entry {
  glModel: { setStyle: (sel: unknown, style: unknown, add?: boolean) => void };
  resiMin: number;
  resiMax: number;
}

export async function createStructureViewer(
  container: HTMLElement,
  opts: { dark: boolean },
): Promise<StructureViewer> {
  const $3Dmol = await import('3dmol');
  const viewer = $3Dmol.createViewer(container, {
    backgroundColor: opts.dark ? BG_DARK : BG_LIGHT,
  });

  const entries = new Map<string, Entry>();
  let order: string[] = [];
  let colorMode: ColorMode = 'spectrum';
  let representation: Representation = 'cartoon';

  const colorProps = (e: Entry) => {
    switch (colorMode) {
      case 'chain':
        return {
          colorfunc: (a: { chain?: string }) => {
            const c = (a.chain ?? 'A').charCodeAt(0);
            return CHAIN_COLORS[c % CHAIN_COLORS.length];
          },
        };
      case 'plddt':
        // pLDDT lives in the B-factor column (AlphaFold/ESMFold convention).
        return { colorfunc: (a: { b?: number }) => plddtColor(typeof a.b === 'number' ? a.b : 0) };
      case 'spectrum':
      default:
        return {
          colorfunc: (a: { resi?: number }) => {
            const span = e.resiMax - e.resiMin || 1;
            const t = ((a.resi ?? e.resiMin) - e.resiMin) / span;
            return hslHex(0.66 * (1 - t)); // blue(N) -> red(C)
          },
        };
    }
  };

  const repStyle = (e: Entry) => {
    const c = colorProps(e);
    // A thin backbone line underlays the ribbon representations so a structure
    // is always visible even when triangulated cartoon geometry isn't produced
    // (very short peptides, coordinate-only models, software WebGL).
    switch (representation) {
      case 'trace':
        return { cartoon: { style: 'trace', thickness: 0.5, ...c }, line: { ...c } };
      case 'stick':
        return { stick: { radius: 0.15, ...c } };
      case 'sphere':
        return { sphere: { scale: 0.28, ...c } };
      case 'cartoon':
      default:
        return { cartoon: { arrows: true, ...c }, line: { ...c } };
    }
  };

  const restyle = () => {
    for (const id of order) {
      const e = entries.get(id);
      if (e) e.glModel.setStyle({}, repStyle(e));
    }
    viewer.render();
  };

  return {
    setModels(models: ViewerModel[], fit = false) {
      const had = entries.size;
      viewer.removeAllModels();
      entries.clear();
      order = [];
      for (const m of models) {
        const glModel = viewer.addModel(m.data, m.format === 'mmcif' ? 'cif' : 'pdb');
        const cas = (
          glModel as unknown as { selectedAtoms: (s: unknown) => Array<{ resi: number }> }
        ).selectedAtoms({ atom: 'CA' });
        const resis = cas.map((a) => a.resi);
        entries.set(m.id, {
          glModel: glModel as Entry['glModel'],
          resiMin: resis.length ? Math.min(...resis) : 0,
          resiMax: resis.length ? Math.max(...resis) : 0,
        });
        order.push(m.id);
      }
      restyle();
      if (fit || had === 0) viewer.zoomTo();
      viewer.render();
    },

    setColorMode(mode: ColorMode) {
      if (mode === colorMode) return;
      colorMode = mode;
      restyle();
    },

    setRepresentation(rep: Representation) {
      if (rep === representation) return;
      representation = rep;
      restyle();
    },

    setDark(dark: boolean) {
      viewer.setBackgroundColor(dark ? BG_DARK : BG_LIGHT, 1);
      viewer.render();
    },

    resetView() {
      viewer.zoomTo();
      viewer.render();
    },

    snapshot() {
      try {
        return (viewer as unknown as { pngURI: () => string }).pngURI();
      } catch {
        return null;
      }
    },

    resize() {
      viewer.resize();
      viewer.render();
    },

    dispose() {
      try {
        viewer.clear();
      } catch {
        /* already torn down */
      }
    },
  };
}
