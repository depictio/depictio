import type { StoredMetadata } from '../../api';

/**
 * The title an interactive control shows when its author gave it none.
 *
 * Kept apart from `frame.tsx`, which re-exports it, because more than the
 * renderers need the string: the dashboard search lists a filter under the
 * name it carries on screen, and it runs as plain logic, with no React and no
 * stylesheet to load.
 */

/** Human label per control type, used to compose a default title. Each
 *  renderer used to spell its own ("MultiSelect on x", "Filter on x",
 *  "Slider on x", "Date range on x"), so four controls over the same kind of
 *  column announced themselves four different ways. */
const TYPE_LABELS: Record<string, string> = {
  MultiSelect: 'Select',
  Select: 'Select',
  SegmentedControl: 'Select',
  RangeSlider: 'Range',
  Slider: 'Value',
  DatePicker: 'Date range',
  DateRangePicker: 'Date range',
  Checkbox: 'Filter',
  Switch: 'Filter',
  Timeline: 'Timeline',
};

/** ``{Type} on {column}`` in one consistent shape. Exported so the builder
 *  writes the same string it would have rendered had the author left the title
 *  empty. */
export function defaultInteractiveTitle(
  interactiveType: string | undefined,
  columnName: string | undefined,
): string {
  if (!columnName) return '';
  return `${TYPE_LABELS[interactiveType || ''] || 'Filter'} on ${columnName}`;
}

/** Author's title, else the default above. */
export function interactiveTitle(metadata: StoredMetadata): string {
  if (metadata.title) return metadata.title;
  return defaultInteractiveTitle(metadata.interactive_component_type, metadata.column_name);
}
