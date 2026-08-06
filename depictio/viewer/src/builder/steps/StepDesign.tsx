/**
 * Step 2: mounts ComponentBuilder for the chosen type, plus the Save action.
 * Used by both CreateComponentPage (final step) and EditComponentPage (only step).
 */
import React, { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Center, Group, Paper, Stack, Text, Title } from '@mantine/core';
import { Icon } from '@iconify/react';
import { notifications } from '@mantine/notifications';
import { fetchSpecs, upsertComponent } from 'depictio-react-core';
import { AiFillModal, useAIHealth } from 'depictio-react-ai';
import { useServerStatus } from '../../hooks/useServerStatus';
import { useBuilderStore } from '../store/useBuilderStore';
import type { ColumnSpec } from '../store/useBuilderStore';
import ComponentBuilder from '../ComponentBuilder';
import SectionSelect from '../shared/SectionSelect';
import { buildMetadata } from '../buildMetadata';
import { getComponentTypeMeta } from '../componentTypes';

/** Component types the AI fill flow can author (matches the backend's
 *  ComponentType literal — text/jbrowse/advanced_viz are out of scope). */
const AI_FILL_TYPES = new Set([
  'figure',
  'card',
  'interactive',
  'table',
  'image',
  'multiqc',
  'map',
]);

const StepDesign: React.FC = () => {
  const state = useBuilderStore();
  const [savedRedirect, setSavedRedirect] = useState(false);
  const [aiFillOpened, setAiFillOpened] = useState(false);
  const { features: serverFeatures } = useServerStatus();
  const aiHealth = useAIHealth(serverFeatures.ai);
  const aiFillAvailable =
    serverFeatures.ai &&
    Boolean(state.dcId) &&
    Boolean(state.componentType && AI_FILL_TYPES.has(state.componentType));

  /** Hydrate the builder from an AI-validated component dict. Field names
   *  match the lite-model shape the per-type builders read; figure needs its
   *  top-level store fields synced too. Deliberately does NOT touch
   *  figureMode when the AI omitted `mode` — the user's current editing mode
   *  must survive a non-figure or partial fill. */
  const applyAiFill = (parsed: Record<string, unknown>) => {
    const store = useBuilderStore.getState();
    store.patchConfig(parsed);
    if (store.componentType === 'figure') {
      const mode = parsed.mode as string | undefined;
      if (mode === 'code' || mode === 'ui') store.setFigureMode(mode);
      if (typeof parsed.visu_type === 'string') store.setVisuType(parsed.visu_type);
      if (parsed.dict_kwargs && typeof parsed.dict_kwargs === 'object') {
        store.patchDictKwargs(parsed.dict_kwargs as Record<string, unknown>);
      }
      if (typeof parsed.code_content === 'string') store.setCodeContent(parsed.code_content);
    }
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
              color="violet"
              leftSection={<Icon icon="mdi:auto-fix" width={14} />}
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

      {aiFillAvailable && state.dashboardId && state.dcId && (
        <AiFillModal
          opened={aiFillOpened}
          onClose={() => setAiFillOpened(false)}
          dashboardId={state.dashboardId}
          componentType={state.componentType as never}
          dataCollectionId={state.dcId}
          current={currentForAiFill()}
          onApply={applyAiFill}
          closeOnApply={false}
          serverKeyAvailable={aiHealth?.server_key_configured === true}
        />
      )}

      <ComponentBuilder />

      {/* Placement, not appearance — so it sits outside the per-type builder,
          which keeps it identical for every component type instead of nine
          near-copies. */}
      <Paper withBorder radius="md" p="md">
        <SectionSelect />
      </Paper>

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
