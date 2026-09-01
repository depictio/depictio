/**
 * The dashboard's analysis state as one object — the TypeScript mirror of
 * `depictio/models/models/analysis_state.py`.
 *
 * Today the pieces live apart: active filters in the viewer's React state,
 * selection groups and colour-by in localStorage, the funnel stage order in the
 * funnel modal. `buildAnalysisState` gathers them into the shape the server
 * accepts for notebook export and component embeds. The committed JSON schema
 * (`analysis_state.schema.json`) is the contract; `analysisState.test.ts`
 * validates what this builder produces against it.
 */
import type { InteractiveFilter } from './api';
import type { ColorByState, GroupingDisplay, SelectionGroup } from './selectionGroups';
import type { PanelSpec } from './splitPanels';

export const ANALYSIS_STATE_VERSION = 1 as const;

export interface AnalysisFilterMetadata {
  dc_id?: string | null;
  column_name?: string | null;
  interactive_component_type?: string | null;
  selection_column?: string | null;
  filter_expr?: string | null;
}

export interface AnalysisFilter {
  index: string;
  value?: unknown;
  column_name?: string | null;
  interactive_component_type?: string | null;
  source?: string | null;
  filter_expr?: string | null;
  metadata?: AnalysisFilterMetadata | null;
}

export interface AnalysisGroup {
  id: string;
  name: string;
  color: string;
  dc_id?: string | null;
  column_name: string;
  values: string[];
  created_at: number;
  filter_active: boolean;
}

export interface AnalysisColorBy {
  kind: 'none' | 'groups' | 'column';
  column_name?: string | null;
}

export interface AnalysisFunnel {
  enabled: boolean;
  stage_order: string[];
}

export interface AnalysisSplitPanel {
  name: string;
  color?: string | null;
  constraints: AnalysisFilter[];
}

export interface AnalysisContext {
  dashboard_id: string;
  family_id?: string | null;
  theme: 'light' | 'dark';
}

export interface AnalysisState {
  version: typeof ANALYSIS_STATE_VERSION;
  filters: AnalysisFilter[];
  groups: AnalysisGroup[];
  color_by: AnalysisColorBy;
  display_mode: GroupingDisplay;
  show_other: boolean;
  show_overall: boolean;
  compare_in_cards: boolean;
  funnel: AnalysisFunnel;
  split_panels: AnalysisSplitPanel[];
  context: AnalysisContext;
}

export function toAnalysisFilter(f: InteractiveFilter): AnalysisFilter {
  const out: AnalysisFilter = { index: String(f.index), value: f.value ?? null };
  if (f.column_name !== undefined) out.column_name = f.column_name;
  if (f.interactive_component_type !== undefined) {
    out.interactive_component_type = f.interactive_component_type;
  }
  if (f.source !== undefined) out.source = f.source;
  if (f.filter_expr !== undefined) out.filter_expr = f.filter_expr;
  if (f.metadata) {
    out.metadata = {
      dc_id: f.metadata.dc_id ?? null,
      column_name: f.metadata.column_name ?? null,
      interactive_component_type: f.metadata.interactive_component_type ?? null,
      selection_column: f.metadata.selection_column ?? null,
      filter_expr: f.metadata.filter_expr ?? null,
    };
  }
  return out;
}

export function toAnalysisGroup(g: SelectionGroup): AnalysisGroup {
  return {
    id: g.id,
    name: g.name,
    color: g.color,
    dc_id: g.dcId ?? null,
    column_name: g.columnName,
    values: [...g.values],
    created_at: g.createdAt,
    filter_active: g.filterActive,
  };
}

export function toAnalysisColorBy(c: ColorByState): AnalysisColorBy {
  if (c.kind === 'column') return { kind: 'column', column_name: c.columnName };
  return { kind: c.kind };
}

export interface BuildAnalysisStateInput {
  /** The filters the render endpoints receive: user filters plus group projections. */
  filters: InteractiveFilter[];
  groups: SelectionGroup[];
  colorBy: ColorByState;
  displayMode: GroupingDisplay;
  showOther: boolean;
  showOverall: boolean;
  compareInCards: boolean;
  funnel: { enabled: boolean; order: string[] };
  splitPanels: PanelSpec[];
  dashboardId: string;
  familyId?: string | null;
  theme: 'light' | 'dark';
}

export function buildAnalysisState(input: BuildAnalysisStateInput): AnalysisState {
  return {
    version: ANALYSIS_STATE_VERSION,
    filters: input.filters.map(toAnalysisFilter),
    groups: input.groups.map(toAnalysisGroup),
    color_by: toAnalysisColorBy(input.colorBy),
    display_mode: input.displayMode,
    show_other: input.showOther,
    show_overall: input.showOverall,
    compare_in_cards: input.compareInCards,
    funnel: { enabled: input.funnel.enabled, stage_order: [...input.funnel.order] },
    split_panels: input.splitPanels.map((p) => ({
      name: p.name,
      color: p.color ?? null,
      constraints: p.constraints.map(toAnalysisFilter),
    })),
    context: {
      dashboard_id: input.dashboardId,
      family_id: input.familyId ?? null,
      theme: input.theme,
    },
  };
}
