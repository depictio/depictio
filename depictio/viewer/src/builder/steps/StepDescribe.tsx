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
 * The Suggestions mode asks the other question, "what would you add to this
 * dashboard?" (/ai/suggest-components). The same two pins scope it: nothing
 * pinned means a mix of types across the dashboard's collections, a pinned
 * type or collection narrows the answer. Each suggestion is a validated lite
 * component, so "Use this" lands through the same hydration path as a
 * prompt. Under the AI's list sit the catalog's offers for the same scope,
 * deterministic and free of any model call.
 */
import React, { useEffect, useMemo, useRef, useState } from 'react';
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
import {
  fetchCatalogCompose,
  fetchDashboard,
  fetchProjectFromDashboard,
} from 'depictio-react-core';
import type {
  CatalogModule,
  CatalogOutputMatch,
  CatalogRender,
  WorkflowEntry,
} from 'depictio-react-core';
import {
  AI_COLOR,
  AI_ICON,
  AIKeySection,
  aiColorVar,
  useAIHealth,
  useAISession,
  useComponentFromPrompt,
  useSuggestComponents,
} from 'depictio-react-ai';
import type {
  ComponentType as AIComponentType,
  ComponentFromPromptResponse,
  ComponentSuggestion,
} from 'depictio-react-ai';
import { useServerStatus } from '../../hooks/useServerStatus';
import { useBuilderStore } from '../store/useBuilderStore';
import type { AIRouting, AISource, ComponentType } from '../store/useBuilderStore';
import { applyLiteComponent } from '../store/applyLiteComponent';
import { COMPONENT_TYPES, getComponentTypeMeta } from '../componentTypes';
import { TypeCard } from './StepType';
import type { TypeCardMeta } from './StepType';
import AISuggestionPreview from '../ai/AISuggestionPreview';
import CollectionPicker, { AUTO_COLLECTION } from '../ai/CollectionPicker';
import type { CollectionOption } from '../ai/CollectionPicker';
import { catalogUseRef, matchTitle } from '../catalog/CatalogPreviewPanel';
import { buildConfigFromRender } from '../catalog/renderConfig';

const AUTO = 'auto';

/** How many suggestions one Suggest asks for. */
const SUGGEST_N = 4;
/** How many catalog offers the Suggestions mode lists under the AI's. */
const MAX_CATALOG_OFFERS = 6;

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

/** One catalog render offered in the Suggestions mode, with the tool and the
 *  matched output it came from (what `initFromCatalog` needs as provenance). */
interface CatalogOffer {
  toolId: string;
  toolName: string;
  match: CatalogOutputMatch;
  render: CatalogRender;
}

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

/** One line saying what the suggested component is made of, per type, read
 *  off its lite dict. The title says why; this says what, so two suggestions
 *  with similar titles can be told apart before a preview renders. */
function summarizeComponent(s: ComponentSuggestion): string {
  const c = s.component;
  const str = (k: string): string | null => (typeof c[k] === 'string' ? (c[k] as string) : null);
  const obj = (k: string): Record<string, unknown> => {
    const value = c[k];
    return value && typeof value === 'object' ? (value as Record<string, unknown>) : {};
  };
  switch (s.component_type) {
    case 'card':
      return [str('aggregation'), str('column_name')].filter(Boolean).join(' of ');
    case 'interactive':
      return `${str('interactive_component_type') ?? 'widget'} on ${str('column_name') ?? '?'}`;
    case 'figure': {
      const kwargs = obj('dict_kwargs');
      const axes = ['x', 'y', 'color']
        .filter((k) => typeof kwargs[k] === 'string')
        .map((k) => `${k}=${String(kwargs[k])}`);
      return [str('visu_type'), ...axes].filter(Boolean).join(' ');
    }
    case 'table': {
      const count = Array.isArray(c.columns)
        ? c.columns.length
        : Object.keys(obj('cols_json')).length;
      return `${count} column${count === 1 ? '' : 's'}`;
    }
    case 'advanced_viz': {
      const roles = Object.entries(obj('config'))
        .filter(([k, v]) => k.endsWith('_col') && typeof v === 'string')
        .map(([k, v]) => `${k.slice(0, -4)}=${String(v)}`);
      return `${str('viz_kind') ?? 'viz'}${roles.length ? `: ${roles.join(', ')}` : ''}`;
    }
    case 'map':
      return `lat=${str('lat_column') ?? str('lat') ?? '?'} lon=${str('lon_column') ?? str('lon') ?? '?'}`;
    case 'multiqc':
      return [str('selected_module') ?? str('module'), str('selected_plot') ?? str('plot')]
        .filter(Boolean)
        .join(' / ');
    case 'text': {
      const body = str('body') ?? str('content') ?? '';
      return body.length > 80 ? `${body.slice(0, 80)}...` : body;
    }
    default:
      return '';
  }
}

/** What distinguishes a catalog render from its siblings on the same output,
 *  without the viz-kind labels the catalog tab loads separately. */
function offerVariant(render: CatalogRender): string {
  if (render.kind) return render.kind.replace(/_/g, ' ');
  if (render.visu_type) return render.visu_type;
  if (render.aggregation)
    return render.column ? `${render.aggregation} of ${render.column}` : render.aggregation;
  return '';
}

/** The figure grammar of a suggestion, when its lite component carries one
 *  to render a preview from (only figures do). */
function figureGrammar(
  s: ComponentSuggestion,
): { visuType: string; dictKwargs: Record<string, unknown> } | null {
  if (s.component_type !== 'figure') return null;
  const { visu_type: visuType, dict_kwargs: dictKwargs } = s.component;
  if (typeof visuType !== 'string' || !dictKwargs || typeof dictKwargs !== 'object') return null;
  return { visuType, dictKwargs: dictKwargs as Record<string, unknown> };
}

interface SuggestionCardProps {
  suggestion: ComponentSuggestion;
  index: number;
  /** The collection's workflow, resolved by the caller against the project. */
  wfId: string | null;
  dashboardId: string;
  onUse: () => void;
}

/** One AI suggestion: what it is, why it was proposed, what it is made of,
 *  and a live preview when it is a figure. */
const SuggestionCard: React.FC<SuggestionCardProps> = ({
  suggestion,
  index,
  wfId,
  dashboardId,
  onUse,
}) => {
  const meta = getComponentTypeMeta(suggestion.component_type as ComponentType);
  const summary = summarizeComponent(suggestion);
  const figure = figureGrammar(suggestion);
  const dcId = suggestion.data_collection_id;
  return (
    <Paper
      withBorder
      radius="md"
      p="sm"
      data-testid={`ai-suggestion-${index}`}
      data-component-type={suggestion.component_type}
      data-origin={suggestion.origin}
    >
      <Stack gap={6}>
        <Group gap="xs" align="center" wrap="nowrap">
          <Badge
            size="sm"
            variant="light"
            color={AI_COLOR}
            leftSection={<Icon icon={meta.icon} width={12} />}
            style={{ flexShrink: 0 }}
          >
            {meta.label}
          </Badge>
          {suggestion.data_collection_tag && (
            <Badge size="sm" variant="outline" color="gray" style={{ flexShrink: 0 }}>
              {suggestion.data_collection_tag}
            </Badge>
          )}
          <Text size="sm" fw={600} style={{ flex: 1, minWidth: 0 }} lineClamp={1}>
            {suggestion.title}
          </Text>
          <Button
            size="compact-xs"
            variant="light"
            color={AI_COLOR}
            onClick={onUse}
            data-testid={`ai-suggestion-use-${index}`}
          >
            Use this
          </Button>
        </Group>
        <Text size="xs" c="dimmed">
          {suggestion.rationale}
        </Text>
        {summary && (
          <Text size="xs" ff="monospace" c="dimmed">
            {summary}
            {suggestion.origin === 'ranked' && (
              <Text span size="xs" c="dimmed">
                {' '}
                (ranked from the data)
              </Text>
            )}
          </Text>
        )}
        {figure && dcId && (
          <AISuggestionPreview
            visuType={figure.visuType}
            dictKwargs={figure.dictKwargs}
            dcId={dcId}
            wfId={wfId}
            dashboardId={dashboardId}
          />
        )}
        {suggestion.code && (
          <Code block fz={11}>
            {suggestion.code}
          </Code>
        )}
      </Stack>
    </Paper>
  );
};

interface CatalogOfferCardProps {
  offer: CatalogOffer;
  index: number;
  pending: boolean;
  disabled: boolean;
  onUse: () => void;
}

/** One catalog offer: the tool output it comes from and the collection it
 *  matched, with no model in the loop. */
const CatalogOfferCard: React.FC<CatalogOfferCardProps> = ({
  offer,
  index,
  pending,
  disabled,
  onUse,
}) => {
  const meta = getComponentTypeMeta(offer.render.component as ComponentType);
  const variant = offerVariant(offer.render);
  return (
    <Paper
      withBorder
      radius="md"
      p="sm"
      data-testid={`ai-catalog-offer-${index}`}
      data-tool-id={offer.toolId}
      data-output-id={offer.match.output_id}
    >
      <Stack gap={6} h="100%" justify="space-between">
        <Stack gap={4}>
          <Group gap="xs" align="center" wrap="nowrap">
            <Badge
              size="sm"
              variant="light"
              color="violet"
              leftSection={<Icon icon={meta.icon} width={12} />}
              style={{ flexShrink: 0 }}
            >
              {meta.label}
            </Badge>
            {variant && variant !== meta.label && (
              <Text size="xs" c="dimmed" lineClamp={1}>
                {variant}
              </Text>
            )}
          </Group>
          <Text size="sm" fw={600} lineClamp={1}>
            {offer.toolName}
            <Text span size="sm" c="dimmed" fw={400}>
              {' '}
              / {matchTitle(offer.match)}
            </Text>
          </Text>
          {offer.match.description && (
            <Text size="xs" c="dimmed" lineClamp={2}>
              {offer.match.description}
            </Text>
          )}
          <Text size="xs" c="dimmed" ff="monospace">
            {offer.match.dc_tag}
          </Text>
        </Stack>
        <Group justify="flex-end">
          <Button
            size="compact-xs"
            variant="light"
            color="violet"
            onClick={onUse}
            loading={pending}
            disabled={disabled}
            data-testid={`ai-catalog-offer-use-${index}`}
          >
            Use this
          </Button>
        </Group>
      </Stack>
    </Paper>
  );
};

const StepDescribe: React.FC = () => {
  const dashboardId = useBuilderStore((s) => s.dashboardId);
  const storedType = useBuilderStore((s) => s.componentType);
  const storedDcId = useBuilderStore((s) => s.dcId);
  const initFromAI = useBuilderStore((s) => s.initFromAI);
  const initFromCatalog = useBuilderStore((s) => s.initFromCatalog);

  const { features: serverFeatures } = useServerStatus();
  const aiHealth = useAIHealth(serverFeatures.ai);
  const session = useAISession(dashboardId ?? '');
  const hasCreds = Boolean(session.llmKey) || aiHealth?.server_key_configured === true;

  const { run, pending, error } = useComponentFromPrompt(dashboardId ?? '');
  const suggest = useSuggestComponents(dashboardId ?? '');
  const [prompt, setPrompt] = useState('');
  const [mode, setMode] = useState<PromptMode>('prompt');
  // Coming back from Design pins what was used, so a correction is one
  // change away instead of a fresh guess.
  const [typeSel, setTypeSel] = useState<string>(storedType ?? AUTO);
  const [dcSel, setDcSel] = useState<string>(storedDcId ?? AUTO_COLLECTION);

  const [collections, setCollections] = useState<CollectionOption[] | null>(null);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // The catalog's offers, fetched once the first time Suggestions opens. The
  // whole compose result is kept and filtered client-side so pinning a type
  // or a collection never re-fetches.
  const [catalogModules, setCatalogModules] = useState<CatalogModule[] | null>(null);
  const catalogRequested = useRef(false);
  const [offerPending, setOfferPending] = useState<number | null>(null);

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

  // No cancellation flag here on purpose: the ref guard already makes this a
  // one-shot, and under StrictMode's double effect run a cancelled first call
  // would leave the guard set with nothing ever arriving.
  useEffect(() => {
    if (mode !== 'suggest' || !projectId || catalogRequested.current) return;
    catalogRequested.current = true;
    fetchCatalogCompose(projectId)
      .then((r) => setCatalogModules(r.modules))
      .catch(() => setCatalogModules([]));
  }, [mode, projectId]);

  const byId = useMemo(
    () => new Map((collections ?? []).map((c) => [c.dcId, c])),
    [collections],
  );
  const dashboardCollections = useMemo(
    () => (collections ?? []).filter((c) => c.onDashboard),
    [collections],
  );
  const dashboardDcIds = useMemo(
    () => new Set(dashboardCollections.map((c) => c.dcId)),
    [dashboardCollections],
  );

  const isText = typeSel === 'text';
  const effectiveDcSel = isText ? AUTO_COLLECTION : dcSel;
  const typePinned = typeSel !== AUTO;
  const dcPinned = effectiveDcSel !== AUTO_COLLECTION;
  const suggestMode = mode === 'suggest';
  // What the two panels below pin, as the server reads them: null is Auto.
  const pinnedType = typePinned ? (typeSel as AIComponentType) : null;
  const pinnedDcId = dcPinned ? effectiveDcSel : null;

  // Suggestions are scoped by the two pins: changing either drops the old
  // list so a stale suggestion is never applied against the wrong collection
  // or shown under the wrong type.
  const resetSuggestions = suggest.reset;
  useEffect(() => {
    resetSuggestions();
  }, [typeSel, dcSel, resetSuggestions]);

  const catalogOffers = useMemo<CatalogOffer[]>(() => {
    const offers: CatalogOffer[] = [];
    for (const mod of catalogModules ?? []) {
      for (const match of mod.matches) {
        const inScope = dcPinned
          ? match.dc_id === effectiveDcSel
          : dashboardDcIds.has(match.dc_id);
        if (!inScope) continue;
        for (const render of match.renders_as) {
          if (typePinned && render.component !== typeSel) continue;
          offers.push({ toolId: mod.tool_id, toolName: mod.tool_name, match, render });
          if (offers.length >= MAX_CATALOG_OFFERS) return offers;
        }
      }
    }
    return offers;
  }, [catalogModules, dcPinned, effectiveDcSel, dashboardDcIds, typePinned, typeSel]);

  if (!dashboardId) return null;

  const canGenerate = Boolean(prompt.trim()) && hasCreds && !pending && collections !== null;
  const canSuggest = hasCreds && !suggest.pending && collections !== null;

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
    source: { flow?: AISource['flow']; prompt?: string },
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
    try {
      const res = await run({
        prompt: text,
        component_type: pinnedType,
        data_collection_id: pinnedDcId,
        dashboard_id: dashboardId,
        current: null,
      });
      const usedType = res.component_type as ComponentType;
      const usedDc = usedType === 'text' ? null : (res.data_collection_id ?? pinnedDcId);
      const routing =
        usedType === 'text' && !res.routing
          ? null
          : routingFor(usedDc, res.routing, pinnedType && pinnedDcId ? 'user' : 'auto');
      land(usedType, usedDc, res.workflow_id, res.parsed, { prompt: text }, routing);
    } catch {
      // useComponentFromPrompt surfaces the failure through `error`.
    }
  };

  const runSuggest = () => {
    if (!canSuggest) return;
    suggest
      .run({ component_type: pinnedType, data_collection_id: pinnedDcId, n: SUGGEST_N })
      .catch(() => {
        // useSuggestComponents surfaces the failure through `error`.
      });
  };

  /** A suggestion's `component` is the same validated lite dict the prompt
   *  flow returns in `parsed`, so it lands through the same path. */
  const landSuggestion = (s: ComponentSuggestion) => {
    land(
      s.component_type as ComponentType,
      s.data_collection_id,
      s.workflow_id,
      s.component,
      { flow: 'suggest-components', prompt: s.title },
      // Text is written from the dashboard, so there is nothing to route;
      // for the others the rationale is the reason the notice shows.
      s.component_type === 'text'
        ? null
        : routingFor(
            s.data_collection_id,
            { source: typePinned && dcPinned ? 'user' : 'auto', reason: s.rationale, alternatives: [] },
            'auto',
          ),
    );
  };

  /** A catalog offer lands the way the Catalog tab lands it: the render is
   *  translated to the builder config and the store is seeded with the
   *  catalog provenance, so the Design step and the saved component are the
   *  same as if it had been picked in that tab. Only MultiQC can fail the
   *  translation (its plot list comes from the collection); the store is
   *  still seeded so the user lands on Design with the collection bound. */
  const landCatalogOffer = async (offer: CatalogOffer, i: number) => {
    if (!projectId) return;
    setOfferPending(i);
    let config: Record<string, unknown> = {};
    try {
      config = await buildConfigFromRender(offer.render, offer.match.dc_id);
    } catch {
      config = {};
    }
    setOfferPending(null);
    initFromCatalog({
      componentType: offer.render.component as ComponentType,
      wfId: offer.match.wf_id,
      dcId: offer.match.dc_id,
      projectId,
      config,
      source: {
        toolId: offer.toolId,
        toolName: offer.toolName,
        outputId: offer.match.output_id,
        description: offer.match.description,
        use: catalogUseRef(offer.toolId, offer.match.output_id, offer.render),
      },
    });
  };

  const typeLabel = typePinned ? getComponentTypeMeta(typeSel as ComponentType).label : null;
  const typeSummary = typeLabel ?? 'Auto: chosen from the prompt';
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
  const scopeCaption =
    [
      typeLabel ? `for ${typeLabel}` : null,
      dcPinned ? `on ${byId.get(effectiveDcSel)?.tag ?? effectiveDcSel}` : null,
    ]
      .filter(Boolean)
      .join(' ') || 'for this dashboard';

  const showEmptyState =
    suggest.suggestions.length === 0 && !suggest.pending && catalogOffers.length === 0;

  return (
    <Stack gap="lg" pt="md" maw={1040} mx="auto">
      <Stack gap={4} align="center">
        <Title order={3} ta="center" fw={700}>
          Describe the component
        </Title>
        <Text size="sm" c="gray" ta="center">
          Say what it should show, or ask for suggestions. The AI picks the kind of
          component and the data collection unless you pin them below.
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

      {/* 1. The prompt, or the AI's suggestions for the current scope. */}
      <Paper withBorder radius="md" p="md">
        <Stack gap="sm">
          <Group justify="space-between" align="center">
            <Text fw={600} size="sm">
              {suggestMode ? 'What would fit this dashboard?' : 'What should it show?'}
            </Text>
            <SegmentedControl
              size="xs"
              color={AI_COLOR}
              value={mode}
              onChange={(v) => setMode(v as PromptMode)}
              data={[
                { value: 'prompt', label: 'Describe' },
                { value: 'suggest', label: 'Suggestions' },
              ]}
              data-testid="ai-describe-mode"
            />
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
              <Text size="xs" c="dimmed" data-testid="ai-suggest-scope">
                Suggestions {scopeCaption}
              </Text>

              {showEmptyState && (
                <Text size="sm" c="dimmed" ta="center" py="sm" data-testid="ai-suggest-empty">
                  No suggestions yet. Suggest asks the AI what would fit this dashboard;
                  catalog offers appear when a collection matches a known tool output.
                </Text>
              )}

              {suggest.suggestions.map((s, i) => (
                <SuggestionCard
                  key={`${s.component_type}-${s.data_collection_id ?? 'none'}-${i}`}
                  suggestion={s}
                  index={i}
                  wfId={byId.get(s.data_collection_id ?? '')?.wfId ?? s.workflow_id ?? null}
                  dashboardId={dashboardId}
                  onUse={() => landSuggestion(s)}
                />
              ))}

              {suggest.warnings.length > 0 && (
                <Text size="xs" c="dimmed" data-testid="ai-suggest-warnings">
                  {suggest.warnings.join(' ')}
                </Text>
              )}
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
                onClick={runSuggest}
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

      {/* 1b. The catalog's offers for the same scope: deterministic, no model. */}
      {suggestMode && catalogOffers.length > 0 && (
        <Paper withBorder radius="md" p="md" data-testid="ai-catalog-offers">
          <Stack gap="sm">
            <Stack gap={0}>
              <Text fw={600} size="sm">
                From the catalog
              </Text>
              <Text size="xs" c="dimmed">
                Known tool outputs matched to {dcPinned ? 'this collection' : "the dashboard's collections"},
                without asking the AI.
              </Text>
            </Stack>
            <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="xs">
              {catalogOffers.map((offer, i) => (
                <CatalogOfferCard
                  key={`${offer.toolId}-${offer.match.output_id}-${offer.match.dc_id}-${i}`}
                  offer={offer}
                  index={i}
                  pending={offerPending === i}
                  disabled={offerPending !== null && offerPending !== i}
                  onUse={() => void landCatalogOffer(offer, i)}
                />
              ))}
            </SimpleGrid>
          </Stack>
        </Paper>
      )}

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
                onClick={() => setTypeSel(AUTO)}
                testId="ai-describe-type-auto"
              />
              {COMPONENT_TYPES.map((t) => (
                <TypeCard
                  key={t.type}
                  meta={t}
                  compact
                  accent={AI_COLOR}
                  selected={typeSel === t.type}
                  onClick={() => setTypeSel(t.type)}
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
