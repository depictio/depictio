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
import type { ComponentType } from './store/useBuilderStore';
import StepType from './steps/StepType';
import StepData from './steps/StepData';
import StepDesign from './steps/StepDesign';

export interface CreateComponentPageProps {
  dashboardId: string;
  newComponentId: string;
}

/** Shape written by EditorApp's "Add component → With AI…" flow. */
interface AIPendingFill {
  componentType: ComponentType;
  config: Record<string, unknown>;
  dcId: string;
  wfId: string | null;
  projectId: string | null;
}

/** Pop (read + clear) the AI pre-fill stash for this component id, if any.
 *  Cleared on consumption so a refresh restarts the manual stepper instead
 *  of silently re-applying a stale AI fill. */
function popAIPendingFill(newComponentId: string): AIPendingFill | null {
  const key = `depictio.ai.pending-fill.${newComponentId}`;
  try {
    const raw = sessionStorage.getItem(key);
    if (!raw) return null;
    sessionStorage.removeItem(key);
    const parsed = JSON.parse(raw) as Partial<AIPendingFill>;
    if (!parsed.componentType || !parsed.config || !parsed.dcId) return null;
    return {
      componentType: parsed.componentType,
      config: parsed.config,
      dcId: parsed.dcId,
      wfId: parsed.wfId ?? null,
      projectId: parsed.projectId ?? null,
    };
  } catch {
    return null;
  }
}

const CreateComponentPage: React.FC<CreateComponentPageProps> = ({
  dashboardId,
  newComponentId,
}) => {
  const init = useBuilderStore((s) => s.init);
  const reset = useBuilderStore((s) => s.reset);
  const initFromPrompt = useBuilderStore((s) => s.initFromPrompt);
  const step = useBuilderStore((s) => s.step);
  const setStep = useBuilderStore((s) => s.setStep);
  const wfId = useBuilderStore((s) => s.wfId);
  const dcId = useBuilderStore((s) => s.dcId);
  const componentType = useBuilderStore((s) => s.componentType);

  useEffect(() => {
    init({ mode: 'create', dashboardId, componentId: newComponentId });
    // AI hand-off: hydrate AFTER init() so the reset doesn't clobber the
    // pre-fill. Lands the user directly on the Design step with the live
    // preview rendering the AI-authored component.
    const pending = popAIPendingFill(newComponentId);
    if (pending && pending.wfId) {
      initFromPrompt({
        componentType: pending.componentType,
        wfId: pending.wfId,
        dcId: pending.dcId,
        projectId: pending.projectId,
        config: pending.config,
      });
    }
    return () => reset();
  }, [dashboardId, newComponentId, init, initFromPrompt, reset]);

  // Text components don't bind to a workflow/DC — the Data Source step is
  // hidden entirely. The global `step` state still uses 0,1,2; for text the
  // stepper UI just renders 2 children (Type → Design), so internal state 2
  // maps to stepper position 1.
  const isText = componentType === 'text';
  const canAdvanceFromZero = Boolean(componentType);
  const canAdvanceFromOne = isText || Boolean(wfId && dcId);
  const stepperActive = isText ? (step >= 2 ? 1 : 0) : step;

  const cancel = () => {
    window.location.assign(`/dashboard-edit/${dashboardId}`);
  };

  const handleAddToDashboard = () => {
    // The Save action lives inside StepDesign; the completion page only links
    // back to the dashboard once the component has been persisted.
    window.location.assign(`/dashboard-edit/${dashboardId}`);
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
    </AppShell>
  );
};

export default CreateComponentPage;
