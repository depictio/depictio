import React, { useMemo } from 'react';
import { CompactControlSlot, DepictioRangeSlider } from 'depictio-components';
import ComponentSkeleton from '../ComponentSkeleton';

import { InteractiveFilter, StoredMetadata } from '../../api';
import { InteractiveFrame, InteractiveTitle, interactiveAccentRaw } from './frame';
import { buildNumericScale, formatSliderValue, rangeSliderBounds } from './numericScale';
import { useColumnRange } from './useInteractiveData';

const RangeSliderRenderer: React.FC<{
  metadata: StoredMetadata;
  filters: InteractiveFilter[];
  onChange?: (filter: InteractiveFilter) => void;
  /** When true (e.g. inside an InteractiveGroupCard), drop the inner Paper
   *  and default tick marks to hidden — relies on the parent to provide the
   *  visual frame. */
  compact?: boolean;
}> = ({ metadata, filters, onChange, compact }) => {
  // Shared with the filter bar's slider on the same column (useInteractiveData).
  const { data: range, loading } = useColumnRange(metadata.dc_id, metadata.column_name);
  const bounds = useMemo(() => rangeSliderBounds(range), [range]);

  const filterEntry = filters.find((f) => f.index === metadata.index);
  const selectedValue =
    Array.isArray(filterEntry?.value) && filterEntry!.value.length === 2
      ? (filterEntry!.value as [number, number])
      : null;

  const marksNumber = (metadata.default_state as Record<string, unknown> | undefined)
    ?.marks_number as number | undefined;
  const scale = useMemo(
    // A continuous range slider anchors on its two ends unless the author asks
    // for more — that is what it has always drawn, and five labels do not fit
    // the Filters panel's width. A discrete scale ignores the number and marks
    // every value it has.
    () => (bounds ? buildNumericScale(bounds, { marksNumber: marksNumber ?? 2 }) : null),
    [bounds, marksNumber],
  );

  if (loading || !bounds || !scale) {
    return (
      <InteractiveFrame compact={compact}>
        <ComponentSkeleton variant="control" />
      </InteractiveFrame>
    );
  }

  return (
    <InteractiveFrame compact={compact}>
      <InteractiveTitle metadata={metadata} compact={compact} />
      <CompactControlSlot compact={compact}>
      <DepictioRangeSlider
        bare
        min={bounds.min}
        max={bounds.max}
        value={selectedValue || [bounds.min, bounds.max]}
        // Same accent the title row paints its icon and label with.
        color={interactiveAccentRaw(metadata)}
        step={scale.step}
        // Hand the canonical formatter down rather than letting the slider fall
        // back to its own copy: depictio-components cannot import from here (the
        // dependency runs the other way, and the Dash bundle uses it standalone),
        // so its mirror is a mirror, and this keeps the viewer reading the one in
        // numericScale.ts.
        format_value={formatSliderValue}
        marks={scale.marks}
        restrict_to_marks={scale.discrete}
        show_marks={
          // YAML wins; otherwise compact mode hides marks for higher density,
          // ungrouped renders show them — except on a discrete scale, where the
          // marks are the only thing saying which values the thumbs can reach.
          typeof metadata.show_marks === 'boolean'
            ? metadata.show_marks
            : !compact || scale.discrete
        }
        compact={compact}
        onChange={(next) =>
          onChange?.({
            index: metadata.index,
            value: next,
            column_name: metadata.column_name,
            interactive_component_type: 'RangeSlider',
            filter_expr: metadata.filter_expr,
          })
        }
      />
      </CompactControlSlot>
    </InteractiveFrame>
  );
};

export default RangeSliderRenderer;
