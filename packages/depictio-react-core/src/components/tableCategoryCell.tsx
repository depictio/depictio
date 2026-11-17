import React from 'react';
import type { ICellRendererParams } from 'ag-grid-community';

import { hasPinnedColors, pinnedCategoryColor } from '../categoryColors';
import type { CategoryColorSource } from '../categoryColors';

/**
 * A table cell that wears its category colour: a dot, then the value.
 *
 * Only a column the dashboard gives colours to (`category_colors`, own or
 * inherited) gets one, the same rule as a filter's chips: the dot is the
 * colour every figure draws that value in, so it carries a meaning. A value the
 * author did not list takes no dot, and a column without pinned colours is
 * left as plain text, since a colour handed out by position would read as a
 * meaning it does not have.
 */
export function pinnedColourColumns(
  source: CategoryColorSource | null | undefined,
  fields: readonly string[],
): Set<string> {
  const out = new Set<string>();
  for (const f of fields) if (hasPinnedColors(source, f)) out.add(f);
  return out;
}

/** Cell renderer reading the latest colour source through a ref, so a colour
 *  change repaints the cell without replacing the column definitions (which
 *  would reset the reader's sort). */
export function categoryDotCellRenderer(
  sourceRef: React.MutableRefObject<CategoryColorSource | null | undefined>,
  field: string,
) {
  const CategoryDotCell: React.FC<ICellRendererParams> = ({ value }) => {
    if (value === null || value === undefined || value === '') return null;
    const colour = pinnedCategoryColor(sourceRef.current, field, value);
    return (
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
        {colour && (
          <span
            aria-hidden
            data-testid="table-category-dot"
            style={{
              flex: '0 0 auto',
              width: 9,
              height: 9,
              borderRadius: '50%',
              background: colour,
            }}
          />
        )}
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{String(value)}</span>
      </span>
    );
  };
  return CategoryDotCell;
}
