/**
 * "Use this region": the genome browser as a source of a `genome_selection`.
 *
 * The browser has always followed a region another tile brushed. This is the
 * other direction: the reader drags a span on the ruler (or presses the
 * header button for the window on screen) and the span goes out as the same
 * filter pair a `genome_view` brush emits, on the columns of the tile's
 * `locus_from` (`locus_source`, resolved by the backend). Everything that
 * already follows a region (Plotly plots, GenomeSpy, tables) narrows to it.
 *
 * Coordinates: JBrowse regions are 0-based, end-exclusive; the filter pair
 * is 1-based inclusive, like the data columns it filters. Pure helpers plus
 * the rubberband plugin that adds the menu entry.
 */
import Plugin from '@jbrowse/core/Plugin';
import type PluginManager from '@jbrowse/core/PluginManager';

import type { InteractiveFilter, JBrowseLocusSource, StoredMetadata } from '../../api';
import {
  clearedSelectionFilters,
  genomePosFilterIndex,
  genomeRegionFilters,
  isRegionFilter,
  ownSelection,
} from '../../selection';

/** A stretch of one contig as JBrowse reports it (0-based, end-exclusive). */
export interface JBrowseRegion {
  refName: string;
  start: number;
  end: number;
}

const finite = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n);

/**
 * The filter pair for `region`, on the columns `locusSource` names. `null`
 * (or a region with no readable span) gives the cleared pair.
 *
 * The entries carry `locusSource.dc_id`, not the tile's own collection (the
 * manifest of tracks): followers recognise a region by the collection whose
 * columns it filters, and the backend resolves it through that id.
 */
export function regionFiltersFor(
  locusSource: JBrowseLocusSource,
  metadata: Pick<StoredMetadata, 'index'>,
  region: JBrowseRegion | null,
): InteractiveFilter[] {
  const usable =
    region && region.refName && finite(region.start) && finite(region.end) && region.end > region.start
      ? region
      : null;
  return genomeRegionFilters(
    { index: metadata.index, component_type: 'jbrowse', dc_id: locusSource.dc_id },
    locusSource.chrom_column,
    locusSource.start_column,
    usable
      ? {
          chroms: [usable.refName],
          range: [Math.max(1, Math.floor(usable.start) + 1), Math.ceil(usable.end)],
        }
      : null,
  );
}

/** The non-empty `genome_selection` entries this tile emitted (both halves). */
export function ownRegionFilters(
  filters: readonly InteractiveFilter[],
  index: string,
): InteractiveFilter[] {
  return ownSelection(filters, index).filters.filter(isRegionFilter);
}

/** Whether the tile's own region is in force (drives the button's state). */
export function isOwnRegion(filters: readonly InteractiveFilter[], index: string): boolean {
  return ownRegionFilters(filters, index).length > 0;
}

/** The cleared form of the tile's own region entries. */
export function clearOwnRegion(
  filters: readonly InteractiveFilter[],
  index: string,
): InteractiveFilter[] {
  return clearedSelectionFilters(ownRegionFilters(filters, index));
}

/**
 * The filters a tile follows a region from: the dashboard's, minus the pair
 * the tile emitted itself (both halves). Without this the tile would
 * navigate onto the region it just took from its own view.
 */
export function withoutOwnRegion(
  filters: readonly InteractiveFilter[],
  index: string,
): InteractiveFilter[] {
  const posIndex = genomePosFilterIndex(index);
  return filters.filter((f) => !(isRegionFilter(f) && (f.index === index || f.index === posIndex)));
}

/**
 * The region the tile's own pair describes, to draw it as a band. Null unless
 * both halves are in force (a contig with no range is not a band).
 */
export function ownRegionOf(
  filters: readonly InteractiveFilter[],
  index: string,
): JBrowseRegion | null {
  const posIndex = genomePosFilterIndex(index);
  let refName: string | null = null;
  let range: [number, number] | null = null;
  for (const f of ownRegionFilters(filters, index)) {
    if (!Array.isArray(f.value)) continue;
    if (f.index === index && f.value.length === 1) refName = String(f.value[0]);
    else if (f.index === posIndex && f.value.length === 2) {
      const lo = Number(f.value[0]);
      const hi = Number(f.value[1]);
      if (finite(lo) && finite(hi) && hi >= lo) range = [lo, hi];
    }
  }
  if (!refName || !range) return null;
  return { refName, start: Math.max(0, range[0] - 1), end: range[1] };
}

/** What a rubberband selection hands over (`getSelectedRegions`). */
export type SelectedRegion = JBrowseRegion & { assemblyName?: string };

/** Where the plugin finds the tile's emitter; `null` hides the menu entry
 *  (a tile with no `locus_source`, or a view that is going away). */
export interface RegionSelectHandle {
  current: ((region: SelectedRegion) => void) | null;
}

/** The slice of the LinearGenomeView model the menu entry reads. */
interface RubberbandView {
  leftOffset: unknown;
  rightOffset: unknown;
  rubberBandMenuItems: () => unknown[];
  getSelectedRegions: (left: unknown, right: unknown) => SelectedRegion[];
}

/** The slice of a pluggable element the extension point passes. */
interface PluggableLike {
  name?: string;
  stateModel?: {
    views: (fn: (self: RubberbandView) => Record<string, unknown>) => unknown;
  };
}

/**
 * A JBrowse plugin adding "Use this region" to the rubberband menu of the
 * linear genome view. JBrowse has no extension point for that menu, so the
 * view's state model is extended the way `plugin-grid-bookmark` does it:
 * `rubberBandMenuItems` is overridden to append the entry.
 *
 * Built per tile: each tile has its own plugin manager, and the entry reaches
 * the tile's emitter through `handle`, read when the menu opens (so a
 * `locus_source` that arrives after the view was built still counts).
 */
export function createRegionSelectPlugin(handle: RegionSelectHandle) {
  return class DepictioRegionSelectPlugin extends Plugin {
    name = 'DepictioRegionSelectPlugin';

    install(pluginManager: PluginManager) {
      pluginManager.addToExtensionPoint(
        'Core-extendPluggableElement',
        (element: PluggableLike) => {
          if (element.name === 'LinearGenomeView' && element.stateModel) {
            element.stateModel = element.stateModel.views((self) => {
              const superItems = self.rubberBandMenuItems;
              return {
                rubberBandMenuItems() {
                  const items = superItems();
                  const emit = handle.current;
                  if (!emit) return items;
                  return [
                    ...items,
                    {
                      label: 'Use this region',
                      onClick: () => {
                        const [region] = self.getSelectedRegions(self.leftOffset, self.rightOffset);
                        if (region) emit(region);
                      },
                    },
                  ];
                },
              };
            }) as PluggableLike['stateModel'];
          }
          return element;
        },
      );
    }
  };
}
