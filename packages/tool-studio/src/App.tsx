import { useEffect, useState } from 'react';
import { Stepper, Group, Button, Alert, Code, Text } from '@mantine/core';
import { Icon } from '@iconify/react';
import { ArrowLeft, ArrowRight, PanelRight } from 'lucide-react';
import { notifications } from '@mantine/notifications';
import AppHeader from './components/AppHeader';
import { STUDIO_TONE } from './theme';
import { BaseThemeContext, useStudioTone } from './components/Tone';
import { MantineThemeContext, useMantineTheme } from '@mantine/core';
import { useStudioStore, newOutputSlugClash } from './state/useStudioStore';
import { useKinds } from './catalog/kinds';
import { useCatalog } from './catalog/catalog';
import ToolForm from './steps/ToolForm';
import FixtureDrop from './steps/FixtureDrop';
import VizDesigner from './steps/VizDesigner';
import ExportPanel from './steps/ExportPanel';
import StartScreen from './steps/StartScreen';
import OutputsBar from './components/OutputsBar';
import EntryPanel from './components/EntryPanel';
import { useDiagnostics } from './hooks/useDiagnostics';
import { useMediaQuery } from '@mantine/hooks';
import { discardDraftBackup, restoreDraftBackup, useDraftBackup } from './state/draftBackup';

const STEPS = ['Tool', 'Fixture', 'Visualizations', 'Export'] as const;

export default function App() {
  const { kinds } = useKinds();
  const { catalog } = useCatalog();
  const started = useStudioStore((s) => s.started);
  const start = useStudioStore((s) => s.start);
  const step = useStudioStore((s) => s.step);
  const setStepRaw = useStudioStore((s) => s.setStep);
  // Toasts belong to the step that raised them; carrying them across steps left
  // stale messages ("golden.csv: 5 columns") sitting over the next one.
  const setStep = (i: number) => {
    notifications.clean();
    setStepRaw(i);
  };
  const tool = useStudioStore((s) => s.tool);
  const output = useStudioStore((s) => s.output);
  const fixture = useStudioStore((s) => s.fixture);
  const renders = useStudioStore((s) => s.renders);
  const existing = useStudioStore((s) => s.existing);
  const newOutputTarget = useStudioStore((s) => s.newOutputTarget);
  const reset = useStudioStore((s) => s.reset);
  const diagnostics = useDiagnostics(kinds, catalog);
  // The draft a #draft= link replaced (state/draftBackup.ts).
  const backup = useDraftBackup();
  // The entry panel sits beside the steps on wide screens; on narrower ones it
  // is a toggle, so the form keeps its width.
  const wide = useMediaQuery('(min-width: 75em)');
  const [panelOpen, setPanelOpen] = useState<boolean | null>(null);
  const showPanel = started && (panelOpen ?? Boolean(wide));

  // A draft is restored from localStorage on load. Say so once, with a way out:
  // silently resuming someone else's half-finished entry is worse than losing it.
  const [restored, setRestored] = useState(
    () => useStudioStore.getState().renders.length > 0 || Boolean(useStudioStore.getState().tool.id),
  );

  // Gate forward navigation on the minimum each step needs. Each gate returns
  // what is missing, so the disabled Next can say why instead of just greying out.
  const missing = (i: number): string[] => {
    if (i === 0) {
      // Append mode: identity + output come from the catalog (not authored in
      // the Tool form, and an existing output may recognise its file by
      // `filename` rather than `path_glob`), so the Tool step is always
      // satisfied — otherwise maxReachable stalls at 0 and blocks Next→Export.
      if (existing) return [];
      const out: string[] = [];
      if (!tool.id) out.push('tool id');
      if (!tool.name) out.push('tool name');
      // The catalog card shows both; `catalog validate` rejects a module without them.
      if (!tool.description) out.push('tool description');
      if (!tool.homepage) out.push('homepage');
      if (!output.slug) out.push('output slug');
      if (!output.path_glob && !output.filename) out.push('path glob (or file name)');
      // A new output must not reuse an existing output's slug (would overwrite its file).
      if (newOutputSlugClash(newOutputTarget, output.slug)) out.push('an output slug not already used by this tool');
      return out;
    }
    if (i === 1) return fixture || existing ? [] : ['a fixture file']; // existing tools bring their own fixture
    if (i === 2) return renders.length > 0 ? [] : ['at least one visualization'];
    return [];
  };
  const canLeave = (i: number): boolean => missing(i).length === 0;
  const maxReachable = (() => {
    let i = 0;
    while (i < STEPS.length - 1 && canLeave(i)) i++;
    return i;
  })();

  // Below `sm` the bar turns compact and the entry panel becomes a sheet, as
  // depictio's chrome does on a phone.
  const compact = Boolean(useMediaQuery('(max-width: 47.99em)'));

  // Portalled surfaces (menus, modals, popovers) are styled for depictio's
  // pages through a mark on <html>; `builder` is the component builder's,
  // whose dropdown and chip rules are the ones the Studio's builder needs.
  useEffect(() => {
    const root = document.documentElement;
    root.setAttribute('data-gp-page', 'builder');
    return () => root.removeAttribute('data-gp-page');
  }, []);
  // While the step bar is docked, toasts rise above it (styles/studio.css).
  useEffect(() => {
    const root = document.documentElement;
    if (started) root.setAttribute('data-ts-foot', '');
    else root.removeAttribute('data-ts-foot');
  }, [started]);

  const errorCount = diagnostics.filter((d) => d.severity === 'error').length;

  // The Studio's section tone (theme.ts): the page's primary, as GlassPage
  // tones Projects and Dashboards. Previews opt back out (components/Tone.tsx).
  const baseTheme = useMantineTheme();
  const tonedTheme = useStudioTone(STUDIO_TONE);

  return (
    <BaseThemeContext.Provider value={baseTheme}>
    <MantineThemeContext.Provider value={tonedTheme}>
    {/* depictio's component-builder shell (builder/glass/GlassBuilderShell.tsx):
        the Paper top bar, a canvas that scrolls on its own, and the step bar
        docked under it, so Back/Next sit in the same place on every step. The
        entry panel docks on the right like the dashboards' side panels. */}
    <div
      className="gp-shell bgl-shell ts-shell ts-tone"
      data-testid="app-shell"
      data-foot={started ? '' : undefined}
      data-panel={showPanel && !compact ? '' : undefined}
    >
      <AppHeader context={started ? STEPS[step] : undefined} compact={compact} />

      <main className="gp-main bgl-main">
        <div className="gp-page">
          {/* The start screen replaces the whole wizard chrome: a stepper and a
              disabled Back/Next bar around an explanation would say "you are
              already in the middle of something", which is exactly the
              confusion it exists to remove. */}
          {!started ? (
            <StartScreen onStart={start} resuming={Boolean(tool.id || renders.length)} />
          ) : (
            <>
              <Stepper
                active={step}
                onStepClick={setStep}
                allowNextStepsSelect={false}
                size="lg"
                iconSize={38}
                className="bgl-stepper"
                styles={{
                  stepLabel: { fontSize: '16px', fontWeight: 700 },
                  stepDescription: { fontSize: '14px', color: 'var(--mantine-color-dimmed)' },
                }}
              >
                <Stepper.Step data-testid="step-0" label="Tool" description="Identity & output" />
                <Stepper.Step data-testid="step-1" label="Fixture" description="Drop a CSV/TSV" />
                <Stepper.Step data-testid="step-2" label="Visualizations" description="Bind columns" />
                <Stepper.Step data-testid="step-3" label="Export" description="Zip or PR" />
              </Stepper>

              <div className="ts-toolbar">
                {!existing ? <OutputsBar diagnostics={diagnostics} /> : <span />}
                <Button
                  size="compact-md"
                  variant={showPanel ? 'light' : 'default'}
                  className="ts-panel-toggle"
                  leftSection={<PanelRight size={16} strokeWidth={1.8} aria-hidden />}
                  onClick={() => setPanelOpen(!showPanel)}
                  data-testid="toggle-entry-panel"
                  aria-pressed={showPanel}
                >
                  Entry
                  {errorCount ? (
                    <Text span size="xs" c="red" fw={700} ml={6}>
                      {errorCount}
                    </Text>
                  ) : null}
                </Button>
              </div>

              {backup.available && (
                <Alert
                  color="gray"
                  variant="light"
                  mb="md"
                  withCloseButton
                  onClose={discardDraftBackup}
                  icon={<Icon icon="mdi:backup-restore" />}
                  title="Opened from a link"
                  data-testid="draft-backup"
                >
                  <Group justify="space-between" wrap="nowrap" gap="md">
                    <span>
                      The link replaced the draft you had here
                      {backup.toolId ? (
                        <>
                          {' '}
                          (<Code>{backup.toolId}</Code>)
                        </>
                      ) : null}
                      . It is kept until you dismiss this.
                    </span>
                    <Button
                      size="xs"
                      variant="default"
                      data-testid="restore-backup"
                      onClick={() => {
                        restoreDraftBackup();
                        setRestored(false);
                      }}
                    >
                      Restore previous draft
                    </Button>
                  </Group>
                </Alert>
              )}

              {restored && !backup.available && (
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

              {step === 0 && <ToolForm catalog={catalog} />}
              {step === 1 && <FixtureDrop />}
              {step === 2 && <VizDesigner kinds={kinds} />}
              {step === 3 && <ExportPanel kinds={kinds} catalog={catalog} />}
            </>
          )}
        </div>
      </main>

      {started && (
        <aside className="ts-panel" aria-label="Catalog entry" hidden={!showPanel}>
          <EntryPanel diagnostics={diagnostics} onClose={() => setPanelOpen(false)} />
        </aside>
      )}

      {started && (
        <footer className="bgl-foot">
          <div className="bgl-foot-inner">
            <span className="bgl-foot-step">
              Step {step + 1} of {STEPS.length}
              <span className="bgl-foot-name"> · {STEPS[step]}</span>
            </span>
            <div className="bgl-foot-actions">
              {step < STEPS.length - 1 && !canLeave(step) && (
                <Text size="sm" c="dimmed" ta="right" data-testid="next-missing" visibleFrom="md" lineClamp={1}>
                  Still needed: {missing(step).join(', ')}
                </Text>
              )}
              <Button
                variant="default"
                size="md"
                leftSection={<ArrowLeft size={18} strokeWidth={1.9} aria-hidden />}
                disabled={step === 0}
                onClick={() => setStep(step - 1)}
              >
                Back
              </Button>
              {step < STEPS.length - 1 && (
                <Button
                  data-testid="next"
                  size="md"
                  color={STUDIO_TONE}
                  rightSection={<ArrowRight size={18} strokeWidth={1.9} aria-hidden />}
                  disabled={!canLeave(step) || step > maxReachable}
                  onClick={() => setStep(step + 1)}
                >
                  Next
                </Button>
              )}
            </div>
          </div>
        </footer>
      )}
    </div>
    </MantineThemeContext.Provider>
    </BaseThemeContext.Provider>
  );
}
