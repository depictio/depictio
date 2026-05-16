/**
 * Step 2: mounts ComponentBuilder for the chosen type, plus the Save action.
 * Used by both CreateComponentPage (final step) and EditComponentPage (only step).
 */
import React, { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Center, Stack, Text, Title } from '@mantine/core';
import { Icon } from '@iconify/react';
import { notifications } from '@mantine/notifications';
import { fetchSpecs, upsertComponent } from 'depictio-react-core';
import { useBuilderStore } from '../store/useBuilderStore';
import type { ColumnSpec } from '../store/useBuilderStore';
import ComponentBuilder from '../ComponentBuilder';
import { buildMetadata } from '../buildMetadata';
import { getComponentTypeMeta } from '../componentTypes';

const StepDesign: React.FC = () => {
  const state = useBuilderStore();
  const [savedRedirect, setSavedRedirect] = useState(false);

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
