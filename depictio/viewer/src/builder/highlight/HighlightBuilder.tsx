/**
 * Highlight builder: which figure of which tab the tile shows, and how it
 * draws it here. A highlight is made from the figure's menu ("Highlight on…")
 * on its own tab; this is where its menu's Edit lands.
 *
 * The preview is the tile itself, rendered by the dashboard's own
 * ComponentRenderer with the tab family resolving its source, so it shows
 * exactly what the grid will, the dashboard's filters included.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { Box, Group, Select, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';
import {
  ComponentRenderer,
  canHighlight,
  componentTypeVisual,
  fetchDashboard,
  findHighlightSource,
  highlightSourceRef,
  tabDisplayName,
} from 'depictio-react-core';
import type { StoredMetadata } from 'depictio-react-core';

import { useBuilderStore } from '../store/useBuilderStore';
import { buildMetadata } from '../buildMetadata';
import { useBuilderPreviewFilters } from '../useBuilderPreviewFilters';
import DesignShell from '../shared/DesignShell';
import { BuilderSection, BuilderSections } from '../shared/BuilderSections';
import PlacementSection from '../shared/PlacementSection';
import PreviewPanel from '../shared/PreviewPanel';
import PreviewTabLinks from '../shared/PreviewTabLinks';
import { useTabFamily } from '../shared/useTabFamily';
import FigureStyleSection from '../figure/FigureStyleSection';

interface HighlightConfig {
  source_tab?: string | null;
  source_dashboard_id?: string | null;
  source_component?: string | null;
}

const PREVIEW_HEIGHT = 420;

const HighlightBuilder: React.FC = () => {
  const state = useBuilderStore();
  const config = state.config as HighlightConfig;
  const patchConfig = state.patchConfig;
  const tabs = useTabFamily();
  const filters = useBuilderPreviewFilters();

  // The tab picked: by id first, as the tile resolves it, else by name.
  const otherTabs = useMemo(
    () => tabs.filter((t) => t.dashboard_id !== state.dashboardId),
    [tabs, state.dashboardId],
  );
  const sourceTab =
    otherTabs.find((t) => t.dashboard_id === config.source_dashboard_id) ??
    otherTabs.find((t) => tabDisplayName(t) === config.source_tab) ??
    null;

  const [components, setComponents] = useState<StoredMetadata[] | null>(null);
  useEffect(() => {
    setComponents(null);
    if (!sourceTab) return;
    let cancelled = false;
    fetchDashboard(sourceTab.dashboard_id)
      .then((dash) => {
        if (!cancelled) setComponents(dash.stored_metadata ?? []);
      })
      .catch((err) => console.warn('[builder] highlight source tab unavailable:', err));
    return () => {
      cancelled = true;
    };
  }, [sourceTab?.dashboard_id]);

  const figures = useMemo(() => (components ?? []).filter(canHighlight), [components]);
  const found = findHighlightSource(components ?? undefined, config.source_component ?? undefined);
  const current = found.ok ? found.component : null;
  const figureOptions = useMemo(
    () =>
      figures.map((m) => ({
        value: highlightSourceRef(m, components ?? undefined),
        label: (typeof m.title === 'string' && m.title.trim()) || String(m.index),
        type: m.component_type,
      })),
    [figures, components],
  );
  const typeOf = new Map(figureOptions.map((o) => [o.value, o.type]));

  const metadata = buildMetadata(state);

  const form = (
    <BuilderSections builder="highlight" required={['source']}>
      <BuilderSection
        value="source"
        icon="mdi:star-four-points-outline"
        title="Figure shown"
        subtitle="The tab it lives on and the figure on it"
      >
        <Stack gap="md">
          <Text size="xs" c="dimmed">
            A highlight shows a figure of another tab without copying it: an edit made
            there shows here too. This tab&apos;s filters apply to it.
          </Text>
          <Select
            label="Tab"
            placeholder={otherTabs.length ? 'Pick a tab' : 'This dashboard has no other tabs'}
            data={otherTabs.map((t) => ({ value: t.dashboard_id, label: tabDisplayName(t) }))}
            value={sourceTab?.dashboard_id ?? null}
            onChange={(id) => {
              const tab = otherTabs.find((t) => t.dashboard_id === id);
              patchConfig({
                source_dashboard_id: tab?.dashboard_id ?? null,
                source_tab: tab ? tabDisplayName(tab) : null,
                source_component: null,
              });
            }}
            searchable
            allowDeselect={false}
            leftSection={<Icon icon="mdi:tab" width={14} />}
            error={
              !sourceTab && (config.source_tab || config.source_dashboard_id)
                ? `No tab “${config.source_tab || config.source_dashboard_id}” in this dashboard`
                : undefined
            }
          />
          <Select
            label="Figure"
            description="Figures restyle to this tile's style; an advanced visualisation is shown as on its tab."
            placeholder={
              !sourceTab ? 'Pick a tab first' : components === null ? 'Loading…' : 'Pick a figure'
            }
            data={figureOptions.map(({ value, label }) => ({ value, label }))}
            value={current ? highlightSourceRef(current, components ?? undefined) : null}
            onChange={(ref) => patchConfig({ source_component: ref })}
            disabled={!sourceTab}
            searchable
            allowDeselect={false}
            renderOption={({ option }) => {
              const visual = componentTypeVisual(typeOf.get(option.value) ?? 'figure');
              return (
                <Group gap="xs" wrap="nowrap">
                  <Icon icon={visual.icon} width={14} color={visual.color} />
                  <Text size="sm">{option.label}</Text>
                </Group>
              );
            }}
            error={
              components && config.source_component && !current
                ? `No figure “${config.source_component}” on that tab`
                : undefined
            }
          />
        </Stack>
      </BuilderSection>

      <FigureStyleSection
        highlight
        inherited={{
          title: typeof current?.title === 'string' ? current.title : undefined,
          subtitle: typeof current?.subtitle === 'string' ? current.subtitle : undefined,
        }}
      />

      <PlacementSection />
    </BuilderSections>
  );

  const preview = (
    <PreviewPanel
      minHeight={PREVIEW_HEIGHT}
      empty={!current}
      emptyMessage="Pick a tab and a figure to see the tile."
    >
      <PreviewTabLinks tabs={tabs}>
        <Box style={{ height: PREVIEW_HEIGHT, display: 'flex', flexDirection: 'column' }}>
          {state.dashboardId && (
            <ComponentRenderer
              metadata={metadata}
              filters={filters}
              dashboardId={state.dashboardId}
            />
          )}
        </Box>
      </PreviewTabLinks>
    </PreviewPanel>
  );

  return <DesignShell formSlot={form} previewSlot={preview} hideColumns />;
};

export default HighlightBuilder;
