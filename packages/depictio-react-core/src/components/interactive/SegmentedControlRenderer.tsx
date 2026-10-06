import React, { useCallback, useMemo } from 'react';
import { Text, SegmentedControl } from '@mantine/core';
import { CompactControlSlot } from 'depictio-components';

import { InteractiveFilter, StoredMetadata } from '../../api';
import { useAvailableSet, useFunnelState } from '../../availableValues';
import ComponentSkeleton from '../ComponentSkeleton';
import { orderCategoricalOptions } from './categoricalOptions';
import { FunnelAvailabilityBadge, FunnelOptionMarker } from './funnelDecorations';
import { InteractiveFrame, InteractiveTitle } from './frame';
import { useUniqueValues } from './useInteractiveData';

/**
 * SegmentedControl renderer for the React viewer.
 *
 * Mirror of `depictio/dash/modules/interactive_component/utils.py:_build_select_component`
 * when interactive_component_type === "SegmentedControl". Reads unique column
 * values via `fetchUniqueValues`, then renders a Mantine `SegmentedControl`.
 *
 * Options come from `useUniqueValues`, the one cache every control on the same
 * (dc_id, column, filter_expr) shares — the panel's MultiSelect and the filter
 * bar's chips included.
 *
 * SegmentedControl is "one-of-N + optional null". On change emits
 *   { index, value: string | null, column_name, interactive_component_type: 'SegmentedControl' }
 *
 * Bigger-than-20-option columns degrade gracefully: we render a small dimmed
 * warning instead of a giant unusable segmented bar (visually impractical above
 * ~20 segments).
 */

const MAX_SEGMENTS = 20;

const SegmentedControlRenderer: React.FC<{
  metadata: StoredMetadata;
  filters: InteractiveFilter[];
  onChange?: (filter: InteractiveFilter) => void;
  /** Compact rendering — drops the frame, relies on the parent group's card. */
  compact?: boolean;
}> = ({ metadata, filters, onChange, compact }) => {
  const {
    data: options,
    loading,
    error,
  } = useUniqueValues(metadata.dc_id, metadata.column_name, metadata.filter_expr);

  const filterEntry = filters.find((f) => f.index === metadata.index);
  const selectedValue =
    typeof filterEntry?.value === 'string' ? (filterEntry!.value as string) : null;

  // Cross-DC available-values intersection — see `availableValues.tsx`. Marks
  // segments whose value isn't present in any other joined DC as disabled.
  // Available segments come first, then unavailable; locale-aware natural
  // sort within each bucket so `Sample_2` precedes `Sample_10`.
  const availableSet = useAvailableSet(metadata.dc_id, metadata.column_name, metadata.index);
  const funnel = useFunnelState(metadata.index);
  // With the funnel active, segments carry a colored dot: teal = still leads
  // to a non-empty result set, dimmed grey = exhausted by the other filters.
  const funnelHighlight = funnel.active && availableSet !== null;
  const data = useMemo(() => {
    const sorted = orderCategoricalOptions(options, availableSet);
    return sorted.map((v) => ({
      value: v,
      label: funnelHighlight ? (
        <FunnelOptionMarker label={v} available={availableSet!.has(v)} />
      ) : (
        v
      ),
      disabled: availableSet ? !availableSet.has(v) : false,
    }));
  }, [options, availableSet, funnelHighlight]);
  const availableCount = funnelHighlight
    ? options.filter((v) => availableSet!.has(v)).length
    : null;

  const handleChange = useCallback(
    (next: string) => {
      // Emit null when the user re-clicks the active segment (toggle off).
      // Mantine's SegmentedControl does not natively allow deselect, so the
      // value will always be one of `data`. Keep the typing union for callers.
      onChange?.({
        index: metadata.index,
        value: next,
        column_name: metadata.column_name,
        interactive_component_type: 'SegmentedControl',
        filter_expr: metadata.filter_expr,
      });
    },
    [onChange, metadata.index, metadata.column_name, metadata.filter_expr],
  );

  // Plain function rather than an inline component: declaring a component
  // inside the render body gives it a new identity every render, so React
  // unmounts and remounts the whole subtree on each state change.
  const frame = (children: React.ReactNode) => (
    <InteractiveFrame compact={compact}>
      <InteractiveTitle metadata={metadata} compact={compact} />
      <CompactControlSlot compact={compact}>{children}</CompactControlSlot>
    </InteractiveFrame>
  );

  if (error) {
    return frame(
        <Text size="xs" c="red">
          Failed to load options: {error}
        </Text>
      );
  }

  if (loading) {
    return frame(
        <ComponentSkeleton variant="control" withTitle={false} />
      );
  }

  if (data.length === 0) {
    return frame(
        <Text size="xs" c="dimmed">
          No values available for column "{metadata.column_name}".
        </Text>
      );
  }

  if (data.length > MAX_SEGMENTS) {
    return frame(
        <Text size="xs" c="dimmed">
          Too many options for SegmentedControl, use Select instead
        </Text>
      );
  }

  return frame(
      <>
      <SegmentedControl
        data={data}
        value={selectedValue ?? data[0]?.value}
        onChange={handleChange}
        color={metadata.icon_color || undefined}
        // One step below the panel's shared control size, deliberately. Every
        // other control is a single input; a segmented control is N labels
        // side by side, so at the same token it carries several times the ink
        // and reads as a slab next to its neighbours.
        size="xs"
        styles={{
          root: {
            // Sized to its content and centred, rather than stretched across
            // the panel. `1fr` tracks inside a `fit-content` grid all resolve
            // to the widest label, so "male" and "female" get equal cells that
            // fit "female" — which is what `fullWidth` cannot do, since that
            // stretches to the container instead.
            display: 'grid',
            gridTemplateColumns: `repeat(${data.length}, 1fr)`,
            width: 'fit-content',
            maxWidth: '100%',
            marginInline: 'auto',
          },
          // Long category names must cost width, not height: without this a
          // four-option control wraps its labels and the row grows past the
          // panel's fixed height.
          label: {
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          },
        }}
      />
      {funnelHighlight && (
        <FunnelAvailabilityBadge
          available={availableCount ?? 0}
          total={options.length}
          truncated={funnel.state?.truncated}
        />
      )}
      </>
    );
};

export default SegmentedControlRenderer;
