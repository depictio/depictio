import React, { useMemo } from 'react';
import { CompactControlSlot, DepictioMultiSelect } from 'depictio-components';
import ComponentSkeleton from '../ComponentSkeleton';

import { InteractiveFilter, StoredMetadata } from '../../api';
import { useAvailableSet, useFunnelState } from '../../availableValues';
import { orderCategoricalOptions } from './categoricalOptions';
import { FunnelAvailabilityBadge, FunnelOptionMarker } from './funnelDecorations';
import { INTERACTIVE_FRAME, InteractiveFrame, InteractiveTitle } from './frame';
import { useUniqueValues } from './useInteractiveData';

const MultiSelectRenderer: React.FC<{
  metadata: StoredMetadata;
  filters: InteractiveFilter[];
  onChange?: (filter: InteractiveFilter) => void;
  /** Compact rendering — drops the frame, relies on the parent group's card. */
  compact?: boolean;
}> = ({ metadata, filters, onChange, compact }) => {
  // Shared with every other control on the same column (see useInteractiveData).
  // A failed fetch leaves the select empty rather than replacing it.
  const { data: options, loading } = useUniqueValues(
    metadata.dc_id,
    metadata.column_name,
    metadata.filter_expr,
  );

  const selected =
    (filters.find((f) => f.index === metadata.index)?.value as string[]) || [];

  // Grey out values that the filter's source DC declares but that aren't
  // present in the dashboard's joined data — see `availableValues.tsx`.
  // With funnel filtering on, the set is live instead: values that no longer
  // lead to a non-empty result set under every OTHER active filter.
  // Sort order: available values first (so they're immediately visible),
  // then unavailable (greyed) values; alphabetical within each bucket using
  // a locale-aware natural compare so `Sample_2` sorts before `Sample_10`.
  const availableSet = useAvailableSet(metadata.dc_id, metadata.column_name, metadata.index);
  const funnel = useFunnelState(metadata.index);
  const optionItems = useMemo(
    () =>
      orderCategoricalOptions(options, availableSet).map((v) =>
        availableSet
          ? { value: v, label: v, disabled: !availableSet.has(v) }
          : { value: v, label: v },
      ),
    [options, availableSet],
  );

  // Skeleton on first load so this widget matches the rest of the dashboard's
  // loading treatment instead of flashing an empty select. Framed like the
  // loaded state, so the panel row doesn't gain a border on arrival.
  if (loading) {
    return (
      <InteractiveFrame compact={compact}>
        <ComponentSkeleton variant="control" />
      </InteractiveFrame>
    );
  }

  // Funnel decorations: a colored dot per option (still-filterable vs
  // exhausted) and an "n/N available" badge on the control itself.
  const funnelHighlight = funnel.active && availableSet !== null;
  const availableCount = funnelHighlight
    ? options.filter((v) => availableSet!.has(v)).length
    : null;

  return (
    <InteractiveFrame compact={compact}>
      <InteractiveTitle metadata={metadata} compact={compact} />
      <CompactControlSlot compact={compact}>
        <DepictioMultiSelect
          bare
          size={compact ? 'xs' : INTERACTIVE_FRAME.controlSize}
          column_name={metadata.column_name}
          options={optionItems}
          value={selected}
          placeholder={`Select ${metadata.column_name || 'values'}…`}
          renderOption={
            funnelHighlight
              ? ({ option }) => (
                  <FunnelOptionMarker
                    label={option.label}
                    available={availableSet!.has(option.value)}
                  />
                )
              : undefined
          }
          onChange={(next) =>
            onChange?.({
              index: metadata.index,
              value: next,
              column_name: metadata.column_name,
              interactive_component_type: metadata.interactive_component_type,
              filter_expr: metadata.filter_expr,
            })
          }
        />
        {funnelHighlight && (
          <FunnelAvailabilityBadge
            available={availableCount ?? 0}
            total={options.length}
            truncated={funnel.state?.truncated}
          />
        )}
      </CompactControlSlot>
    </InteractiveFrame>
  );
};

export default MultiSelectRenderer;
