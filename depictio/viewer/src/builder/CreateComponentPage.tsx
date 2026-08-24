/**
 * Component creation page. A two-tile chooser (`ChoiceScreen`) fronts two paths:
 *
 *   - Manual  → the three-step Mantine stepper (Type → Data → Design), mirroring
 *               the old Dash stepper at /dashboard-edit/{id}/component/add/{newId}.
 *   - Catalog → a full-screen catalog browser (`CatalogTab`, 1/4 filters — 3/4
 *               preview) that recognises the project's ingested tool outputs.
 *               "Add" persists directly; "Edit & Add" pre-fills the store and
 *               drops into the Design step (catalogMode) for customisation.
 *
 * `sourceMode` ('unset' | 'manual' | 'catalog') + `catalogMode` in the builder
 * store drive which surface renders. The same `<ComponentBuilder>` powers the
 * Design step here and `EditComponentPage`.
 */
import React, { useEffect, useState } from 'react';
import {
  AppShell,
  Button,
  Center,
  Container,
  Group,
  Loader,
  Stack,
  Stepper,
  Text,
  Title,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { fetchDashboard } from 'depictio-react-core';
import { useBuilderStore } from './store/useBuilderStore';
import StepType from './steps/StepType';
import StepData from './steps/StepData';
import StepDesign from './steps/StepDesign';
import ChoiceScreen from './ChoiceScreen';
import CatalogTab from './catalog/CatalogTab';

export interface CreateComponentPageProps {
  dashboardId: string;
  newComponentId: string;
}

const CreateComponentPage: React.FC<CreateComponentPageProps> = ({
  dashboardId,
  newComponentId,
}) => {
  const init = useBuilderStore((s) => s.init);
  const reset = useBuilderStore((s) => s.reset);
  const step = useBuilderStore((s) => s.step);
  const setStep = useBuilderStore((s) => s.setStep);
  const wfId = useBuilderStore((s) => s.wfId);
  const dcId = useBuilderStore((s) => s.dcId);
  const componentType = useBuilderStore((s) => s.componentType);
  const sourceMode = useBuilderStore((s) => s.sourceMode);
  const catalogMode = useBuilderStore((s) => s.catalogMode);
  const setSourceMode = useBuilderStore((s) => s.setSourceMode);

  // The catalog browser matches the whole project's ingested DCs, so it needs
  // the project id — resolved once from the dashboard. `undefined` = still
  // loading, `null` = resolved but the dashboard carries no project id.
  const [projectId, setProjectId] = useState<string | null | undefined>(undefined);

  useEffect(() => {
    init({ mode: 'create', dashboardId, componentId: newComponentId });
    fetchDashboard(dashboardId)
      .then((dash) => setProjectId(dash.project_id ?? null))
      .catch(() => setProjectId(null));
    return () => reset();
  }, [dashboardId, newComponentId, init, reset]);

  // Text components don't bind to a workflow/DC — the Data Source step is
  // hidden entirely. The global `step` state still uses 0,1,2; for text the
  // stepper UI just renders 2 children (Type → Design), so internal state 2
  // maps to stepper position 1.
  const isText = componentType === 'text';
  const canAdvanceFromZero = Boolean(componentType);
  const canAdvanceFromOne = isText || Boolean(wfId && dcId);
  const stepperActive = isText ? (step >= 2 ? 1 : 0) : step;

  // Which surface is showing.
  const showChoice = sourceMode === 'unset';
  const showCatalogBrowser = sourceMode === 'catalog' && !catalogMode;
  const showStepper = !showChoice && !showCatalogBrowser;

  const cancel = () => {
    window.location.assign(`/dashboard-edit/${dashboardId}`);
  };

  // Back to the two-tile chooser — a clean slate on the same component id.
  const backToChoice = () => {
    init({ mode: 'create', dashboardId, componentId: newComponentId });
  };
  // From the catalog Design step (Edit & Add) back to the catalog browser.
  const backToCatalogBrowser = () => {
    useBuilderStore.setState({ catalogMode: false, sourceMode: 'catalog', step: 0 });
  };

  const handleAddToDashboard = () => {
    // The Save action lives inside StepDesign; the completion page only links
    // back to the dashboard once the component has been persisted.
    window.location.assign(`/dashboard-edit/${dashboardId}`);
  };

  const headerBack = (() => {
    if (showChoice) return null;
    if (showCatalogBrowser || sourceMode === 'manual') {
      return (
        <Button
          variant="subtle"
          color="gray"
          size="xs"
          leftSection={<Icon icon="mdi:arrow-left" width={16} />}
          onClick={backToChoice}
        >
          Methods
        </Button>
      );
    }
    // catalog Design step (Edit & Add)
    return (
      <Button
        variant="subtle"
        color="gray"
        size="xs"
        leftSection={<Icon icon="mdi:arrow-left" width={16} />}
        onClick={backToCatalogBrowser}
      >
        Back to catalog
      </Button>
    );
  })();

  const headerTitle = showCatalogBrowser
    ? 'Pick from catalog'
    : sourceMode === 'catalog'
      ? 'Customize catalog component'
      : 'New component';
  const headerIcon = sourceMode === 'catalog' ? 'mdi:shape-plus' : 'mdi:plus-box';

  return (
    <AppShell
      padding="md"
      header={{ height: 50 }}
      footer={showStepper ? { height: 80 } : { height: 0 }}
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group gap="xs">
            {headerBack}
            <Icon icon={headerIcon} width={22} />
            <Title order={5}>{headerTitle}</Title>
          </Group>
          <Button variant="default" size="xs" onClick={cancel}>
            Cancel
          </Button>
        </Group>
      </AppShell.Header>

      <AppShell.Main>
        {showChoice && (
          <Container size="xl" px="md" py="xl">
            <ChoiceScreen
              onManual={() => setSourceMode('manual')}
              onCatalog={() => setSourceMode('catalog')}
            />
          </Container>
        )}

        {showCatalogBrowser && (
          <Container
            fluid
            px="md"
            py={0}
            // Header (50) + AppShell.Main md padding (16 top+bottom) → leave room
            // so the split panel fills the viewport without a second scrollbar.
            style={{ height: 'calc(100vh - 82px)', display: 'flex', flexDirection: 'column' }}
          >
            {projectId === undefined ? (
              <Center style={{ flex: 1 }}>
                <Loader size="sm" />
              </Center>
            ) : projectId === null ? (
              <Center style={{ flex: 1 }}>
                <Text c="dimmed">This dashboard is not linked to a project, so no catalog is available.</Text>
              </Center>
            ) : (
              <CatalogTab projectId={projectId} />
            )}
          </Container>
        )}

        {showStepper && (
          <Container size="xl" px="md" py="xl">
            <Stepper
              active={stepperActive}
              onStepClick={(n) => {
                if (isText) {
                  // 2-step stepper for text: 0 → Type, 1 → Design (internal step=2)
                  if (n === 0) setStep(0);
                  else if (n === 1 && canAdvanceFromZero) setStep(2);
                  return;
                }
                if (n < step) setStep(n);
                else if (n === 1 && canAdvanceFromZero) setStep(1);
                else if (n === 2 && canAdvanceFromZero && canAdvanceFromOne)
                  setStep(2);
              }}
              allowNextStepsSelect={false}
              color="gray"
              size="lg"
              iconSize={42}
              data-tour-id="component-wizard-stepper"
              styles={{
                stepLabel: { fontSize: '16px', fontWeight: 700 },
                stepDescription: {
                  fontSize: '14px',
                  color: 'var(--mantine-color-dimmed)',
                },
              }}
            >
              <Stepper.Step
                label="Component Type"
                description="Choose the type of dashboard component to create"
              >
                <StepType />
              </Stepper.Step>
              {!isText && (
                <Stepper.Step
                  label="Data Source"
                  description="Connect your component to data"
                >
                  <StepData />
                </Stepper.Step>
              )}
              <Stepper.Step
                label="Component Design"
                description="Customize the appearance and behavior of your component"
              >
                <StepDesign />
              </Stepper.Step>
              <Stepper.Completed>
                <Stack gap="md" align="center" mt="xl">
                  <Title order={2} ta="center" fw={700} c="green">
                    Component Ready!
                  </Title>
                  <Text size="md" ta="center" c="gray" mb="xl">
                    Your component has been configured and is ready to be added to
                    your dashboard.
                  </Text>
                  <Center>
                    <Button
                      color="green"
                      variant="filled"
                      size="xl"
                      onClick={handleAddToDashboard}
                      leftSection={<Icon icon="bi:check-circle" width={24} />}
                      style={{
                        height: 60,
                        fontSize: 18,
                        fontWeight: 700,
                      }}
                    >
                      Add to Dashboard
                    </Button>
                  </Center>
                </Stack>
              </Stepper.Completed>
            </Stepper>
          </Container>
        )}
      </AppShell.Main>

      {showStepper && (
        <AppShell.Footer
          withBorder
          style={{
            background: 'var(--mantine-color-body)',
          }}
        >
          <Container size="xl" px="md" h="100%">
            <Group justify="center" align="center" gap="md" h="100%">
              <Button
                variant="outline"
                color="gray"
                size="lg"
                leftSection={<Icon icon="mdi:arrow-left" width={20} />}
                disabled={step === 0 || (step >= 2 && !isText)}
                onClick={() => {
                  // Text components skip Step 1 in both directions.
                  if (isText && step === 2) setStep(0);
                  else setStep(Math.max(0, step - 1));
                }}
              >
                Back
              </Button>
              <Button
                variant="filled"
                color="gray"
                size="lg"
                rightSection={<Icon icon="mdi:arrow-right" width={20} />}
                disabled={
                  (step === 0 && !canAdvanceFromZero) ||
                  (step === 1 && !canAdvanceFromOne) ||
                  step >= 2
                }
                onClick={() => {
                  // Text jumps 0 → 2 directly (no data binding required).
                  if (isText && step === 0) setStep(2);
                  else setStep(step + 1);
                }}
              >
                Next Step
              </Button>
            </Group>
          </Container>
        </AppShell.Footer>
      )}
    </AppShell>
  );
};

export default CreateComponentPage;
