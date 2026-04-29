/**
 * Default card title format `<Aggregation> on <column>` — used both by the
 * live preview and by buildMetadata at save time, so the user-facing string
 * stays consistent whether they leave the title input blank or not.
 *
 * Mirrors the convention Dash uses in
 * depictio/dash/modules/interactive_component/utils.py:1477 for interactive
 * components (`f"{interactive_component_type} on {column_name}"`).
 */
import { cardMethodsForType } from '../aggFunctions';

export function autoCardTitle(
  aggregation: string | undefined | null,
  columnName: string | undefined | null,
  columnType?: string | null,
): string {
  if (!aggregation || !columnName) return '';
  const methods = cardMethodsForType(columnType || '');
  const friendly =
    methods.find((m) => m.value === aggregation)?.label ||
    aggregation
      .replace(/_/g, ' ')
      .replace(/\b\w/g, (c) => c.toUpperCase());
  return `${friendly} on ${columnName}`;
}
