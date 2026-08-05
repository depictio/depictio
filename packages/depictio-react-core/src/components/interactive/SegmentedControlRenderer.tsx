import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Text, SegmentedControl } from '@mantine/core';
import { CompactControlSlot } from 'depictio-components';

import { fetchUniqueValues, InteractiveFilter, StoredMetadata } from '../../api';
import { useAvailableSet } from '../../availableValues';
import ComponentSkeleton from '../ComponentSkeleton';
import { INTERACTIVE_FRAME, InteractiveFrame, InteractiveTitle } from './frame';

/**
 * SegmentedControl renderer for the React viewer.
 *
 * Mirror of `depictio/dash/modules/interactive_component/utils.py:_build_select_component`
 * when interactive_component_type === "SegmentedControl". Reads unique column
 * values via `fetchUniqueValues`, then renders a Mantine `SegmentedControl`.
 *
 * Mirrors the data-fetch + module-level cache pattern used by MultiSelectRenderer
 * in ComponentRenderer.tsx so multiple renderers on the same (dc_id, column) share
 * one in-flight fetch. The cache here is local — defined separately because we
 * cannot edit ComponentRenderer.tsx to share the existing one. Each (dc_id,
 * column) pair will fetch up to twice across renderer flavors, which is
 * negligible and the result is then cached for the page lifetime.
 *
 * SegmentedControl is "one-of-N + optional null". On change emits
 *   { index, value: string | null, column_name, interactive_component_type: 'SegmentedControl' }
 *
 * Bigger-than-20-option columns degrade gracefully: we render a small dimmed
 * warning instead of a giant unusable segmented bar (visually impractical above
 * ~20 segments).
 */

const MAX_SEGMENTS = 20;

// Module-level cache for unique-values fetches. Keyed by `${dcId}|${column}`.
const uniqueValuesCache = new Map<string, Promise<string[]>>();

const SegmentedControlRenderer: React.FC<{
  metadata: StoredMetadata;
  filters: InteractiveFilter[];
  onChange?: (filter: InteractiveFilter) => void;
  /** Compact rendering — drops the frame, relies on the parent group's card. */
  compact?: boolean;
}> = ({ metadata, filters, onChange, compact }) => {
  const [options, setOptions] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    if (!metadata.dc_id || !metadata.column_name) {
      setLoading(false);
      return;
    }
    const cacheKey = `${metadata.dc_id}|${metadata.column_name}|${metadata.filter_expr || ''}`;
    let p = uniqueValuesCache.get(cacheKey);
    if (!p) {
      p = fetchUniqueValues(metadata.dc_id, metadata.column_name, metadata.filter_expr);
      uniqueValuesCache.set(cacheKey, p);
    }
    p.then((values) => {
      if (mountedRef.current) setOptions(values);
    })
      .catch((err) => {
        console.warn('[SegmentedControlRenderer] fetchUniqueValues failed:', err);
        // Remove from cache on error so next mount retries.
        uniqueValuesCache.delete(cacheKey);
        if (mountedRef.current) {
          setError(err instanceof Error ? err.message : String(err));
        }
      })
      .finally(() => {
        if (mountedRef.current) setLoading(false);
      });

    return () => {
      mountedRef.current = false;
    };
  }, [metadata.dc_id, metadata.column_name, metadata.filter_expr]);

  const filterEntry = filters.find((f) => f.index === metadata.index);
  const selectedValue =
    typeof filterEntry?.value === 'string' ? (filterEntry!.value as string) : null;

  // Cross-DC available-values intersection — see `availableValues.tsx`. Marks
  // segments whose value isn't present in any other joined DC as disabled.
  // Available segments come first, then unavailable; locale-aware natural
  // sort within each bucket so `Sample_2` precedes `Sample_10`.
  const availableSet = useAvailableSet(metadata.dc_id, metadata.column_name);
  const data = useMemo(() => {
    const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' });
    const sorted = [...options].sort((a, b) => {
      if (availableSet) {
        const aAvail = availableSet.has(a);
        const bAvail = availableSet.has(b);
        if (aAvail !== bAvail) return aAvail ? -1 : 1;
      }
      return collator.compare(a, b);
    });
    return sorted.map((v) => ({
      value: v,
      label: v,
      disabled: availableSet ? !availableSet.has(v) : false,
    }));
  }, [options, availableSet]);

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
    );
};

export default SegmentedControlRenderer;
