/**
 * Three-step component creation page. Mirrors the Dash stepper at
 * /dashboard-edit/{id}/component/add/{newId}: Component Type → Data Source →
 * Component Design. Same `<ComponentBuilder>` is reused by `EditComponentPage`.
 *
 * Step labels, descriptions, stepper props, and the "Component Ready!"
 * completion page are taken verbatim from depictio/dash/layouts/stepper.py.
 */
import React, { useEffect } from 'react';
import {
  AppShell,
  Button,
  Center,
  Container,
  Group,
  Stack,
  Stepper,
  Text,
  Title,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { useBuilderStore } from './store/useBuilderStore';
import StepType from './steps/StepType';
import StepData from './steps/StepData';
import StepDesign from './steps/StepDesign';

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

  useEffect(() => {
    init({ mode: 'create', dashboardId, componentId: newComponentId });
    return () => reset();
  }, [dashboardId, newComponentId, init, reset]);

  // Step 0 → 1 needs componentType. Step 1 → 2 needs wfId+dcId. Step 2 always
  // allowed once reached.
  const canAdvanceFromZero = Boolean(componentType);
  const canAdvanceFromOne = Boolean(wfId && dcId);

  const cancel = () => {
    window.location.assign(`/dashboard-beta-edit/${dashboardId}`);
  };

  const handleAddToDashboard = () => {
    // The Save action lives inside StepDesign; the completion page only links
    // back to the dashboard once the component has been persisted.
    window.location.assign(`/dashboard-beta-edit/${dashboardId}`);
  };

  return (
    <AppShell padding="md" header={{ height: 50 }} footer={{ height: 80 }}>
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group gap="xs">
            <Icon icon="mdi:plus-box" width={22} />
            <Title order={5}>New component</Title>
          </Group>
          <Button variant="default" size="xs" onClick={cancel}>
            Cancel
          </Button>
        </Group>
      </AppShell.Header>

      <AppShell.Main>
        <Container size="xl" px="md" py="xl">
          <Stepper
            active={step}
            onStepClick={(n) => {
              if (n < step) setStep(n);
              else if (n === 1 && canAdvanceFromZero) setStep(1);
              else if (n === 2 && canAdvanceFromZero && canAdvanceFromOne)
                setStep(2);
            }}
            allowNextStepsSelect={false}
            color="gray"
            size="lg"
            iconSize={42}
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
            <Stepper.Step
              label="Data Source"
              description="Connect your component to data"
            >
              <StepData />
            </Stepper.Step>
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
      </AppShell.Main>

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
              disabled={step === 0 || step >= 2}
              onClick={() => setStep(Math.max(0, step - 1))}
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
              onClick={() => setStep(step + 1)}
            >
              Next Step
            </Button>
          </Group>
        </Container>
      </AppShell.Footer>
    </AppShell>
  );
};

export default CreateComponentPage;
