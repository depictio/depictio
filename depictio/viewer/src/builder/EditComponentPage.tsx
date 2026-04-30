/**
 * Edit-existing-component page. Mounts the same `<ComponentBuilder>` as the
 * stepper's last step, but pre-loaded from the existing stored_metadata.
 * Skips workflow/DC + type selection — those are fixed for an existing
 * component. The save button updates in place.
 */
import React, { useEffect, useState } from 'react';
import {
  AppShell,
  Alert,
  Button,
  Container,
  Group,
  Loader,
  Title,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { fetchDashboard } from 'depictio-react-core';
import type { StoredMetadata } from 'depictio-react-core';
import { useBuilderStore } from './store/useBuilderStore';
import StepDesign from './steps/StepDesign';

export interface EditComponentPageProps {
  dashboardId: string;
  componentId: string;
}

const EditComponentPage: React.FC<EditComponentPageProps> = ({
  dashboardId,
  componentId,
}) => {
  const init = useBuilderStore((s) => s.init);
  const reset = useBuilderStore((s) => s.reset);
  const loadExisting = useBuilderStore((s) => s.loadExisting);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    init({ mode: 'edit', dashboardId, componentId });
    fetchDashboard(dashboardId)
      .then((dash) => {
        const meta = (dash.stored_metadata || []).find(
          (m: StoredMetadata) => String(m.index) === String(componentId),
        );
        if (!meta) {
          setError(`Component ${componentId} not found in this dashboard.`);
          return;
        }
        loadExisting(meta);
      })
      .catch((err) => {
        setError(`Failed to load dashboard: ${err.message || err}`);
      })
      .finally(() => setLoading(false));
    return () => reset();
  }, [dashboardId, componentId, init, loadExisting, reset]);

  const cancel = () => {
    window.location.assign(`/dashboard-beta-edit/${dashboardId}`);
  };

  return (
    <AppShell padding="md" header={{ height: 50 }}>
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group gap="xs">
            <Icon icon="mdi:pencil" width={22} />
            <Title order={5}>Edit component</Title>
          </Group>
          <Button variant="default" size="xs" onClick={cancel}>
            Cancel
          </Button>
        </Group>
      </AppShell.Header>

      <AppShell.Main>
        <Container size="xl" px="md" py="xl">
          {loading && (
            <Group p="lg">
              <Loader size="sm" />
            </Group>
          )}
          {error && (
            <Alert color="red" title="Cannot edit component">
              {error}
            </Alert>
          )}
          {!loading && !error && <StepDesign />}
        </Container>
      </AppShell.Main>
    </AppShell>
  );
};

export default EditComponentPage;
