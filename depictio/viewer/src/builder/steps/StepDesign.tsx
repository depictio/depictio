/**
 * Step 2: mounts ComponentBuilder for the chosen type, plus the Save action.
 * Used by both CreateComponentPage (final step) and EditComponentPage (only step).
 */
import React, { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Center, Group, Paper, Stack, Switch, Text, Title } from '@mantine/core';
import { Icon } from '@iconify/react';
import { notifications } from '@mantine/notifications';
import { fetchSpecs, upsertComponent } from 'depictio-react-core';
import { AI_COLOR, AI_ICON, AiFillModal, useAIHealth } from 'depictio-react-ai';
import { useServerStatus } from '../../hooks/useServerStatus';
import { useBuilderStore } from '../store/useBuilderStore';
import type { ColumnSpec } from '../store/useBuilderStore';
import { applyLiteComponent } from '../store/applyLiteComponent';
import ComponentBuilder from '../ComponentBuilder';
import { buildMetadata } from '../buildMetadata';
import { getComponentTypeMeta } from '../componentTypes';

const StepDesign: React.FC = () => {
  const state = useBuilderStore();
  const [savedRedirect, setSavedRedirect] = useState(false);
  const [aiFillOpened, setAiFillOpened] = useState(false);
  const { features: serverFeatures } = useServerStatus();
  const aiHealth = useAIHealth(serverFeatures.ai);
  // Every builder type can be filled; text is the one that needs no data
  // collection (it is written with the dashboard as context).
  const aiFillAvailable =
    serverFeatures.ai && Boolean(state.componentType) &&
    (Boolean(state.dcId) || state.componentType === 'text');

  /** Hydrate the builder from an AI-validated component dict, through the
   *  same mapping the Describe step and the catalog use, and mark the
   *  component as AI-authored for the saved `ai_source` provenance. */
  const applyAiFill = (parsed: Record<string, unknown>) => {
    applyLiteComponent(parsed);
    if (!state.aiSource) state.setAiSource({ flow: 'component-from-prompt' });
  };

  /** Current component state for the revision prompt — lets the LLM patch
   *  what's on screen instead of starting over. Best effort: an incomplete
   *  builder state simply means a from-scratch fill. */
  const currentForAiFill = (): Record<string, unknown> | null => {
    try {
      if (Object.keys(state.config).length === 0 && !state.existing) return null;
      return buildMetadata(state) as unknown as Record<string, unknown>;
    } catch {
      return null;
    }
  };

  // Filters the previews can apply: the dashboard's active ones minus any this
  // component emitted itself (mirrors useBuilderPreviewFilters, but unhooked
  // from the toggle — the banner must keep showing the count while the toggle
  // is off, or there'd be no way to turn it back on).
  const carriedFilters = state.dashboardFilters.filter(
    (f) => String(f.index) !== String(state.componentId),
  );

  // Safety net: if user lands on this step without cols loaded (e.g. StepData
  // didn't run to completion before they clicked Next, or edit mode skipped
  // step 1), refetch column specs once.
  useEffect(() => {
    if (state.dcId && state.cols.length === 0) {
      fetchSpecs(state.dcId)
        .then((specs) => {
          if (Array.isArray(specs)) {
            state.setCols(specs as ColumnSpec[]);
          } else if (specs && typeof specs === 'object') {
            const colsList: ColumnSpec[] = Object.entries(
              specs as Record<string, Record<string, unknown>>,
            ).map(([name, info]) => ({
              name,
              type: String(info?.type ?? ''),
              specs: info,
            }));
            state.setCols(colsList);
          }
        })
        .catch(() => {
          // best effort — leave cols empty if refetch fails
        });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.dcId]);

  const ready = useMemo(() => {
    if (!state.componentType) return false;
    if (!state.dashboardId || !state.componentId) return false;
    if (state.mode === 'create') {
      // Text components are stand-alone — no workflow/DC binding required.
      if (state.componentType !== 'text' && (!state.wfId || !state.dcId))
        return false;
    }
    return true;
  }, [state]);

  const handleSave = async () => {
    if (!ready) return;
    state.setSaving(true);
    state.setSaveError(null);
    try {
      const metadata = buildMetadata(state);
      await upsertComponent(state.dashboardId!, metadata, {
        appendLayout: state.mode === 'create',
      });
      notifications.show({
        color: 'teal',
        title: state.mode === 'create' ? 'Component created' : 'Component updated',
        message: '',
        autoClose: 1500,
      });
      setSavedRedirect(true);
      window.setTimeout(() => {
        window.location.assign(`/dashboard-edit/${state.dashboardId}`);
      }, 600);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      state.setSaveError(msg);
      notifications.show({
        color: 'red',
        title: 'Save failed',
        message: msg,
        autoClose: 5000,
      });
    } finally {
      state.setSaving(false);
    }
  };

  if (!state.componentType) {
    return (
      <Alert color="yellow" mt="md" title="No component type selected">
        Pick a component type in the previous step.
      </Alert>
    );
  }

  const meta = getComponentTypeMeta(state.componentType);
  // What the AI routing notice says after the type name: the collection the
  // component was generated against, or the fact that text has none.
  const routedOn = ((): string => {
    if (state.componentType === 'text') return ', written with the dashboard as context';
    if (state.aiRouting?.dcTag) return ` on ${state.aiRouting.dcTag}`;
    return '';
  })();

  return (
    <Stack gap="md" pt="md">
      <Stack gap={4} align="center">
        <Title order={3} ta="center" fw={700}>
          {meta.label} — Component Design
        </Title>
        <Text size="sm" c="gray" ta="center">
          Customize the appearance and behavior of your component
        </Text>
        {aiFillAvailable && (
          <Group justify="center" mt={4}>
            <Button
              size="xs"
              variant="light"
              color={AI_COLOR}
              leftSection={<Icon icon={AI_ICON} width={14} />}
              onClick={() => setAiFillOpened(true)}
              data-testid="ai-fill-open"
            >
              {state.mode === 'edit' || Object.keys(state.config).length > 0
                ? 'Refine with AI'
                : 'AI fill'}
            </Button>
          </Group>
        )}
      </Stack>

      {state.sourceMode === 'ai' && state.aiSource && (
        <Paper withBorder radius="md" p="sm" data-testid="ai-routing-notice">
          <Group gap="xs" wrap="nowrap" align="flex-start">
            <Icon icon={AI_ICON} width={18} style={{ flexShrink: 0, marginTop: 2 }} />
            <Stack gap={2}>
              <Text size="sm">
                <Text span fw={600}>
                  {meta.label}
                </Text>
                {routedOn}
                {state.aiRouting?.source === 'auto' && (
                  <Text span c="dimmed">
                    {' '}
                    · chosen by the AI
                    {state.aiRouting.reason ? `: ${state.aiRouting.reason}` : ''}
                  </Text>
                )}
                {state.aiRouting?.source === 'single' && (
                  <Text span c="dimmed">
                    {' '}
                    · the only matching collection
                  </Text>
                )}
              </Text>
              {state.aiRouting && state.aiRouting.alternatives.length > 0 && (
                <Text size="xs" c="dimmed">
                  Also plausible:{' '}
                  {state.aiRouting.alternatives.map((a) => a.data_collection_tag).join(', ')}
                </Text>
              )}
              <Text size="xs" c="dimmed">
                Not what you meant? Use Back to change the type or the collection and
                generate again.
              </Text>
            </Stack>
          </Group>
        </Paper>
      )}

      {/* MultiQC previews render pre-aggregated report plots (no row-filter
          concept) and text components have no data at all — no banner there. */}
      {carriedFilters.length > 0 &&
        state.componentType !== 'text' &&
        state.componentType !== 'multiqc' && (
          <Paper withBorder radius="md" p="sm" data-testid="builder-filter-banner">
            <Group justify="space-between" wrap="nowrap">
              <Group gap="xs" wrap="nowrap">
                <Icon icon="mdi:filter-variant" width={18} />
                <Text size="sm">
                  Previewing with {carriedFilters.length} active dashboard filter
                  {carriedFilters.length === 1 ? '' : 's'}
                </Text>
              </Group>
              <Switch
                size="sm"
                checked={state.applyDashboardFilters}
                onChange={(e) => state.setApplyDashboardFilters(e.currentTarget.checked)}
                label="Apply to preview"
                data-testid="builder-filter-toggle"
              />
            </Group>
            {state.applyDashboardFilters && (
              <Text size="xs" c="dimmed" mt={4}>
                A heavily filtered preview can be empty — toggle off to preview the
                full dataset. The saved component always follows the dashboard's
                live filters.
              </Text>
            )}
          </Paper>
        )}

      {aiFillAvailable && state.dashboardId && (
        <AiFillModal
          opened={aiFillOpened}
          onClose={() => setAiFillOpened(false)}
          dashboardId={state.dashboardId}
          componentType={state.componentType}
          dataCollectionId={state.dcId}
          current={currentForAiFill()}
          onApply={applyAiFill}
          closeOnApply={false}
          serverKeyAvailable={aiHealth?.server_key_configured === true}
        />
      )}

      <ComponentBuilder />

      {state.saveError && (
        <Alert color="red" title="Save error">
          {state.saveError}
        </Alert>
      )}

      <Center mt="xl">
        <Button
          variant="filled"
          color="green"
          size="xl"
          leftSection={<Icon icon="mdi:content-save" width={24} />}
          loading={state.saving}
          disabled={!ready || savedRedirect || !state.previewReady}
          onClick={handleSave}
          style={{ height: 60, fontSize: 18, fontWeight: 700 }}
          data-tour-id="component-save"
          title={
            !state.previewReady
              ? 'Bind all required columns before creating'
              : undefined
          }
        >
          {state.mode === 'create' ? 'Create component' : 'Save changes'}
        </Button>
      </Center>

      {savedRedirect && (
        <Text size="sm" c="dimmed" ta="center">
          Redirecting…
        </Text>
      )}
    </Stack>
  );
};

export default StepDesign;
