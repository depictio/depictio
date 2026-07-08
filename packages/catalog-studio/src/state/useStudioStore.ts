import { create } from 'zustand';
import type { ParsedFixture, RenderSpec, ToolMeta, OutputMeta } from '../types';
import { defaultRenderId } from '../viz/renderMeta';

let uidCounter = 0;
export const nextUid = () => `r${++uidCounter}`;

interface StudioState {
  step: number;
  tool: ToolMeta;
  output: OutputMeta;
  fixture: ParsedFixture | null;
  renders: RenderSpec[];

  setStep: (step: number) => void;
  setTool: (patch: Partial<ToolMeta>) => void;
  setOutput: (patch: Partial<OutputMeta>) => void;
  setFixture: (fixture: ParsedFixture | null) => void;
  addRender: (render: RenderSpec) => void;
  updateRender: (uid: string, patch: Partial<RenderSpec>) => void;
  removeRender: (uid: string) => void;
  reset: () => void;
}

const emptyTool: ToolMeta = { id: '', name: '', source: 'nf-core' };
const emptyOutput: OutputMeta = { slug: '', path_glob: '' };

export const useStudioStore = create<StudioState>((set) => ({
  step: 0,
  tool: { ...emptyTool },
  output: { ...emptyOutput },
  fixture: null,
  renders: [],

  setStep: (step) => set({ step }),
  setTool: (patch) => set((s) => ({ tool: { ...s.tool, ...patch } })),
  setOutput: (patch) => set((s) => ({ output: { ...s.output, ...patch } })),
  setFixture: (fixture) => set({ fixture }),
  addRender: (render) =>
    set((s) => {
      // Give every render a default, editable, tool-unique id so it's reusable
      // via `use: <tool>/<id>` out of the box.
      let spec = render;
      if (!spec.id) {
        const base = defaultRenderId(render) || 'render';
        const taken = new Set(s.renders.map((r) => r.id).filter(Boolean));
        let id = base;
        for (let n = 2; taken.has(id); n++) id = `${base}_${n}`;
        spec = { ...render, id } as RenderSpec;
      }
      return { renders: [...s.renders, spec] };
    }),
  updateRender: (uid, patch) =>
    set((s) => ({
      renders: s.renders.map((r) => (r.uid === uid ? ({ ...r, ...patch } as RenderSpec) : r)),
    })),
  removeRender: (uid) => set((s) => ({ renders: s.renders.filter((r) => r.uid !== uid) })),
  reset: () =>
    set({ step: 0, tool: { ...emptyTool }, output: { ...emptyOutput }, fixture: null, renders: [] }),
}));
