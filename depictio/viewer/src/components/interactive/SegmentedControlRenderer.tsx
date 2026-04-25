import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Paper, Stack, Text, Group, SegmentedControl } from '@mantine/core';
import { Icon } from '@iconify/react';

import { fetchUniqueValues, InteractiveFilter, StoredMetadata } from '../../api';

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
}> = ({ metadata, filters, onChange }) => {
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
    const cacheKey = `${metadata.dc_id}|${metadata.column_name}`;
    let p = uniqueValuesCache.get(cacheKey);
    if (!p) {
      p = fetchUniqueValues(metadata.dc_id, metadata.column_name);
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
  }, [metadata.dc_id, metadata.column_name]);

  const filterEntry = filters.find((f) => f.index === metadata.index);
  const selectedValue =
    typeof filterEntry?.value === 'string' ? (filterEntry!.value as string) : null;

  const data = useMemo(
    () => options.map((v) => ({ value: v, label: v })),
    [options],
  );

  const displayTitle =
    metadata.title || (metadata.column_name ? `Filter on ${metadata.column_name}` : '');
  const iconCol = metadata.icon_color || 'var(--mantine-color-blue-6)';

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
      });
    },
    [onChange, metadata.index, metadata.column_name],
  );

  const Header = displayTitle ? (
    <Group gap="xs" align="center" wrap="nowrap">
      {metadata.icon_name && (
        <Icon
          icon={metadata.icon_name}
          width={18}
          height={18}
          style={{ color: iconCol, flexShrink: 0 }}
        />
      )}
      <Text fw={600} size="sm" style={{ color: 'var(--app-text-color, #1a1b1e)' }}>
        {displayTitle}
      </Text>
    </Group>
  ) : null;

  const Frame: React.FC<{ children: React.ReactNode }> = ({ children }) => (
    <Paper
      p="md"
      radius="md"
      shadow="xs"
      className="dashboard-component-hover"
      style={{
        backgroundColor: 'var(--app-surface-color, #ffffff)',
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        boxSizing: 'border-box',
      }}
    >
      <Stack gap="xs" style={{ flex: 1 }}>
        {Header}
        {children}
      </Stack>
    </Paper>
  );

  if (error) {
    return (
      <Frame>
        <Text size="xs" c="red">
          Failed to load options: {error}
        </Text>
      </Frame>
    );
  }

  if (loading) {
    return (
      <Frame>
        <Text size="xs" c="dimmed">
          Loading options…
        </Text>
      </Frame>
    );
  }

  if (data.length === 0) {
    return (
      <Frame>
        <Text size="xs" c="dimmed">
          No values available for column "{metadata.column_name}".
        </Text>
      </Frame>
    );
  }

  if (data.length > MAX_SEGMENTS) {
    return (
      <Frame>
        <Text size="xs" c="dimmed">
          Too many options for SegmentedControl, use Select instead
        </Text>
      </Frame>
    );
  }

  return (
    <Frame>
      <SegmentedControl
        data={data}
        value={selectedValue ?? data[0]?.value}
        onChange={handleChange}
        color={metadata.icon_color || undefined}
        fullWidth
        styles={{
          root: {
            backgroundColor: 'var(--app-surface-color, #ffffff)',
            borderColor: 'var(--app-border-color, #e9ecef)',
          },
        }}
      />
    </Frame>
  );
};

export default SegmentedControlRenderer;
