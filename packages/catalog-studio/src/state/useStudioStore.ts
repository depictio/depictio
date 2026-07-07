import { create } from 'zustand';
import type { ParsedFixture, RenderSpec, ToolMeta, OutputMeta } from '../types';

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

const emptyTool: ToolMeta = { id: '', name: '' };
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
  addRender: (render) => set((s) => ({ renders: [...s.renders, render] })),
  updateRender: (uid, patch) =>
    set((s) => ({
      renders: s.renders.map((r) => (r.uid === uid ? ({ ...r, ...patch } as RenderSpec) : r)),
    })),
  removeRender: (uid) => set((s) => ({ renders: s.renders.filter((r) => r.uid !== uid) })),
  reset: () =>
    set({ step: 0, tool: { ...emptyTool }, output: { ...emptyOutput }, fixture: null, renders: [] }),
}));
