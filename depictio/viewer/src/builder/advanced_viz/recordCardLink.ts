/**
 * Which components of a dashboard can drive a record card.
 *
 * A record card follows the selection another tile emits, and it honours two
 * sources only (`RecordCardConfig.selection_source`): `scatter_selection`,
 * which scatter figures and the selecting advanced_viz kinds emit, and
 * `table_selection`, which tables with row selection emit. Maps and image
 * galleries select too, but on sources the card ignores, so offering them here
 * would link the card to a tile it can never hear.
 *
 * The per-type rules mirror `supportsSelectionGrouping` and
 * `advancedVizSelectionColumn` in packages/depictio-react-core/src/selection.ts,
 * which are the source of truth for what the renderers actually emit. They are
 * not exported from the package, so keep this in step with them.
 */
import type { StoredMetadata } from 'depictio-react-core';

export type RecordCardSelectionSource = 'scatter_selection' | 'table_selection' | 'any';

export interface SelectionEmitter {
  /** What the card stores in `linked_component`: the component's tag when it
   *  has one, its index otherwise. */
  value: string;
  label: string;
  /** Short component-type label, shown next to the title in the picker. */
  typeLabel: string;
  source: Exclude<RecordCardSelectionSource, 'any'>;
  /** Column the emitted values belong to, when the component names one. */
  column: string | null;
  index: string;
  tag: string | null;
  dcId: string | null;
}

const str = (v: unknown): string | null => (typeof v === 'string' && v ? v : null);

/** The column an advanced_viz tile selects on, or null when it cannot select.
 *  Mirrors `advancedVizSelectionColumn` (see the module comment). The second
 *  return value tells "cannot select" apart from "selects, column unnamed". */
function advancedVizEmits(m: StoredMetadata): { emits: boolean; column: string | null } {
  const config = (m.config ?? {}) as Record<string, unknown>;
  if (config.selection_enabled !== true) return { emits: false, column: null };
  const named = str(config.selection_column);
  let column: string | null;
  switch (str(m.viz_kind)) {
    case 'embedding':
      column = named ?? str(config.sample_id_col);
      break;
    case 'profile':
      column = named ?? str(config.series_col);
      break;
    case 'scatter_xy':
    case 'genome_chord':
      column = named ?? str(config.label_col);
      break;
    case 'manhattan':
    case 'genome_view':
      column = named;
      break;
    default:
      return { emits: false, column: null };
  }
  return { emits: column !== null, column };
}

function emitterOf(m: StoredMetadata): Pick<SelectionEmitter, 'source' | 'column' | 'typeLabel'> | null {
  switch (m.component_type) {
    case 'table':
      if (!m.row_selection_enabled) return null;
      return {
        source: 'table_selection',
        column: str(m.row_selection_column),
        typeLabel: 'Table',
      };
    case 'figure':
      if (!m.selection_enabled) return null;
      if (m.visu_type !== 'scatter' && m.visu_type !== 'scatter_3d') return null;
      return {
        source: 'scatter_selection',
        column: str(m.selection_column),
        typeLabel: 'Scatter figure',
      };
    case 'advanced_viz': {
      const { emits, column } = advancedVizEmits(m);
      if (!emits) return null;
      return { source: 'scatter_selection', column, typeLabel: str(m.viz_kind) ?? 'Advanced viz' };
    }
    default:
      return null;
  }
}

/** Components of `metadata`, other than `selfIndex`, whose selection a record
 *  card can follow, in dashboard order. */
export function selectionEmitters(
  metadata: readonly StoredMetadata[],
  selfIndex: string | null,
): SelectionEmitter[] {
  const out: SelectionEmitter[] = [];
  for (const m of metadata) {
    const index = String(m.index);
    if (selfIndex != null && index === String(selfIndex)) continue;
    const emitter = emitterOf(m);
    if (!emitter) continue;
    const tag = str(m.tag);
    out.push({
      ...emitter,
      value: tag ?? index,
      label: str(m.title) ?? tag ?? index,
      index,
      tag,
      dcId: str(m.dc_id),
    });
  }
  return out;
}

/**
 * The emitter a stored `linked_component` points at.
 *
 * Dashboard YAML names the linked tile by tag, and the import may resolve that
 * to the component's index in the stored JSON (a YAML-authored component's
 * index usually is its tag, a UI-created one's is a UUID). Matching either
 * keeps the picker showing the right tile whichever form was stored.
 */
export function findEmitter(
  emitters: readonly SelectionEmitter[],
  linked: unknown,
): SelectionEmitter | undefined {
  const ref = str(linked);
  if (!ref) return undefined;
  return emitters.find((e) => e.value === ref || e.index === ref || e.tag === ref);
}
