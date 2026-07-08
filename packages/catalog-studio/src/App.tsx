import { AppShell, Stepper, Container, Group, Button, Box } from '@mantine/core';
import { Icon } from '@iconify/react';
import AppHeader from './components/AppHeader';
import { useStudioStore } from './state/useStudioStore';
import { useKinds } from './catalog/kinds';
import ToolForm from './steps/ToolForm';
import FixtureDrop from './steps/FixtureDrop';
import VizDesigner from './steps/VizDesigner';
import ExportPanel from './steps/ExportPanel';

const STEPS = ['Tool', 'Fixture', 'Visualizations', 'Export'] as const;

export default function App() {
  const { kinds } = useKinds();
  const step = useStudioStore((s) => s.step);
  const setStep = useStudioStore((s) => s.setStep);
  const tool = useStudioStore((s) => s.tool);
  const output = useStudioStore((s) => s.output);
  const fixture = useStudioStore((s) => s.fixture);
  const renders = useStudioStore((s) => s.renders);

  // Gate forward navigation on the minimum each step needs.
  const canLeave = (i: number): boolean => {
    if (i === 0) return Boolean(tool.id && tool.name && output.slug && output.path_glob);
    if (i === 1) return Boolean(fixture);
    if (i === 2) return renders.length > 0;
    return true;
  };
  const maxReachable = (() => {
    let i = 0;
    while (i < STEPS.length - 1 && canLeave(i)) i++;
    return i;
  })();

  return (
    <AppShell header={{ height: 56 }} padding={0}>
      <AppShell.Header>
        <AppHeader />
      </AppShell.Header>
      <AppShell.Main>
        <Container size="lg" py="lg">
          <Stepper
            active={step}
            onStepClick={setStep}
            allowNextStepsSelect={false}
            color="teal"
            size="sm"
            mb="lg"
          >
            <Stepper.Step label="Tool" description="Identity & output" icon={<Icon icon="mdi:tools" />} />
            <Stepper.Step label="Fixture" description="Drop a CSV/TSV" icon={<Icon icon="mdi:file-delimited-outline" />} />
            <Stepper.Step label="Visualizations" description="Bind columns" icon={<Icon icon="mdi:chart-box-outline" />} />
            <Stepper.Step label="Export" description="Zip or PR" icon={<Icon icon="mdi:download" />} />
          </Stepper>

          <Box mih={360}>
            {step === 0 && <ToolForm />}
            {step === 1 && <FixtureDrop />}
            {step === 2 && <VizDesigner kinds={kinds} />}
            {step === 3 && <ExportPanel kinds={kinds} />}
          </Box>

          <Group justify="space-between" mt="xl">
            <Button
              variant="default"
              leftSection={<Icon icon="mdi:chevron-left" />}
              disabled={step === 0}
              onClick={() => setStep(step - 1)}
            >
              Back
            </Button>
            {step < STEPS.length - 1 && (
              <Button
                rightSection={<Icon icon="mdi:chevron-right" />}
                disabled={!canLeave(step) || step > maxReachable}
                onClick={() => setStep(step + 1)}
              >
                Next
              </Button>
            )}
          </Group>
        </Container>
      </AppShell.Main>
    </AppShell>
  );
}
