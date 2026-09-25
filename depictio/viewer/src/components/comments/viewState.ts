import type {
  CommentSelection,
  CommentViewState,
  InteractiveFilter,
  StoredMetadata,
} from 'depictio-react-core';

/** Filter sources a chart, table, map or tree selection emits. */
const SELECTION_SOURCES = new Set([
  'scatter_selection',
  'table_selection',
  'map_selection',
  'tree_selection',
]);

export function isSelectionFilter(f: InteractiveFilter): boolean {
  return f.source != null && SELECTION_SOURCES.has(f.source);
}

function selectionSize(f: InteractiveFilter): number {
  const v = f.value;
  if (Array.isArray(v)) return v.length;
  return v == null ? 0 : 1;
}

/** The selection a component emits right now, summarised for a comment:
 *  its source, how many rows it holds, and the raw filters. Null when none. */
export function selectionFor(
  filters: InteractiveFilter[],
  componentIndex: string | null,
): CommentSelection | null {
  if (!componentIndex) return null;
  const own = filters.filter((f) => f.index === componentIndex && isSelectionFilter(f));
  if (own.length === 0) return null;
  const count = own.reduce((n, f) => n + selectionSize(f), 0);
  if (count === 0) return null;
  return { source: own[0].source, count, filters: own };
}

/** What a new comment attaches: every active filter plus the selection made
 *  on the component it is about. */
export function buildViewState(
  filters: InteractiveFilter[],
  componentIndex: string | null,
): CommentViewState {
  return { filters, selection: selectionFor(filters, componentIndex) };
}

/** Human label for a component, for group headers and the drawer title. */
export function componentLabel(meta: StoredMetadata | undefined, fallback?: string | null): string {
  const title = typeof meta?.title === 'string' ? meta.title.trim() : '';
  if (title) return title;
  if (fallback) return fallback;
  if (meta) return `Untitled ${meta.component_type.replace('_', ' ')}`;
  return 'Component';
}

export function selectionHint(selection: CommentSelection | null | undefined): string | null {
  if (!selection || !selection.count) return null;
  const noun =
    selection.source === 'table_selection'
      ? 'row'
      : selection.source === 'map_selection'
        ? 'feature'
        : selection.source === 'tree_selection'
          ? 'leaf'
          : 'point';
  const plural = selection.count === 1 ? noun : noun === 'leaf' ? 'leaves' : `${noun}s`;
  return `${selection.count} ${plural} selected`;
}
