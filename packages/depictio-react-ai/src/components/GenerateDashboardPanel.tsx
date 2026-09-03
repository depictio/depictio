import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Alert,
  Button,
  Checkbox,
  Group,
  Loader,
  MultiSelect,
  Paper,
  Select,
  Stack,
  Text,
  Textarea,
  TextInput,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { GENERATE_DASHBOARD_SESSION_ID, useGenerateDashboard } from '../hooks';
import { AI_COLOR, AI_ICON, aiColorVar } from '../icons';
import { useAISession, useAIStore } from '../store';
import type { GenerateDashboardRequest } from '../types';
import AIKeySection from './AIKeySection';
import GenerationProgress from './GenerationProgress';

export interface GenerateProjectOption {
  id: string;
  name: string;
}

/** The subset of a project `joins[]` entry the picker shows. Mirrors
 *  `JoinDetails` in depictio/viewer/src/builder/data/DataCollectionInfoCard.tsx. */
export interface GenerateJoinInfo {
  leftDc: string;
  rightDc: string;
  onColumns: string[];
  how: string;
}

export interface GenerateDataCollection {
  id: string;
  /** Label shown in the picker, normally the collection tag. */
  tag: string;
  /** Collection type as the project declares it ('table', 'multiqc', ...);
   *  the panel offers tables only, the one kind generation reads. */
  type: string;
  /** Set when this collection is the result of a project-level join; the
   *  picker then marks it the way the builder's Data Collection dropdown
   *  does. */
  join?: GenerateJoinInfo | null;
}

interface Props {
  projects: GenerateProjectOption[];
  /** Resolve the collections of a project. Called once per project change;
   *  memoise it in the host so the effect does not refire on every render. */
  loadProject: (projectId: string) => Promise<{ dataCollections: GenerateDataCollection[] }>;
  /** Called with the new draft's id when the user clicks "Open in editor".
   *  The panel never navigates on its own. Memoise it in the host. */
  onOpen: (dashboardId: string) => void;
  /** True when the server holds a fallback LLM key, so the panel works
   *  without a user-supplied key. */
  serverKeyAvailable?: boolean;
  /** Called by the footer's Cancel button, which closes the dialog.
   *  Omitted, no Cancel is drawn. */
  onClose?: () => void;
}

/**
 * Whole-dashboard generation, as a tab of the New Dashboard dialog. Pick a
 * project (and optionally which of its table collections), say what the
 * dashboard should show, and watch the plan, then each component, land.
 *
 * By default the run is two calls: the first plans and stops, and nothing is
 * saved until the plan is approved; the second fills the approved plan. The
 * result is saved server-side as an AI draft, which the user opens in the
 * editor where the draft banner takes over.
 *
 * A run takes minutes and belongs to the page, not to this component: it
 * lives in the AI store, so closing the dialog leaves it streaming and
 * reopening it lands back on the run as it stands, including a plan still
 * waiting for its verdict. Only "Stop generating" ends a run early.
 */
const GenerateDashboardPanel: React.FC<Props> = ({
  projects,
  loadProject,
  onOpen,
  serverKeyAvailable = false,
  onClose,
}) => {
  const session = useAISession(GENERATE_DASHBOARD_SESSION_ID);
  const { run, cancel, pending, state, awaitingPlan, sessionSpend } = useGenerateDashboard();

  // A run that outlived the dialog is re-entered here: the form comes back as
  // the run was started, so "Build this plan" sends the request the plan was
  // made for. Read at mount only — from then on the fields are the user's.
  const [restored] = useState(() => useAIStore.getState().generation?.request ?? null);
  const [projectId, setProjectId] = useState<string | null>(
    () => restored?.project_id ?? (projects.length === 1 ? projects[0].id : null),
  );
  const [collections, setCollections] = useState<GenerateDataCollection[]>([]);
  const [collectionsLoading, setCollectionsLoading] = useState(false);
  const [collectionsError, setCollectionsError] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>(
    () => restored?.data_collection_ids ?? [],
  );
  const [prompt, setPrompt] = useState(() => restored?.prompt ?? '');
  const [title, setTitle] = useState(() => restored?.title ?? '');
  const [reviewPlan, setReviewPlan] = useState(() =>
    restored ? Boolean(restored.plan_only) : true,
  );

  /** The project whose collection selection came back from a restored run.
   *  The effect below wipes the selection when the project changes, and a
   *  restore looks exactly like a change to it. */
  const restoredProject = useRef<string | null>(restored?.project_id ?? null);

  // The chosen project's table collections; the selection resets with it.
  useEffect(() => {
    if (restoredProject.current === projectId) {
      // Only the first pass after a restore keeps the selection.
      restoredProject.current = null;
    } else {
      setSelectedIds([]);
    }
    setCollections([]);
    setCollectionsError(null);
    if (!projectId) return;
    let cancelled = false;
    setCollectionsLoading(true);
    loadProject(projectId)
      .then(({ dataCollections }) => {
        if (cancelled) return;
        setCollections(dataCollections.filter((dc) => dc.type.toLowerCase() === 'table'));
      })
      .catch((e: unknown) => {
        if (!cancelled) setCollectionsError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setCollectionsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, loadProject]);

  // One navigation per draft: a second click on "Open in editor" is the same
  // hand-off, not a second one.
  const openedRef = useRef<string | null>(null);
  const openEditor = useCallback(
    (id: string) => {
      if (openedRef.current === id) return;
      openedRef.current = id;
      onOpen(id);
    },
    [onOpen],
  );

  const hasCreds = Boolean(session.llmKey) || serverKeyAvailable;
  const canRun = Boolean(projectId) && hasCreds && !pending;

  const requestBody = (): GenerateDashboardRequest | null =>
    projectId
      ? {
          project_id: projectId,
          prompt: prompt.trim(),
          title: title.trim() || null,
          data_collection_ids: selectedIds,
        }
      : null;

  /** Start a call of the run. The store banks the ending call's spend and
   *  remembers which phase this one is, so both survive the dialog closing. */
  const startRun = (body: GenerateDashboardRequest, planPhase: boolean) => {
    void run(body, {
      planPhase,
      projectName: projects.find((p) => p.id === body.project_id)?.name ?? '',
    });
  };

  const submit = () => {
    const body = requestBody();
    if (!canRun || !body) return;
    startRun(reviewPlan ? { ...body, plan_only: true } : body, reviewPlan);
  };

  const buildPlan = () => {
    const body = requestBody();
    const approved = state.plan;
    if (pending || !body || !approved) return;
    startRun({ ...body, plan: approved }, false);
  };

  const draft = state.dashboard;
  // The run has a container of its own, which appears with the first sign of
  // a run and stays after it, holding the outcome.
  const started = pending || Boolean(state.status || state.plan || state.error || draft);

  function collectionsPlaceholder(): string {
    if (!projectId) return 'Select a project first';
    if (collectionsLoading) return 'Loading collections';
    if (collections.length === 0) return 'No table collections in this project';
    return 'All table collections';
  }

  // Same visual language as the builder's Data Collection dropdown, so a
  // joined collection is recognisable wherever it is picked.
  const joinById = new Map(collections.map((dc) => [dc.id, dc.join ?? null]));
  const renderDcOption = ({ option }: { option: { value: string; label: string } }) => {
    const join = joinById.get(option.value);
    const isJoined = Boolean(join);
    return (
      <Group gap={8} wrap="nowrap" align="flex-start">
        <Icon
          icon={isJoined ? 'mdi:link-variant' : 'mdi:database'}
          width={16}
          color={isJoined ? 'var(--mantine-color-grape-6)' : 'var(--mantine-color-gray-6)'}
          style={{ marginTop: 2, flexShrink: 0 }}
        />
        <Stack gap={2} style={{ minWidth: 0 }}>
          <Text size="sm" fw={isJoined ? 600 : 400} truncate>
            {option.label}
          </Text>
          {join && (
            <Text size="xs" c="dimmed" truncate>
              {join.leftDc} ⋈ {join.rightDc}
              {join.onColumns.length > 0 ? ` · on ${join.onColumns.join(', ')}` : ''}
            </Text>
          )}
        </Stack>
      </Group>
    );
  };

  return (
    <Stack gap="md" data-testid="generate-dashboard-panel">
      <Alert variant="light" color={AI_COLOR} icon={<Icon icon={AI_ICON} width={16} />}>
        <Text size="sm">
          Describe what the dashboard should show. The assistant reads the project&apos;s table
          collections, plans filters, cards and figures, fills and validates each one, then saves
          the result as a draft you review in the editor.
        </Text>
      </Alert>

      <Select
        label="Project"
        placeholder="Select a project"
        data={projects.map((p) => ({ value: p.id, label: p.name }))}
        value={projectId}
        onChange={setProjectId}
        required
        searchable
        // The plan waiting for a verdict was planned against this project and
        // these collections; changing them under it would build something else.
        disabled={pending || awaitingPlan}
        comboboxProps={{ withinPortal: false }}
        leftSection={<Icon icon="mdi:folder-outline" width={16} />}
        data-testid="generate-dashboard-project"
      />

      <MultiSelect
        label="Data collections"
        description="Leave empty to let the assistant use every table collection of the project."
        placeholder={collectionsPlaceholder()}
        data={collections.map((dc) => ({ value: dc.id, label: dc.tag }))}
        value={selectedIds}
        onChange={setSelectedIds}
        searchable
        clearable
        disabled={pending || awaitingPlan || !projectId || collections.length === 0}
        rightSection={collectionsLoading ? <Loader size="xs" /> : undefined}
        comboboxProps={{ withinPortal: false }}
        error={collectionsError}
        leftSection={<Icon icon="mdi:database" width={16} />}
        renderOption={renderDcOption}
        data-testid="generate-dashboard-collections"
      />

      <Textarea
        label="What should the dashboard show?"
        description="Optional: an empty prompt lets the assistant plan from the data alone. Cmd/Ctrl+Enter generates."
        placeholder="e.g. Compare body mass across species and islands, with a filter on sex"
        autosize
        minRows={3}
        maxRows={8}
        value={prompt}
        onChange={(e) => setPrompt(e.currentTarget.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
            e.preventDefault();
            submit();
          }
        }}
        disabled={pending}
        data-testid="generate-dashboard-prompt"
      />

      <TextInput
        label="Title"
        description="Optional; the assistant picks one otherwise."
        placeholder="Dashboard title"
        value={title}
        onChange={(e) => setTitle(e.currentTarget.value)}
        disabled={pending}
        data-testid="generate-dashboard-title"
      />

      <Checkbox
        label="Review the plan before building"
        description="The first call plans and stops. Nothing is saved until you build it."
        color={AI_COLOR}
        checked={reviewPlan}
        onChange={(e) => setReviewPlan(e.currentTarget.checked)}
        disabled={pending}
        data-testid="generate-review-plan"
      />

      {!serverKeyAvailable && <AIKeySection dashboardId={GENERATE_DASHBOARD_SESSION_ID} />}

      {/* Same footer as the Create and Import tabs of this dialog: centred,
          Cancel then the primary. Stopping a run replaces the primary in
          place so the row never shifts under the pointer; a plan waiting for
          a verdict hands the decision to the buttons beside it instead. */}
      <Group justify="center" gap="md" mt="md">
        {onClose && (
          // Live during a run: leaving the dialog leaves the run alone, and
          // "Stop generating" beside it is the one thing that ends it.
          <Button variant="outline" color="gray" radius="md" onClick={onClose}>
            Cancel
          </Button>
        )}
        {pending && (
          <Button color="red" variant="outline" radius="md" onClick={cancel}>
            Stop generating
          </Button>
        )}
        {!pending && !awaitingPlan && (
          <Button
            color={AI_COLOR}
            radius="md"
            leftSection={<Icon icon={AI_ICON} width={16} />}
            disabled={!canRun}
            onClick={submit}
            data-testid="generate-dashboard-run"
          >
            Generate
          </Button>
        )}
        {awaitingPlan && (
          <Text size="xs" c="dimmed">
            Review the plan below, then build it.
          </Text>
        )}
      </Group>

      {started && (
        <Paper withBorder radius="md" p="md" style={{ borderColor: aiColorVar(3) }}>
          <Stack gap="md">
            <GenerationProgress state={state} pending={pending} sessionSpend={sessionSpend} />

            {awaitingPlan && (
              <Alert
                variant="light"
                color={AI_COLOR}
                icon={<Icon icon="mdi:clipboard-check-outline" width={16} />}
                title="Plan ready for review"
              >
                <Stack gap="xs">
                  <Text size="sm">
                    Nothing has been built or saved yet. Build the plan as it stands, or plan
                    again, on a revised prompt if you want a different shape.
                  </Text>
                  <Group gap="sm">
                    <Button
                      size="xs"
                      color={AI_COLOR}
                      radius="md"
                      leftSection={<Icon icon="mdi:hammer-wrench" width={14} />}
                      onClick={buildPlan}
                      data-testid="generate-build-plan"
                    >
                      Build this plan
                    </Button>
                    <Button
                      size="xs"
                      variant="outline"
                      color={AI_COLOR}
                      radius="md"
                      leftSection={<Icon icon="mdi:refresh" width={14} />}
                      onClick={submit}
                      data-testid="generate-replan"
                    >
                      Re-plan
                    </Button>
                  </Group>
                </Stack>
              </Alert>
            )}

            {state.error && (
              <Alert
                variant="light"
                color="red"
                title="Generation failed"
                data-testid="generate-error"
              >
                {state.error}
              </Alert>
            )}

            {draft && (
              <Alert
                variant="light"
                color="teal"
                icon={<Icon icon="mdi:check" width={16} />}
                title={`Draft ready: ${draft.title}`}
                data-testid="generate-dashboard-ready"
              >
                <Stack gap="xs">
                  <Text size="sm">Saved as an AI draft.</Text>
                  {draft.dropped.length > 0 && (
                    <Text size="xs" c="dimmed">
                      Dropped: {draft.dropped.join(', ')}
                    </Text>
                  )}
                  {draft.warnings.map((w, i) => (
                    <Text key={i} size="xs" c="dimmed">
                      {w}
                    </Text>
                  ))}
                  <Group>
                    <Button
                      size="xs"
                      color={AI_COLOR}
                      radius="md"
                      leftSection={<Icon icon="mdi:open-in-new" width={14} />}
                      onClick={() => openEditor(draft.dashboard_id)}
                      data-testid="generate-open-editor"
                    >
                      Open in editor
                    </Button>
                  </Group>
                </Stack>
              </Alert>
            )}
          </Stack>
        </Paper>
      )}
    </Stack>
  );
};

export default GenerateDashboardPanel;
