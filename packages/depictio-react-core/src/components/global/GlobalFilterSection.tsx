/**
 * Left-sidebar section that renders the active set of global filter pills
 * plus a compact funnel widget. Hidden when no global filters are promoted.
 *
 * Sits ABOVE the existing per-tab interactive filter groups so the user's
 * eye reads from "applies everywhere" down to "applies only here".
 */

import React, { useMemo } from 'react';
import { Group, Paper, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import type {
  FunnelStep,
  FunnelTargetDC,
  GlobalFilterDef,
} from '../../api';
import GlobalFilterPill from './GlobalFilterPill';
import FunnelWidget from './FunnelWidget';

export interface GlobalFilterSectionProps {
  parentDashboardId: string | null;
  definitions: GlobalFilterDef[];
  values: Record<string, unknown>;
  onValueChange: (filterId: string, value: unknown) => void;
  onDemote: (filterId: string) => void;
  onGoToSource?: (sourceTabId: string) => void;
  /** Tick incremented when any value changes — passed through to the funnel so
   *  it re-fetches. (The widget also debounces internally.) */
  refreshTick?: number;
}

const GlobalFilterSection: React.FC<GlobalFilterSectionProps> = ({
  parentDashboardId,
  definitions,
  values,
  onValueChange,
  onDemote,
  onGoToSource,
  refreshTick,
}) => {
  // Steps for the funnel: every promoted filter with a non-empty value.
  const funnelSteps: FunnelStep[] = useMemo(
    () =>
      definitions
        .filter((d) => {
          const v = values[d.id];
          if (v === null || v === undefined) return false;
          if (Array.isArray(v) && v.length === 0) return false;
          if (v === '') return false;
          return true;
        })
        .map((d) => ({ filter_id: d.id, value: values[d.id] })),
    [definitions, values],
  );

  // Target DCs: union of every link's DC across all definitions.
  const targetDcs: FunnelTargetDC[] = useMemo(() => {
    const seen = new Set<string>();
    const out: FunnelTargetDC[] = [];
    for (const def of definitions) {
      for (const link of def.links) {
        const key = `${link.wf_id}::${link.dc_id}`;
        if (seen.has(key)) continue;
        seen.add(key);
        out.push({ wf_id: link.wf_id, dc_id: link.dc_id });
      }
    }
    return out;
  }, [definitions]);

  if (definitions.length === 0 || !parentDashboardId) return null;

  return (
    <Paper withBorder p="xs" radius="md">
      <Stack gap={8}>
        <Group justify="space-between" align="center">
          <Text size="xs" fw={600} c="dimmed" tt="uppercase">
            <Icon
              icon="tabler:world"
              width={12}
              style={{ verticalAlign: 'middle', marginRight: 4 }}
            />
            Global
          </Text>
        </Group>
        <Group gap={6} wrap="wrap">
          {definitions.map((def) => (
            <GlobalFilterPill
              key={def.id}
              def={def}
              value={values[def.id]}
              onChange={(v) => onValueChange(def.id, v)}
              onRemove={() => onDemote(def.id)}
              onGoToSource={
                onGoToSource ? () => onGoToSource(def.source_tab_id) : undefined
              }
            />
          ))}
        </Group>
        {targetDcs.length > 0 && (
          <FunnelWidget
            parentDashboardId={parentDashboardId}
            definitions={definitions}
            steps={funnelSteps}
            targetDcs={targetDcs}
            refreshTick={refreshTick}
          />
        )}
      </Stack>
    </Paper>
  );
};

export default GlobalFilterSection;
