import type { InteractiveFilter } from '../../api';
import { clearedSelectionFilters, mapSelectionValues, ownSelection } from '../../selection';
import type { FloatingPanelKind } from './panelKinds';

/**
 * How many values one floating component currently holds selected.
 *
 * A map's selection is the values it filters on (`map_selection`). A
 * structure's is its residue pick, whose entries (entity, position range and,
 * on a complex, chain) read back as one selection through `ownSelection`: the
 * count there is 0 or 1 for a single-entity pick, never a residue count. A
 * genome browser's selection (`jbrowse_selection`, the tracks it has open) is
 * a view setting that travels with the tile, not a subset worth a badge on the
 * header, so a genome panel counts none and has nothing to clear.
 */
export function selectionCount(
  kind: FloatingPanelKind,
  filters: InteractiveFilter[],
  index: string,
): number {
  if (kind === 'genome') return 0;
  return kind === 'map'
    ? mapSelectionValues(filters, index).length
    : ownSelection(filters, index).count;
}

/**
 * The filter updates that clear one floating component's selection, in the
 * shape `onFilterChange` takes (an empty value removes the entry). Empty when
 * there is nothing to clear, so a caller can loop without checking first.
 */
export function clearSelectionFilters(
  kind: FloatingPanelKind,
  filters: InteractiveFilter[],
  index: string,
): InteractiveFilter[] {
  if (kind === 'genome') return [];
  if (kind === 'map') {
    return mapSelectionValues(filters, index).length === 0
      ? []
      : [{ index, value: [], source: 'map_selection' }];
  }
  return clearedSelectionFilters(ownSelection(filters, index).filters);
}
