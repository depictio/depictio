import { useState } from 'react';
import { AppShell, Stepper, Container, Group, Button, Box, Alert, Code } from '@mantine/core';
import { Icon } from '@iconify/react';
import AppHeader from './components/AppHeader';
import AppFooter from './components/AppFooter';
import { useStudioStore, newOutputSlugClash } from './state/useStudioStore';
import { useKinds } from './catalog/kinds';
import { useCatalog } from './catalog/catalog';
import ToolForm from './steps/ToolForm';
import FixtureDrop from './steps/FixtureDrop';
import VizDesigner from './steps/VizDesigner';
import ExportPanel from './steps/ExportPanel';
import StartScreen from './steps/StartScreen';

const STEPS = ['Tool', 'Fixture', 'Visualizations', 'Export'] as const;

export default function App() {
  const { kinds } = useKinds();
  const { catalog } = useCatalog();
  const started = useStudioStore((s) => s.started);
  const start = useStudioStore((s) => s.start);
  const step = useStudioStore((s) => s.step);
  const setStep = useStudioStore((s) => s.setStep);
  const tool = useStudioStore((s) => s.tool);
  const output = useStudioStore((s) => s.output);
  const fixture = useStudioStore((s) => s.fixture);
  const renders = useStudioStore((s) => s.renders);
  const existing = useStudioStore((s) => s.existing);
  const newOutputTarget = useStudioStore((s) => s.newOutputTarget);
  const reset = useStudioStore((s) => s.reset);

  // A draft is restored from localStorage on load. Say so once, with a way out:
  // silently resuming someone else's half-finished entry is worse than losing it.
  const [restored, setRestored] = useState(
    () => useStudioStore.getState().renders.length > 0 || Boolean(useStudioStore.getState().tool.id),
  );

  // Gate forward navigation on the minimum each step needs.
  const canLeave = (i: number): boolean => {
    if (i === 0) {
      // Append mode: identity + output come from the catalog (not authored in
      // the Tool form, and an existing output may recognise its file by
      // `filename` rather than `path_glob`), so the Tool step is always
      // satisfied — otherwise maxReachable stalls at 0 and blocks Next→Export.
      if (existing) return true;
      if (!(tool.id && tool.name && output.slug && output.path_glob)) return false;
      // A new output must not reuse an existing output's slug (would overwrite its file).
      if (newOutputSlugClash(newOutputTarget, output.slug)) return false;
      return true;
    }
    if (i === 1) return Boolean(fixture || existing); // existing tools bring their own fixture
    if (i === 2) return renders.length > 0;
    return true;
  };
  const maxReachable = (() => {
    let i = 0;
    while (i < STEPS.length - 1 && canLeave(i)) i++;
    return i;
  })();

  return (
    // Header and footer are both AppShell slots, so both stay pinned while only
    // the wizard scrolls between them. AppShell reserves padding for each on the
    // main column, so no step can end up hidden underneath either bar.
    <AppShell header={{ height: 56 }} footer={{ height: 52 }} padding={0}>
      <AppShell.Header>
        <AppHeader />
      </AppShell.Header>
      {/* The start screen replaces the whole wizard chrome — a stepper and a
          disabled Back/Next band around an explanation would say "you are
          already in the middle of something", which is exactly the confusion it
          exists to remove. */}
      {!started ? (
        <AppShell.Main>
          <StartScreen onStart={start} resuming={Boolean(tool.id || renders.length)} />
        </AppShell.Main>
      ) : (
        /* One viewport-tall column: stepper on top, step content scrolling in
           the middle, Back/Next in a band at the bottom. The nav used to sit
           after the content, so it landed at a different height on every step
           and moved again as a step grew; pinning it to the column means it is
           always in the same place and always reachable without scrolling. */
        <AppShell.Main
          style={{ height: '100dvh', boxSizing: 'border-box', display: 'flex', flexDirection: 'column' }}
        >
          <Container size="lg" pt="lg" w="100%">
            <Stepper
              active={step}
              onStepClick={setStep}
              allowNextStepsSelect={false}
              size="sm"
              mb="lg"
            >
              <Stepper.Step label="Tool" description="Identity & output" icon={<Icon icon="mdi:tools" />} />
              <Stepper.Step label="Fixture" description="Drop a CSV/TSV" icon={<Icon icon="mdi:file-delimited-outline" />} />
              <Stepper.Step label="Visualizations" description="Bind columns" icon={<Icon icon="mdi:chart-box-outline" />} />
              <Stepper.Step label="Export" description="Zip or PR" icon={<Icon icon="mdi:download" />} />
            </Stepper>

            {restored && (
              <Alert
                color="gray"
                variant="light"
                mb="md"
                withCloseButton
                onClose={() => setRestored(false)}
                icon={<Icon icon="mdi:content-save-outline" />}
                title="Draft restored"
              >
                <Group justify="space-between" wrap="nowrap" gap="md">
                  <span>
                    Picking up where you left off
                    {tool.id ? (
                      <>
                        {' '}
                        (<Code>{tool.id}</Code>)
                      </>
                    ) : null}
                    . Drafts stay in this browser and never leave it.
                  </span>
                  <Button
                    size="xs"
                    variant="default"
                    onClick={() => {
                      reset();
                      setRestored(false);
                    }}
                  >
                    Start over
                  </Button>
                </Group>
              </Alert>
            )}
          </Container>

          {/* minHeight:0 so this flex child may shrink below its content and
              actually scroll, rather than stretching the column past the viewport. */}
          <Box style={{ flex: 1, overflowY: 'auto', minHeight: 0 }}>
            <Container size="lg" pb="lg" w="100%">
              {step === 0 && <ToolForm catalog={catalog} />}
              {step === 1 && <FixtureDrop />}
              {step === 2 && <VizDesigner kinds={kinds} />}
              {step === 3 && <ExportPanel kinds={kinds} />}
            </Container>
          </Box>

          <Box style={{ borderTop: '1px solid var(--app-border-color)' }}>
            <Container size="lg" py="sm" w="100%">
              <Group justify="space-between">
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
          </Box>
        </AppShell.Main>
      )}
      <AppShell.Footer>
        <AppFooter />
      </AppShell.Footer>
    </AppShell>
  );
}
