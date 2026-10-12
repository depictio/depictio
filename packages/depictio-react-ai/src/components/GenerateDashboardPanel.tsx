import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  MultiSelect,
  Progress,
  Select,
  Stack,
  Text,
  Textarea,
  TextInput,
  Title,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { GENERATE_DASHBOARD_SESSION_ID, useGenerateDashboard } from '../hooks';
import { AI_COLOR, AI_ICON } from '../icons';
import { useAISession } from '../store';
import type { BudgetTick, GeneratedComponentEvent, PlannedComponent } from '../types';
import AIKeySection from './AIKeySection';

export interface GenerateProjectOption {
  id: string;
  name: string;
}

export interface GenerateDataCollection {
  id: string;
  /** Label shown in the picker, normally the collection tag. */
  tag: string;
  /** Collection type as the project declares it ('table', 'multiqc', ...);
   *  the panel offers tables only, the one kind generation reads. */
  type: string;
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
}

const AUTO_OPEN_DELAY_MS = 1500;

type RowStatus = GeneratedComponentEvent['status'] | 'pending';

const ROW_BADGE: Record<RowStatus, { color: string; label: string }> = {
  pending: { color: 'gray', label: 'planned' },
  ok: { color: 'teal', label: 'ok' },
  repaired: { color: 'yellow', label: 'repaired' },
  dropped: { color: 'red', label: 'dropped' },
};

interface Row {
  tag: string;
  section: string;
  component_type: string;
  status: RowStatus;
  attempts?: number;
  error?: string | null;
}

/** Plan rows first, in plan order, each carrying its latest outcome; then
 *  any reported tag the plan did not name, so a row never goes missing. */
function mergeRows(planned: PlannedComponent[], events: GeneratedComponentEvent[]): Row[] {
  const byTag = new Map(events.map((e) => [e.tag, e]));
  const rows: Row[] = planned.map((p) => {
    const e = byTag.get(p.tag);
    return {
      tag: p.tag,
      section: p.section,
      component_type: p.component_type,
      status: e?.status ?? 'pending',
      attempts: e?.attempts,
      error: e?.error,
    };
  });
  const known = new Set(planned.map((p) => p.tag));
  for (const e of events) {
    if (!known.has(e.tag)) rows.push({ ...e });
  }
  return rows;
}

/** Tokens and wall clock both cap a run; the bar tracks whichever is closer
 *  to its limit. Null when no budget tick has arrived yet. */
function budgetPercent(budget: BudgetTick | null): number | null {
  if (!budget) return null;
  const tokenPct = budget.max_tokens > 0 ? (budget.tokens_used / budget.max_tokens) * 100 : 0;
  const secondsPct = budget.max_seconds > 0 ? (budget.seconds / budget.max_seconds) * 100 : 0;
  return Math.min(100, Math.max(tokenPct, secondsPct));
}

function sectionNames(sections: { name: string }[]): string {
  return sections.map((s) => s.name).join(', ');
}

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

  const budgetPct = budgetPercent(state.budget);
  const rows = mergeRows(state.plan?.components ?? [], state.components);
  const draft = state.dashboard;

  function collectionsPlaceholder(): string {
    if (!projectId) return 'Select a project first';
    if (collectionsLoading) return 'Loading collections';
    if (collections.length === 0) return 'No table collections in this project';
    return 'All table collections';
  }

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

      <Group justify="flex-end" gap="md">
        {pending ? (
          <Button color="red" variant="light" onClick={cancel}>
            Cancel
          </Button>
        ) : (
          <Button
            color={AI_COLOR}
            leftSection={<Icon icon={AI_ICON} width={16} />}
            disabled={!canRun}
            onClick={submit}
            data-testid="generate-dashboard-run"
          >
            Generate
          </Button>
        )}
      </Group>

      {pending && (
        <Group gap="xs">
          <Loader size="xs" />
          <Text size="sm" c="dimmed">
            {state.status || 'working'}
          </Text>
          {state.budget && (
            <Text size="xs" c="dimmed" ml="auto">
              {state.budget.tokens_used.toLocaleString()} tokens ·{' '}
              {Math.round(state.budget.seconds)}s
            </Text>
          )}
        </Group>
      )}
      {budgetPct !== null && pending && <Progress value={budgetPct} size="xs" color={AI_COLOR} />}

      {state.plan && (
        <Alert
          variant="light"
          color={AI_COLOR}
          icon={<Icon icon="material-symbols:route" width={16} />}
          title={state.plan.title || 'Plan'}
          data-testid="generate-plan"
        >
          <Stack gap={4}>
            {state.plan.subtitle && <Text size="sm">{state.plan.subtitle}</Text>}
            <Text size="xs" c="dimmed">
              {state.plan.components.length} components
              {state.plan.filter_sections.length > 0 &&
                ` · filters: ${sectionNames(state.plan.filter_sections)}`}
              {state.plan.grid_sections.length > 0 &&
                ` · sections: ${sectionNames(state.plan.grid_sections)}`}
            </Text>
          </Stack>
        </Alert>
      )}

      {rows.length > 0 && (
        <Stack gap={4}>
          <Title order={6}>Components</Title>
          {rows.map((row) => (
            <Group
              key={row.tag}
              gap="xs"
              wrap="nowrap"
              data-testid="generate-progress-component"
              data-tag={row.tag}
              data-status={row.status}
            >
              <Badge size="sm" variant="light" color={ROW_BADGE[row.status].color} miw={76}>
                {ROW_BADGE[row.status].label}
              </Badge>
              <Text size="sm" fw={500}>
                {row.tag}
              </Text>
              <Text size="xs" c="dimmed">
                {row.component_type} · {row.section}
              </Text>
              {row.attempts !== undefined && row.attempts > 1 && (
                <Text size="xs" c="dimmed">
                  {row.attempts} attempts
                </Text>
              )}
              {row.error && (
                <Text size="xs" c="red" lineClamp={1} title={row.error} style={{ minWidth: 0 }}>
                  {row.error}
                </Text>
              )}
            </Group>
          ))}
        </Stack>
      )}

      {state.error && (
        <Alert variant="light" color="red" title="Generation failed" data-testid="generate-error">
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
  );
};

export default GenerateDashboardPanel;
