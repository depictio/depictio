/**
 * Step 2: mounts ComponentBuilder for the chosen type, plus the Save action.
 * Used by both CreateComponentPage (final step) and EditComponentPage (only step).
 */
import React, { useEffect, useMemo, useState } from 'react';
import { ActionIcon, Alert, Button, Group, Stack, Text, Title, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';
import { notifications } from '@mantine/notifications';
import { fetchSpecs, upsertComponent } from 'depictio-react-core';
import { AiFillModal } from 'depictio-react-ai';
import type { ComponentType as AIComponentType } from 'depictio-react-ai';
import { useBuilderStore } from '../store/useBuilderStore';
import type { ColumnSpec, FigureMode } from '../store/useBuilderStore';
import ComponentBuilder from '../ComponentBuilder';
import { buildMetadata } from '../buildMetadata';
import { getComponentTypeMeta } from '../componentTypes';

const StepDesign: React.FC = () => {
  const state = useBuilderStore();
  const [savedRedirect, setSavedRedirect] = useState(false);
  const [aiOpen, setAiOpen] = useState(false);

  // Hydrate the builder store from a validated component dict. The lite
  // model field names match what each builder reads from `config`
  // (and the figure builder also reads top-level `visuType` / `dictKwargs`
  // / `figureMode` / `codeContent`), so we mirror `loadExisting()`'s
  // shape without flipping the store into edit mode.
  const applyAiFill = (parsed: Record<string, unknown>) => {
    const ct = parsed.component_type as AIComponentType | undefined;
    useBuilderStore.setState((s) => ({
      componentType: (ct as never) ?? s.componentType,
      visuType: (parsed.visu_type as string) ?? s.visuType,
      dictKwargs:
        (parsed.dict_kwargs as Record<string, unknown>) ?? s.dictKwargs,
      figureMode:
        ((parsed.mode as FigureMode) ?? s.figureMode) === 'code' ? 'code' : 'ui',
      codeContent: (parsed.code_content as string) ?? s.codeContent,
      // Each per-type builder reads what it needs from `config`. Merge so
      // tag / dc / wf / index already in the store survive.
      config: { ...s.config, ...parsed },
    }));
    notifications.show({
      color: 'violet',
      title: 'AI fill applied',
      message: 'The form and preview have been updated.',
      autoClose: 2500,
    });
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
      if (!state.wfId || !state.dcId) return false;
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
        window.location.assign(`/dashboard-beta-edit/${state.dashboardId}`);
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
      </Stack>

      <ComponentBuilder />

      {state.saveError && (
        <Alert color="red" title="Save error">
          {state.saveError}
        </Alert>
      )}

      <Group justify="flex-end" mt="md" gap="xs">
        {state.dcId && state.componentType && state.dashboardId && (
          <Tooltip label="Fill with AI">
            <ActionIcon
              variant="light"
              color="violet"
              onClick={() => setAiOpen(true)}
              aria-label="Fill with AI"
              size="lg"
              data-tour-id="ai-fill-button"
            >
              <Icon icon="mdi:auto-fix" width={18} />
            </ActionIcon>
          </Tooltip>
        )}
        <Button
          leftSection={<Icon icon="mdi:content-save" width={16} />}
          loading={state.saving}
          disabled={!ready || savedRedirect}
          onClick={handleSave}
        >
          {state.mode === 'create' ? 'Create component' : 'Save changes'}
        </Button>
      </Group>

      {savedRedirect && (
        <Text size="sm" c="dimmed" ta="right">
          Redirecting…
        </Text>
      )}

      {state.dashboardId && state.dcId && state.componentType && (
        <AiFillModal
          opened={aiOpen}
          onClose={() => setAiOpen(false)}
          dashboardId={state.dashboardId}
          componentType={state.componentType as AIComponentType}
          dataCollectionId={state.dcId}
          current={
            state.mode === 'edit' && state.existing
              ? (state.existing as unknown as Record<string, unknown>)
              : null
          }
          onApply={applyAiFill}
        />
      )}
    </Stack>
  );
};

export default StepDesign;
