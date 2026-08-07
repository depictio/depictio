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
import React, { useEffect, useRef, useState } from 'react';
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
import type { ComponentType, SourceMode } from './store/useBuilderStore';
import StepType from './steps/StepType';
import StepData from './steps/StepData';
import StepDesign from './steps/StepDesign';
import ChoiceScreen from './ChoiceScreen';
import CatalogTab from './catalog/CatalogTab';
import BrandMark from '../chrome/BrandMark';
import { COMPONENT_SOURCE } from './componentSource';

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
  const sourceMode = useBuilderStore((s) => s.sourceMode);
  const catalogMode = useBuilderStore((s) => s.catalogMode);
  const setSourceMode = useBuilderStore((s) => s.setSourceMode);

  // The catalog browser matches the whole project's ingested DCs, so it needs
  // the project id — resolved once from the dashboard. `undefined` = still
  // loading, `null` = resolved but the dashboard carries no project id.
  const [projectId, setProjectId] = useState<string | null | undefined>(undefined);

  // The stash is cleared on first read, but under React.StrictMode this
  // effect runs twice (mount → cleanup+reset → remount): the second pass
  // would find sessionStorage empty and dump the user on the bare type
  // grid. Keep the popped value in a ref so every re-run of the effect
  // can re-hydrate from it.
  const pendingRef = useRef<AIPendingFill | null>(null);

  useEffect(() => {
    init({ mode: 'create', dashboardId, componentId: newComponentId });
    fetchDashboard(dashboardId)
      .then((dash) => setProjectId(dash.project_id ?? null))
      .catch(() => setProjectId(null));
    // AI hand-off: hydrate AFTER init() so the reset doesn't clobber the
    // pre-fill. Lands the user directly on the Design step with the live
    // preview rendering the AI-authored component.
    const pending = popAIPendingFill(newComponentId) ?? pendingRef.current;
    pendingRef.current = pending;
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

  // Which surface is showing.
  const showChoice = sourceMode === 'unset';
  const showCatalogBrowser = sourceMode === 'catalog' && !catalogMode;
  const showStepper = !showChoice && !showCatalogBrowser;

  // Browser back/forward across the in-page steps.
  //
  // The whole Add-component flow lives on one URL: picking the catalog, then
  // opening an offer to customise it, are zustand flag changes rather than
  // navigations. So the browser's Back button saw nothing to go back to and
  // left the flow entirely for the dashboard, losing the work in progress,
  // while the header's own "Back to catalog" button worked fine. Each surface
  // now gets a history entry carrying just enough to restore it.
  //
  // The URL deliberately does not change: the route already identifies the
  // component being created, and a per-step URL would be a second source of
  // truth for state the store already owns.
  const surfaceKey = `${sourceMode}:${catalogMode}`;
  const lastSurface = useRef<string | null>(null);
  const fromPopstate = useRef(false);

  useEffect(() => {
    const entry = { builder: { sourceMode, catalogMode } };
    if (lastSurface.current === null) {
      window.history.replaceState({ ...window.history.state, ...entry }, '');
    } else if (lastSurface.current !== surfaceKey && !fromPopstate.current) {
      window.history.pushState({ ...window.history.state, ...entry }, '');
    }
    fromPopstate.current = false;
    lastSurface.current = surfaceKey;
  }, [surfaceKey, sourceMode, catalogMode]);

  useEffect(() => {
    const onPop = (event: PopStateEvent) => {
      const builder = (
        event.state as { builder?: { sourceMode: SourceMode; catalogMode: boolean } } | null
      )?.builder;
      // An entry from before this page (or from the preview iframe) is somebody
      // else's; let the browser handle it as a real navigation.
      if (!builder) return;
      fromPopstate.current = true;
      // Only the surface flags are restored. The seeded config is left alone so
      // stepping back to the browser and forward again returns to the offer
      // already loaded rather than re-deriving it.
      useBuilderStore.setState(
        builder.catalogMode
          ? { sourceMode: builder.sourceMode, catalogMode: true, step: 2 }
          : { sourceMode: builder.sourceMode, catalogMode: false },
      );
    };
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

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

  // Both header states of the catalog path show the catalog's own mark, so the
  // band agrees with the tile directly beneath it and with the badge the added
  // component ends up carrying.
  const headerSource = sourceMode === 'catalog' ? COMPONENT_SOURCE.catalog : COMPONENT_SOURCE.manual;
  // The catalog's Design step is the one state whose title is not just the
  // name of the source it came from.
  const headerTitle =
    sourceMode === 'catalog' && !showCatalogBrowser
      ? 'Customize catalog component'
      : headerSource.label;

  return (
    <AppShell
      padding="md"
      header={{ height: 50 }}
      footer={showStepper ? { height: 80 } : { height: 0 }}
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group gap="xs">
            <BrandMark />
            {headerBack}
            {headerSource.image ? (
              <img
                src={headerSource.image}
                alt=""
                style={{ width: 22, height: 22, objectFit: 'contain', display: 'block' }}
              />
            ) : (
              <Icon icon={headerSource.icon} width={22} />
            )}
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

        {/* Hidden rather than unmounted.
          *
          * The catalog browser holds a lot of where-you-were: which tool is
          * expanded, which output is selected, which render tab, the search
          * text, the facet chips, the scroll position. All of it is React-local
          * state, so unmounting on the way into the Design step threw it away
          * and "Back to catalog" landed on the first output of the first tool
          * every time. Toggling visibility keeps the lot for free, with no
          * state to lift, serialise or restore.
          *
          * `display` is toggled inside the inline style rather than through the
          * `hidden` attribute: the inline `display: flex` below would override
          * the low-specificity `[hidden] { display: none }` UA rule. `none`
          * also drops the subtree from the accessibility tree and the tab
          * order, so nothing behind the stepper is reachable.
          *
          * Mounted only once the catalog path is taken, so the manual path
          * never pays for the project-wide compose request. `sourceMode` stays
          * 'catalog' across the Design-step round-trip and only clears on
          * "Methods", which is a deliberate clean slate anyway. */}
        {sourceMode === 'catalog' && (
          <Container
            fluid
            px="md"
            py={0}
            // Header (50) + AppShell.Main md padding (16 top+bottom) → leave room
            // so the split panel fills the viewport without a second scrollbar.
            style={{
              height: 'calc(100vh - 82px)',
              display: showCatalogBrowser ? 'flex' : 'none',
              flexDirection: 'column',
            }}
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
