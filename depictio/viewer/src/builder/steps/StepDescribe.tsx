/**
 * Describe step: the first (and only input) screen of the AI source mode.
 *
 * Prompt first. The component type and the data collection default to
 * "Auto": the server reads the prompt against the project's collections
 * (preferring those already on the dashboard), picks both, drafts the
 * component and says what it chose. Either can be pinned here, in the two
 * option panels under the prompt: the type through the builder's own type
 * tiles (compact, with an Auto tile in front) and the collection through
 * chips, dashboard collections first. Both appear on the Design step, whose
 * Back button returns here with the used values pinned, so a wrong guess
 * costs one regenerate.
 *
 * The answer from /ai/component-from-prompt is a validated lite component
 * dict; `initFromAI` seeds the store with the resolved type and collection
 * and `applyLiteComponent` drops the dict in, then the per-type builder and
 * its live preview take over on Design, where the AI button reads "Refine
 * with AI".
 *
 * Figures also get the data-grounded suggestions mode (/ai/suggest-figures)
 * once a collection is resolvable client-side (pinned, or the dashboard uses
 * exactly one). Typed suggestions for every component type are the next lot.
 */
import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Code,
  Group,
  Paper,
  SegmentedControl,
  SimpleGrid,
  Stack,
  Text,
  Textarea,
  Title,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { fetchDashboard, fetchProjectFromDashboard } from 'depictio-react-core';
import type { WorkflowEntry } from 'depictio-react-core';
import {
  AI_COLOR,
  AI_ICON,
  AIKeySection,
  aiColorVar,
  useAIHealth,
  useAISession,
  useComponentFromPrompt,
  useSuggestFigures,
} from 'depictio-react-ai';
import type {
  ComponentType as AIComponentType,
  ComponentFromPromptResponse,
  PlotSuggestion,
} from 'depictio-react-ai';
import { useServerStatus } from '../../hooks/useServerStatus';
import { useBuilderStore } from '../store/useBuilderStore';
import type { AIRouting, ComponentType } from '../store/useBuilderStore';
import { applyLiteComponent } from '../store/applyLiteComponent';
import { COMPONENT_TYPES, getComponentTypeMeta } from '../componentTypes';
import { TypeCard } from './StepType';
import type { TypeCardMeta } from './StepType';
import AISuggestionPreview from '../ai/AISuggestionPreview';
import CollectionPicker, { AUTO_COLLECTION } from '../ai/CollectionPicker';
import type { CollectionOption } from '../ai/CollectionPicker';

const AUTO = 'auto';

/** The "let the AI choose" tile, drawn with the same card as the nine types
 *  so the grid reads as one set of choices. */
const AUTO_TYPE: TypeCardMeta = {
  type: AUTO,
  label: 'Auto',
  description: 'Let the AI choose',
  icon: AI_ICON,
  iconBg: aiColorVar(6),
};

/** One example per type, so the empty textarea already shows the level of
 *  detail that works: what to show, split by what, in which form. */
const PROMPT_EXAMPLES: Record<ComponentType | typeof AUTO, string> = {
  auto: 'e.g. "Median body mass per species" or "A filter on island"',
  figure: 'e.g. "Box plot of body mass per species, coloured by sex"',
  card: 'e.g. "Average flipper length, with a per-species breakdown"',
  interactive: 'e.g. "A multi-select on island"',
  table: 'e.g. "A compact table of the measurement columns, 15 rows per page"',
  multiqc: 'e.g. "The per-sequence quality scores plot from FastQC"',
  image: 'e.g. "A grid of the images, four per row, with their sample name"',
  map: 'e.g. "Sampling sites coloured by depth"',
  text: 'e.g. "A two-sentence introduction for the quality-control section"',
  advanced_viz: 'e.g. "A volcano plot of log2 fold change against adjusted p-value"',
};

type PromptMode = 'prompt' | 'suggest';

/** Flatten the project's workflows into picker options, dashboard collections
 *  first so "the only candidate" and the picker's first chip agree with what
 *  the server prefers. */
function toCollectionOptions(
  workflows: WorkflowEntry[],
  usedDcIds: Set<string>,
): CollectionOption[] {
  const options = workflows.flatMap((wf) =>
    (wf.data_collections ?? []).map((dc) => ({
      dcId: dc._id,
      tag: dc.data_collection_tag ?? dc._id,
      wfId: wf._id,
      wfTag: wf.workflow_tag ?? wf.name ?? null,
      type: dc.config?.type ?? null,
      onDashboard: usedDcIds.has(dc._id),
    })),
  );
  return options.sort((a, b) => Number(b.onDashboard) - Number(a.onDashboard));
}

const StepDescribe: React.FC = () => {
  const dashboardId = useBuilderStore((s) => s.dashboardId);
  const storedType = useBuilderStore((s) => s.componentType);
  const storedDcId = useBuilderStore((s) => s.dcId);
  const initFromAI = useBuilderStore((s) => s.initFromAI);

  const { features: serverFeatures } = useServerStatus();
  const aiHealth = useAIHealth(serverFeatures.ai);
  const session = useAISession(dashboardId ?? '');
  const hasCreds = Boolean(session.llmKey) || aiHealth?.server_key_configured === true;

  const { run, pending, error } = useComponentFromPrompt(dashboardId ?? '');
  const suggest = useSuggestFigures(dashboardId ?? '');
  const [prompt, setPrompt] = useState('');
  const [mode, setMode] = useState<PromptMode>('prompt');
  // Coming back from Design pins what was used, so a correction is one
  // change away instead of a fresh guess.
  const [typeSel, setTypeSel] = useState<string>(storedType ?? AUTO);
  const [dcSel, setDcSel] = useState<string>(storedDcId ?? AUTO_COLLECTION);

  const [collections, setCollections] = useState<CollectionOption[] | null>(null);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    if (!dashboardId) return;
    let cancelled = false;
    Promise.all([fetchProjectFromDashboard(dashboardId), fetchDashboard(dashboardId)])
      .then(([{ project }, dash]) => {
        if (cancelled) return;
        const used = new Set(
          ((dash.stored_metadata ?? []) as { dc_id?: string | null }[])
            .map((m) => (m.dc_id ? String(m.dc_id) : null))
            .filter((id): id is string => Boolean(id)),
        );
        setCollections(toCollectionOptions(project.workflows ?? [], used));
        setProjectId(project._id ?? null);
      })
      .catch((err) => {
        if (cancelled) return;
        setLoadError(err instanceof Error ? err.message : String(err));
        setCollections([]);
      });
    return () => {
      cancelled = true;
    };
  }, [dashboardId]);

  const byId = useMemo(
    () => new Map((collections ?? []).map((c) => [c.dcId, c])),
    [collections],
  );
  const dashboardCollections = useMemo(
    () => (collections ?? []).filter((c) => c.onDashboard),
    [collections],
  );

  const isText = typeSel === 'text';
  const effectiveDcSel = isText ? AUTO_COLLECTION : dcSel;
  // The figure suggestions need a concrete collection before any answer
  // exists: the pinned one, or the dashboard's only one.
  const suggestDcId = ((): string | null => {
    if (typeSel !== 'figure') return null;
    if (dcSel !== AUTO_COLLECTION) return dcSel;
    if (dashboardCollections.length === 1) return dashboardCollections[0].dcId;
    return null;
  })();
  const suggestMode = Boolean(suggestDcId) && mode === 'suggest';

  // Suggestions are per collection: switching the target drops the old list
  // so a stale suggestion is never applied against the wrong columns.
  useEffect(() => {
    suggest.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [suggestDcId]);

  if (!dashboardId) return null;

  const canGenerate = Boolean(prompt.trim()) && hasCreds && !pending && collections !== null;
  const canSuggest = hasCreds && Boolean(suggestDcId) && !suggest.pending;

  /** Pin a type (or Auto). Suggestions only exist for figures, so any other
   *  pick drops back to the prompt. */
  const pickType = (type: string) => {
    setTypeSel(type);
    if (type !== 'figure') setMode('prompt');
  };

  const routingFor = (
    dcId: string | null,
    routing: ComponentFromPromptResponse['routing'],
    fallback: AIRouting['source'],
  ): AIRouting => ({
    source: routing?.source ?? fallback,
    reason: routing?.reason ?? null,
    dcTag: dcId ? (byId.get(dcId)?.tag ?? null) : null,
    alternatives: (routing?.alternatives ?? []).map((a) => ({
      data_collection_id: a.data_collection_id,
      data_collection_tag: a.data_collection_tag,
    })),
  });

  /** Seed the store with the resolved type and collection, then the dict. */
  const land = (
    componentType: ComponentType,
    dcId: string | null,
    wfIdFromServer: string | null | undefined,
    parsed: Record<string, unknown>,
    source: { prompt?: string },
    routing: AIRouting | null,
  ) => {
    const dc = dcId ? byId.get(dcId) : undefined;
    initFromAI({
      componentType,
      wfId: dc?.wfId ?? wfIdFromServer ?? null,
      dcId,
      projectId,
      dcConfigType: dc?.type ?? (componentType === 'text' ? null : 'table'),
      source: { flow: 'component-from-prompt', ...source },
      routing,
    });
    applyLiteComponent(parsed);
  };

  const generate = async () => {
    if (!canGenerate) return;
    const text = prompt.trim();
    const pinnedType = typeSel === AUTO ? null : (typeSel as AIComponentType);
    const pinnedDc = isText || dcSel === AUTO_COLLECTION ? null : dcSel;
    try {
      const res = await run({
        prompt: text,
        component_type: pinnedType,
        data_collection_id: pinnedDc,
        dashboard_id: dashboardId,
        current: null,
      });
      const usedType = res.component_type as ComponentType;
      const usedDc = usedType === 'text' ? null : (res.data_collection_id ?? pinnedDc);
      const routing =
        usedType === 'text' && !res.routing
          ? null
          : routingFor(usedDc, res.routing, pinnedType && pinnedDc ? 'user' : 'auto');
      land(usedType, usedDc, res.workflow_id, res.parsed, { prompt: text }, routing);
    } catch {
      // useComponentFromPrompt surfaces the failure through `error`.
    }
  };

  const useSuggestion = (s: PlotSuggestion) => {
    if (!suggestDcId) return;
    // Same shape /ai/component-from-prompt returns for a figure, so the
    // hydration path is the one the prompt mode uses.
    land(
      'figure',
      suggestDcId,
      null,
      { component_type: 'figure', visu_type: s.visu_type, dict_kwargs: s.dict_kwargs, title: s.title },
      { prompt: s.title },
      routingFor(suggestDcId, null, dcSel === AUTO_COLLECTION ? 'single' : 'user'),
    );
  };

  const typeSummary =
    typeSel === AUTO ? 'Auto: chosen from the prompt' : getComponentTypeMeta(typeSel as ComponentType).label;
  const dcSummary = ((): string => {
    if (isText) return 'Not needed for text';
    if (effectiveDcSel !== AUTO_COLLECTION) {
      return byId.get(effectiveDcSel)?.tag ?? effectiveDcSel;
    }
    if (dashboardCollections.length === 1) {
      return `Auto: ${dashboardCollections[0].tag} (the dashboard's only collection)`;
    }
    return 'Auto: chosen from the prompt, dashboard collections first';
  })();

  return (
    <Stack gap="lg" pt="md" maw={1040} mx="auto">
      <Stack gap={4} align="center">
        <Title order={3} ta="center" fw={700}>
          Describe the component
        </Title>
        <Text size="sm" c="gray" ta="center">
          Say what it should show. The AI picks the kind of component and the data
          collection unless you pin them below.
        </Text>
        {session.model && (
          <Badge variant="light" color="blue" mt={4}>
            {session.model.split('/').pop()}
          </Badge>
        )}
      </Stack>

      {!hasCreds && (
        <Paper withBorder radius="md" p="sm">
          <Text size="sm" mb="xs">
            The server has no LLM key configured. Add your own to use the assistant.
          </Text>
          <AIKeySection dashboardId={dashboardId} />
        </Paper>
      )}

      {loadError && (
        <Alert color="yellow" variant="light" title="Project collections unavailable">
          <Text size="xs">{loadError}</Text>
        </Alert>
      )}

      {/* 1. The prompt (or, for a figure with a known collection, suggestions). */}
      <Paper withBorder radius="md" p="md">
        <Stack gap="sm">
          <Group justify="space-between" align="center">
            <Text fw={600} size="sm">
              What should it show?
            </Text>
            {suggestDcId && (
              <SegmentedControl
                size="xs"
                color={AI_COLOR}
                value={mode}
                onChange={(v) => setMode(v as PromptMode)}
                data={[
                  { value: 'prompt', label: 'Describe' },
                  { value: 'suggest', label: 'Suggestions' },
                ]}
                data-testid="ai-figure-mode"
              />
            )}
          </Group>

          {!suggestMode && (
            <Textarea
              placeholder={PROMPT_EXAMPLES[typeSel as ComponentType | typeof AUTO] ?? PROMPT_EXAMPLES.auto}
              value={prompt}
              onChange={(e) => setPrompt(e.currentTarget.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                  e.preventDefault();
                  void generate();
                }
              }}
              autosize
              minRows={3}
              maxRows={8}
              disabled={pending}
              data-testid="ai-describe-prompt"
            />
          )}

          {suggestMode && (
            <Stack gap="xs">
              {suggest.suggestions.length === 0 && !suggest.pending && (
                <Text size="sm" c="dimmed" ta="center">
                  The AI reads the collection's columns and proposes a few plots
                  grounded in the actual data.
                </Text>
              )}
              {suggest.suggestions.map((s, i) => (
                <Paper key={i} withBorder radius="md" p="sm" data-testid={`ai-suggestion-${i}`}>
                  <Stack gap={6}>
                    <Group gap="xs" align="center" wrap="nowrap">
                      <Badge size="xs" variant="light" color={AI_COLOR}>
                        {s.visu_type}
                      </Badge>
                      <Text size="sm" fw={600} style={{ flex: 1 }}>
                        {s.title}
                      </Text>
                      <Button
                        size="compact-xs"
                        variant="light"
                        color={AI_COLOR}
                        onClick={() => useSuggestion(s)}
                        data-testid={`ai-suggestion-use-${i}`}
                      >
                        Use this
                      </Button>
                    </Group>
                    <Text size="xs" c="dimmed">
                      {s.explanation}
                    </Text>
                    {suggestDcId && (
                      <AISuggestionPreview
                        suggestion={s}
                        dcId={suggestDcId}
                        wfId={byId.get(suggestDcId)?.wfId ?? null}
                        dashboardId={dashboardId}
                      />
                    )}
                    {s.code && (
                      <Code block fz={11}>
                        {s.code}
                      </Code>
                    )}
                  </Stack>
                </Paper>
              ))}
            </Stack>
          )}

          {(suggestMode ? suggest.error : error) && (
            <Alert color="red" variant="light" title="AI request failed">
              <Text size="xs" style={{ whiteSpace: 'pre-wrap' }}>
                {suggestMode ? suggest.error : error}
              </Text>
            </Alert>
          )}

          <Group justify="flex-end" align="center" gap="md">
            {!suggestMode && (
              <Text size="xs" c="dimmed">
                Cmd/Ctrl+Enter to generate
              </Text>
            )}
            {suggestMode ? (
              <Button
                variant="filled"
                color={AI_COLOR}
                leftSection={<Icon icon={AI_ICON} width={14} />}
                onClick={() => void (suggestDcId && suggest.run(suggestDcId).catch(() => {}))}
                disabled={!canSuggest}
                loading={suggest.pending}
                data-testid="ai-suggest-run"
              >
                {suggest.suggestions.length > 0 ? 'Suggest again' : 'Suggest'}
              </Button>
            ) : (
              <Button
                variant="filled"
                color={AI_COLOR}
                leftSection={<Icon icon={AI_ICON} width={14} />}
                onClick={() => void generate()}
                disabled={!canGenerate}
                loading={pending}
                data-testid="ai-describe-generate"
              >
                Generate
              </Button>
            )}
          </Group>
        </Stack>
      </Paper>

      {/* 2. The two things the AI decides unless pinned. */}
      <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
        <Paper withBorder radius="md" p="md">
          <Stack gap="sm">
            <Stack gap={0}>
              <Text fw={600} size="sm">
                Component type
              </Text>
              <Text size="xs" c="dimmed" data-testid="ai-describe-type-summary">
                {typeSummary}
              </Text>
            </Stack>
            <SimpleGrid cols={{ base: 3, xs: 5 }} spacing="xs" data-testid="ai-describe-type">
              <TypeCard
                meta={AUTO_TYPE}
                compact
                accent={AI_COLOR}
                selected={typeSel === AUTO}
                onClick={() => pickType(AUTO)}
                testId="ai-describe-type-auto"
              />
              {COMPONENT_TYPES.map((t) => (
                <TypeCard
                  key={t.type}
                  meta={t}
                  compact
                  accent={AI_COLOR}
                  selected={typeSel === t.type}
                  onClick={() => pickType(t.type)}
                  testId={`ai-describe-type-${t.type}`}
                />
              ))}
            </SimpleGrid>
          </Stack>
        </Paper>

        <Paper withBorder radius="md" p="md">
          <Stack gap="sm">
            <Stack gap={0}>
              <Text fw={600} size="sm">
                Data collection
              </Text>
              <Text size="xs" c="dimmed" data-testid="ai-describe-dc-summary">
                {dcSummary}
              </Text>
            </Stack>
            <CollectionPicker
              collections={collections}
              value={effectiveDcSel}
              onChange={setDcSel}
              disabled={isText}
              disabledReason="Text is written with the dashboard as context, not from a collection."
            />
          </Stack>
        </Paper>
      </SimpleGrid>
    </Stack>
  );
};

export default StepDescribe;
