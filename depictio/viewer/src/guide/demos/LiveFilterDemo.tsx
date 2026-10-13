/**
 * The Filters part's demo: one of the dashboard's own key figures and one of
 * its own filters, live.
 *
 * Both are drawn by the real `ComponentRenderer`, the card's value by the same
 * bulk endpoint the dashboard uses. What differs is where the filter state
 * lives: here, in the demo, so picking a value changes the number on screen
 * and nothing else — the dashboard's filters, the panel's count and what other
 * tabs remember are all left as they were.
 *
 * The two are copies under ids of their own, so nothing keyed on a component
 * id (the grid's height fitting, the inspector) mistakes them for the tiles
 * the canvas draws.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Badge, Box, Button, Group, SimpleGrid, Skeleton, Stack, Text } from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { Icon } from '@iconify/react';
import {
  AvailableFilterValuesProvider,
  bulkComputeCards,
  ComponentRenderer,
  countActiveFilters,
  enrichFilterWithDcId,
  InspectorProvider,
  mergeFiltersBySource,
  SaveGroupContext,
} from 'depictio-react-core';
import type { InteractiveFilter, StoredMetadata } from 'depictio-react-core';

import type { FilterDemoSource } from '../useGuideSources';

/** The dashboard's own debounce before a filter change refetches. */
const SETTLE_MS = 250;

const demoCopy = (m: StoredMetadata): StoredMetadata => ({ ...m, index: `guide-demo:${m.index}` });

const valueKey = (filters: InteractiveFilter[]) =>
  JSON.stringify(filters.map((f) => [f.index, f.source ?? null, f.value]));

interface CardState {
  value?: unknown;
  secondary?: Record<string, unknown>;
  /** The value with no filter: the N of "n / N". */
  whole?: unknown;
  loading: boolean;
  failed: boolean;
}

/** The card's value under `filters`, from the endpoint the dashboard uses. */
function useCardValue(
  dashboardId: string,
  cardIndex: string,
  filters: InteractiveFilter[],
): CardState {
  const [state, setState] = useState<CardState>({ loading: true, failed: false });
  const key = valueKey(filters);
  useEffect(() => {
    const ctrl = new AbortController();
    const unfiltered = countActiveFilters(filters) === 0;
    setState((s) => ({ ...s, loading: true }));
    bulkComputeCards(dashboardId, filters, [cardIndex], undefined, ctrl.signal)
      .then((res) => {
        const value = res.values?.[cardIndex];
        setState((s) => ({
          value,
          secondary: res.secondary_values?.[cardIndex],
          whole: unfiltered ? value : s.whole,
          loading: false,
          failed: false,
        }));
      })
      .catch((err) => {
        if (err?.name === 'AbortError') return;
        setState((s) => ({ ...s, loading: false, failed: true }));
      });
    return () => ctrl.abort();
    // `key` is the filters' identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dashboardId, cardIndex, key]);
  return state;
}

const fmt = (v: unknown) =>
  typeof v === 'number' ? v.toLocaleString(undefined, { maximumFractionDigits: 2 }) : String(v ?? '—');

export const LiveFilterDemo: React.FC<{ source: FilterDemoSource }> = ({ source }) => {
  const card = useMemo(() => demoCopy(source.card), [source.card]);
  const control = useMemo(() => demoCopy(source.control), [source.control]);
  const demoMetadata = useMemo(() => [control, card], [control, card]);

  const [filters, setFilters] = useState<InteractiveFilter[]>([]);
  const onFilterChange = useCallback(
    (update: InteractiveFilter) =>
      setFilters((prev) => mergeFiltersBySource(prev, enrichFilterWithDcId(update, [control]))),
    [control],
  );
  const [settled] = useDebouncedValue(filters, SETTLE_MS);
  const { value, secondary, whole, loading, failed } = useCardValue(
    source.dashboardId,
    source.card.index,
    settled,
  );
  const filtered = countActiveFilters(filters) > 0;
  const title = String(source.card.title || source.card.column_name || 'The figure');

  return (
    // Its own providers, empty: the demo must not read the dashboard's filter
    // funnel, nor offer the inspector or analysis groups on its copies.
    <InspectorProvider value={null}>
      <SaveGroupContext.Provider value={null}>
        <AvailableFilterValuesProvider dashboardMetadata={demoMetadata}>
          <Stack gap="sm" data-testid="guide-filter-demo">
            <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
              <Box className="depictio-guide-live" data-testid="guide-filter-demo-control">
                <ComponentRenderer
                  metadata={control}
                  filters={filters}
                  onFilterChange={onFilterChange}
                />
              </Box>
              <Box className="depictio-guide-live" h={150} data-testid="guide-filter-demo-card">
                <ComponentRenderer
                  metadata={card}
                  filters={settled}
                  cardValue={value}
                  cardSecondaryValues={secondary}
                  cardLoading={loading}
                />
              </Box>
            </SimpleGrid>
            <Group justify="space-between" gap="sm" wrap="wrap">
              <Group gap="xs" wrap="nowrap" style={{ minWidth: 0 }} aria-live="polite">
                <Text size="sm" c="dimmed" truncate>
                  {title}
                </Text>
                <Text size="md" fw={700} style={{ whiteSpace: 'nowrap' }} data-testid="guide-filter-readout">
                  {failed ? '—' : fmt(value)}
                  {filtered && whole !== undefined && whole !== value && (
                    <Text span size="sm" fw={500} c="dimmed">
                      {' / '}
                      {fmt(whole)}
                    </Text>
                  )}
                </Text>
                {filtered && (
                  // The badge a pinned section's header shows while it is filtered.
                  <Badge size="xs" variant="light" color="blue">
                    Filtered
                  </Badge>
                )}
              </Group>
              {/* The filter panel's own Reset: light at rest, filled orange
                  while there is something to clear. */}
              <Button
                leftSection={<Icon icon="bx:reset" width={12} />}
                color="orange"
                variant={filtered ? 'filled' : 'light'}
                size="compact-xs"
                onClick={() => setFilters([])}
              >
                Reset
              </Button>
            </Group>
            <Text size="xs" c="dimmed">
              {source.card.title ? `“${source.card.title}”` : 'The card'} and{' '}
              {source.control.title ? `“${source.control.title}”` : 'the filter'} from{' '}
              {source.tabLabel}. What you pick here stays here: the dashboard's own filters are
              untouched.
            </Text>
          </Stack>
        </AvailableFilterValuesProvider>
      </SaveGroupContext.Provider>
    </InspectorProvider>
  );
};

/** While the tab the demo comes from is fetched. */
export const LiveFilterDemoSkeleton: React.FC = () => (
  <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
    <Skeleton h={72} radius="md" />
    <Skeleton h={150} radius="md" />
  </SimpleGrid>
);
