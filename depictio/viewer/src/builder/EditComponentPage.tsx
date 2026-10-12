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
import { Pencil } from 'lucide-react';
import { BrandScope, fetchDashboard } from 'depictio-react-core';
import type { BrandTheme, StoredMetadata } from 'depictio-react-core';
import { useBuilderStore } from './store/useBuilderStore';
import StepDesign from './steps/StepDesign';
import BrandMark from '../chrome/BrandMark';
import { useGlassPages } from '../chrome/variants/glass/pages';
import GlassBuilderShell from './glass/GlassBuilderShell';
import { getComponentTypeMeta } from './componentTypes';

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
  // The dashboard's brand, so the preview draws in the colours the component
  // will have once saved rather than the instance defaults.
  const [brandTheme, setBrandTheme] = useState<BrandTheme | null>(null);
  // Named in the Glass top bar's trail and head.
  const [dashboardTitle, setDashboardTitle] = useState<string | null>(null);
  const componentType = useBuilderStore((s) => s.componentType);
  const glass = useGlassPages();

  useEffect(() => {
    init({ mode: 'edit', dashboardId, componentId });
    fetchDashboard(dashboardId)
      .then((dash) => {
        setDashboardTitle(dash.title ?? null);
        setBrandTheme(dash.brand_theme ?? dash.inherited_brand_theme ?? null);
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
    window.location.assign(`/dashboard-edit/${dashboardId}`);
  };

  const body = (
    <>
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
    </>
  );

  if (glass) {
    return (
      <BrandScope theme={brandTheme}>
        <GlassBuilderShell
          crumbs={[
            { label: dashboardTitle || 'Dashboard', href: `/dashboard-edit/${dashboardId}` },
            { label: 'Edit component' },
          ]}
          onCancel={cancel}
          head={{
            icon: <Pencil size={22} strokeWidth={1.7} />,
            title: 'Edit component',
            description: componentType
              ? `${getComponentTypeMeta(componentType).label} component. Changes apply when you save.`
              : undefined,
          }}
        >
          {body}
        </GlassBuilderShell>
      </BrandScope>
    );
  }

  return (
    <BrandScope theme={brandTheme}>
    <AppShell data-testid="app-shell" padding="md" header={{ height: 50 }}>
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group gap="xs">
            <BrandMark />
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
          {body}
        </Container>
      </AppShell.Main>
    </AppShell>
    </BrandScope>
  );
};

export default EditComponentPage;
