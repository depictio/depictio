import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Alert,
  Button,
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
import { useAISession } from '../store';
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
  /** Called with the new draft's id: on "Open in editor" and, 1.5 s after
   *  the `dashboard` event, automatically. Memoise it in the host. */
  onOpen: (dashboardId: string) => void;
  /** True when the server holds a fallback LLM key, so the panel works
   *  without a user-supplied key. */
  serverKeyAvailable?: boolean;
  /** Called by the footer's Cancel button, which closes the dialog.
   *  Omitted, no Cancel is drawn. */
  onClose?: () => void;
}

const AUTO_OPEN_DELAY_MS = 1500;

/**
 * Whole-dashboard generation, as a tab of the New Dashboard dialog. Pick a
 * project (and optionally which of its table collections), say what the
 * dashboard should show, and watch the plan, then each component, land.
 * The result is saved server-side as an AI draft; the panel hands off to
 * the editor, where the draft banner takes over.
 */
const GenerateDashboardPanel: React.FC<Props> = ({
  projects,
  loadProject,
  onOpen,
  serverKeyAvailable = false,
  onClose,
}) => {
  const session = useAISession(GENERATE_DASHBOARD_SESSION_ID);
  const { run, cancel, pending, state } = useGenerateDashboard();

  const [projectId, setProjectId] = useState<string | null>(
    projects.length === 1 ? projects[0].id : null,
  );
  const [collections, setCollections] = useState<GenerateDataCollection[]>([]);
  const [collectionsLoading, setCollectionsLoading] = useState(false);
  const [collectionsError, setCollectionsError] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [prompt, setPrompt] = useState('');
  const [title, setTitle] = useState('');

  // The chosen project's table collections; the selection resets with it.
  useEffect(() => {
    setSelectedIds([]);
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

  // One navigation per draft: a click on "Open in editor" ahead of the timer
  // is the same hand-off, not a second one.
  const openedRef = useRef<string | null>(null);
  const openEditor = useCallback(
    (id: string) => {
      if (openedRef.current === id) return;
      openedRef.current = id;
      onOpen(id);
    },
    [onOpen],
  );
  const draftId = state.dashboard?.dashboard_id ?? null;
  useEffect(() => {
    if (!draftId) return;
    const timer = window.setTimeout(() => openEditor(draftId), AUTO_OPEN_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [draftId, openEditor]);

  const hasCreds = Boolean(session.llmKey) || serverKeyAvailable;
  const canRun = Boolean(projectId) && hasCreds && !pending;

  const submit = () => {
    if (!canRun || !projectId) return;
    void run({
      project_id: projectId,
      prompt: prompt.trim(),
      title: title.trim() || null,
      data_collection_ids: selectedIds,
    });
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
        disabled={pending}
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
        disabled={pending || !projectId || collections.length === 0}
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

      {!serverKeyAvailable && <AIKeySection dashboardId={GENERATE_DASHBOARD_SESSION_ID} />}

      {/* Same footer as the Create and Import tabs of this dialog: centred,
          Cancel then the primary. Stopping a run replaces the primary in
          place so the row never shifts under the pointer. */}
      <Group justify="center" gap="md" mt="md">
        {onClose && (
          <Button variant="outline" color="gray" radius="md" onClick={onClose} disabled={pending}>
            Cancel
          </Button>
        )}
        {pending ? (
          <Button color="red" variant="outline" radius="md" onClick={cancel}>
            Stop generating
          </Button>
        ) : (
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
      </Group>

      {started && (
        <Paper withBorder radius="md" p="md" style={{ borderColor: aiColorVar(3) }}>
          <Stack gap="md">
            <GenerationProgress state={state} pending={pending} />

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
                  <Text size="sm">Saved as an AI draft. Opening the editor...</Text>
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
