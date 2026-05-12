/**
 * Compact funnel widget showing cumulative row counts per target DC after
 * each step in the global-filter chain. Hover a step → which filter caused
 * the narrowing.
 */

import React, { useEffect, useState } from 'react';
import { Group, Stack, Text, Tabs, Tooltip, Skeleton } from '@mantine/core';
import { Icon } from '@iconify/react';

import {
  computeFunnel,
  type FunnelResponse,
  type FunnelStep,
  type FunnelTargetDC,
  type GlobalFilterDef,
} from '../../api';

export interface FunnelWidgetProps {
  parentDashboardId: string;
  /** Definitions of all active global filters. Used to label hover tooltips. */
  definitions: GlobalFilterDef[];
  /** Steps to compute. Empty steps + a single target DC still yields N₀. */
  steps: FunnelStep[];
  /** DCs to compute the funnel against (typically every DC referenced by a
   *  global filter's `links`). */
  targetDcs: FunnelTargetDC[];
  /** Tick to force refresh — e.g. on global filter value change. */
  refreshTick?: number;
}

const FETCH_DEBOUNCE_MS = 300;

function formatCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

const FunnelWidget: React.FC<FunnelWidgetProps> = ({
  parentDashboardId,
  definitions,
  steps,
  targetDcs,
  refreshTick = 0,
}) => {
  const [data, setData] = useState<FunnelResponse | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (targetDcs.length === 0) {
      setData(null);
      return;
    }
    const handle = setTimeout(() => {
      setLoading(true);
      computeFunnel(parentDashboardId, steps, targetDcs)
        .then((res) => setData(res))
        .catch((err) => {
          console.warn('FunnelWidget: failed to compute funnel:', err);
          setData(null);
        })
        .finally(() => setLoading(false));
    }, FETCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
    // Stringify to make a stable dep without re-running on identity churn.
  }, [
    parentDashboardId,
    JSON.stringify(steps),
    JSON.stringify(targetDcs),
    refreshTick,
  ]);

  if (targetDcs.length === 0) return null;

  const renderSeries = (counts: number[] | null) => {
    if (counts === null) {
      return (
        <Text size="xs" c="dimmed">
          unavailable
        </Text>
      );
    }
    return (
      <Group gap={6} wrap="nowrap">
        {counts.map((n, idx) => {
          const label =
            idx === 0
              ? 'Starting rows'
              : `After: ${
                  definitions.find((d) => d.id === steps[idx - 1]?.filter_id)?.label ??
                  'filter'
                }`;
          return (
            <React.Fragment key={idx}>
              {idx > 0 && (
                <Icon icon="tabler:chevron-right" width={12} color="var(--mantine-color-dimmed)" />
              )}
              <Tooltip label={label} withArrow>
                <Text
                  size="xs"
                  fw={idx === counts.length - 1 ? 700 : 500}
                  c={idx === counts.length - 1 ? 'blue' : 'dimmed'}
                  style={{ fontVariantNumeric: 'tabular-nums' }}
                >
                  {formatCount(n)}
                </Text>
              </Tooltip>
            </React.Fragment>
          );
        })}
      </Group>
    );
  };

  if (loading && !data) {
    return <Skeleton height={20} radius="sm" />;
  }

  if (!data) return null;

  const entries: Array<[string, number[] | null]> = Object.entries(data.counts) as Array<
    [string, number[] | null]
  >;
  if (entries.length === 0) return null;

  // Single-DC: render inline. Multi-DC: tabs.
  if (entries.length === 1) {
    const [, counts] = entries[0];
    return (
      <Stack gap={2}>
        <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
          Rows
        </Text>
        {renderSeries(counts)}
      </Stack>
    );
  }

  return (
    <Tabs defaultValue={entries[0]?.[0]} variant="pills" radius="sm">
      <Tabs.List>
        {entries.map(([dcId]) => (
          <Tabs.Tab key={dcId} value={dcId}>
            <Text size="xs">{dcId.slice(-6)}</Text>
          </Tabs.Tab>
        ))}
      </Tabs.List>
      {entries.map(([dcId, counts]) => (
        <Tabs.Panel key={dcId} value={dcId} pt={6}>
          {renderSeries(counts)}
        </Tabs.Panel>
      ))}
    </Tabs>
  );
};

export default FunnelWidget;
