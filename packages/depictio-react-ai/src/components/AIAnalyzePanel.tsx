import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Collapse,
  Group,
  Loader,
  Paper,
  ScrollArea,
  SegmentedControl,
  Stack,
  Text,
  Textarea,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { useAnalyze } from '../hooks';
import { AI_COLOR, AI_ICON, aiColorVar } from '../icons';
import MarkdownLite from './MarkdownLite';
import { useAISession, useAIStore } from '../store';
import type { AIChatMessage } from '../store';
import type { AnalyzeMode } from '../types';
import ActionsPreview, { type ApplyActionsPayload } from './ActionsPreview';
import AIAnalysisModal from './AIAnalysisModal';
import ExecutionTrace from './ExecutionTrace';

/** One prompt/answer round: the unit the transcript is grouped, folded
 *  and cleared by. `id` is the user message's id. */
interface Exchange {
  id: string;
  user: AIChatMessage;
  assistant?: AIChatMessage;
  mode: AnalyzeMode;
}

function groupExchanges(messages: AIChatMessage[]): Exchange[] {
  const out: Exchange[] = [];
  for (const m of messages) {
    if (m.role === 'user') {
      out.push({ id: m.id, user: m, mode: m.mode ?? m.result?.mode ?? 'mutate' });
    } else {
      const last = out[out.length - 1];
      if (last && !last.assistant) {
        last.assistant = m;
        if (m.mode ?? m.result?.mode) last.mode = (m.mode ?? m.result?.mode)!;
      }
    }
  }
  return out;
}

interface Props {
  dashboardId: string;
  /** Optional component the user is currently focused on. */
  selectedComponentId?: string;
  /** Active InteractiveFilter list — forwarded to the backend so the
   *  executor and quantile thresholds see the rows the user sees. */
  activeFilters?: unknown[];
  /** True when the server holds a fallback LLM key, so the panel works
   *  without a user-supplied key. */
  serverKeyAvailable?: boolean;
  /** Apply a resolved plan to the host's stores. When omitted,
   *  ActionsPreview becomes read-only. */
  onApplyActions?: (payload: ApplyActionsPayload) => void;
}

/**
 * Always-visible analyze surface that lives at the top of the dashboard
 * grid. Ask a question, see the trace + answer + proposed actions
 * without losing the dashboard view.
 *
 * Compact by default — a single-line input with a minimal status row.
 * Expands inline when a transcript exists, with a collapse toggle so
 * the user can reclaim vertical space without losing history.
 */
const AIAnalyzePanel: React.FC<Props> = ({
  dashboardId,
  selectedComponentId,
  activeFilters,
  serverKeyAvailable = false,
  onApplyActions,
}) => {
  const session = useAISession(dashboardId);
  const reset = useAIStore((s) => s.reset);
  const removeMessages = useAIStore((s) => s.removeMessages);
  const { run: runAnalyze, cancel } = useAnalyze(dashboardId);
  const [prompt, setPrompt] = useState('');
  const [open, setOpen] = useState(true);
  const [analysisOpen, setAnalysisOpen] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  // The exchange whose plan currently shapes the dashboard. Single-valued
  // on purpose: applying any plan replaces the previous one wholesale, so
  // older exchanges get their Apply back — that IS the "restore an earlier
  // state" affordance.
  const [appliedId, setAppliedId] = useState<string | null>(null);
  // The two prompt levels. 'analyze' (Interpret) is read-only: the answer
  // comes with its execution trace (thought + Polars code per step) and
  // the server strips actions. 'mutate' (Update) may propose dashboard
  // changes the user can apply. Interpret is the default — asking a
  // question should never surface an Apply button unless requested.
  const [promptMode, setPromptMode] = useState<AnalyzeMode>('analyze');

  const hasCreds = Boolean(session.llmKey) || serverKeyAvailable;

  // All messages in the store are analyze messages; component-creation
  // requests go through the builder's AI fill modal, which doesn't
  // append to this transcript.
  const analyzeMessages = session.messages;
  const exchanges = useMemo(() => groupExchanges(analyzeMessages), [analyzeMessages]);

  // Which exchanges are unfolded. A new exchange opens itself and folds
  // the older ones — the fresh answer is what the user is waiting on, the
  // history stays one click away.
  const [openExchanges, setOpenExchanges] = useState<Set<string>>(new Set());
  const lastExchangeId = exchanges[exchanges.length - 1]?.id;
  const prevLastRef = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (lastExchangeId && lastExchangeId !== prevLastRef.current) {
      prevLastRef.current = lastExchangeId;
      setOpenExchanges(new Set([lastExchangeId]));
    }
  }, [lastExchangeId]);

  const toggleExchange = (id: string) =>
    setOpenExchanges((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  useEffect(() => {
    if (!scrollRef.current) return;
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [analyzeMessages.length, session.pending]);

  async function send() {
    const text = prompt.trim();
    if (!text || session.pending || !hasCreds) return;
    setPrompt('');
    setOpen(true);
    await runAnalyze(text, { selectedComponentId, activeFilters, mode: promptMode });
  }

  const hasTranscript = analyzeMessages.length > 0;

  return (
    <Paper
      withBorder
      radius="md"
      p="xs"
      mb="xs"
      style={{ borderColor: aiColorVar(3) }}
    >
      <Stack gap="xs">
        <Group gap="xs" align="center" wrap="nowrap">
          <Icon icon={AI_ICON} width={18} color={aiColorVar(6)} />
          <Text size="sm" fw={600}>
            Ask the dashboard
          </Text>
          {session.model && (
            <Badge size="xs" variant="light" color="blue">
              {session.model.split('/').pop()}
            </Badge>
          )}
          {session.pending && (
            <Group gap={6} ml="xs">
              <Loader size="xs" />
              <Text size="xs" c="dimmed">
                Thinking…
              </Text>
              <Button size="compact-xs" variant="subtle" color="gray" onClick={cancel}>
                Cancel
              </Button>
            </Group>
          )}
          <Group gap={2} ml="auto">
            {hasCreds && (
              <Tooltip label="Deep analysis (read-only report)">
                <Button
                  size="compact-xs"
                  variant="light"
                  color={AI_COLOR}
                  leftSection={<Icon icon={AI_ICON} width={14} />}
                  onClick={() => setAnalysisOpen(true)}
                >
                  Analyze
                </Button>
              </Tooltip>
            )}
            {hasTranscript && (
              <Tooltip label="Clear">
                <ActionIcon
                  variant="subtle"
                  color="gray"
                  onClick={() => reset(dashboardId)}
                  aria-label="Clear analyze transcript"
                >
                  <Icon icon="material-symbols:delete-outline" width={16} />
                </ActionIcon>
              </Tooltip>
            )}
            <Tooltip label={open ? 'Collapse panel' : 'Expand panel'}>
              <ActionIcon
                variant="subtle"
                color="gray"
                onClick={() => setOpen((v) => !v)}
                aria-label="Toggle panel"
              >
                <Icon
                  icon={
                    open
                      ? 'material-symbols:keyboard-arrow-up'
                      : 'material-symbols:keyboard-arrow-down'
                  }
                  width={18}
                />
              </ActionIcon>
            </Tooltip>
          </Group>
        </Group>

        {/* The whole working area collapses, not just the transcript —
            collapsed, the panel is a single header line. */}
        <Collapse in={open}>
        <Stack gap="xs">
        {!hasCreds && (
          <Alert color="yellow" variant="light" p="xs">
            <Text size="xs">
              Set an LLM API key from the dashboard settings drawer to start.
            </Text>
          </Alert>
        )}

        <Group gap="xs" align="center" wrap="wrap">
          <SegmentedControl
            size="xs"
            color={AI_COLOR}
            value={promptMode}
            onChange={(v) => setPromptMode(v as AnalyzeMode)}
            data={[
              { value: 'analyze', label: 'Interpret' },
              { value: 'mutate', label: 'Update dashboard' },
            ]}
            data-testid="ai-prompt-mode"
          />
          <Text size="xs" c="dimmed">
            {promptMode === 'analyze'
              ? 'Read-only: answers your question and shows the code it ran.'
              : 'Proposes dashboard changes (filters, figure tweaks) you can apply.'}
          </Text>
        </Group>

        <Group gap="xs" align="flex-start" wrap="nowrap">
          <Textarea
            placeholder={
              promptMode === 'analyze'
                ? 'e.g. Which samples fail QC, and on which metric?'
                : 'e.g. Show the top 3% by read count. Log-scale the depth figure.'
            }
            value={prompt}
            onChange={(e) => setPrompt(e.currentTarget.value)}
            onKeyDown={(e) => {
              // Enter sends, Shift+Enter inserts a newline — same contract
              // as every chat input.
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
            autosize
            minRows={1}
            maxRows={4}
            disabled={session.pending}
            style={{ flex: 1 }}
          />
          <Button
            size="sm"
            variant="filled"
            color={AI_COLOR}
            leftSection={<Icon icon={AI_ICON} width={14} />}
            onClick={() => void send()}
            disabled={session.pending || !prompt.trim() || !hasCreds}
          >
            Ask
          </Button>
        </Group>

        {hasTranscript && (
            <ScrollArea.Autosize
              viewportRef={scrollRef}
              mah={420}
              offsetScrollbars
            >
              <Stack gap={6} pr="xs">
                {exchanges.map((ex) => {
                  const isOpen = openExchanges.has(ex.id);
                  const a = ex.assistant;
                  const isApplied = a != null && appliedId === a.id;
                  const applicable =
                    a?.result?.actions != null && a.result.mode !== 'analyze' && onApplyActions;
                  const applyExchange = () => {
                    if (!applicable || !a?.result) return;
                    onApplyActions({
                      actions: a.result.actions!,
                      resolved: a.result.resolved_filters ?? [],
                    });
                    setAppliedId(a.id);
                  };
                  return (
                    <Paper key={ex.id} withBorder radius="sm" p={6}>
                      {/* Header row: fold toggle + mode + the question (the
                          text stays selectable — only the chevron toggles). */}
                      <Group gap={6} wrap="nowrap" align="center">
                        <ActionIcon
                          size="sm"
                          variant="subtle"
                          color="gray"
                          onClick={() => toggleExchange(ex.id)}
                          aria-expanded={isOpen}
                          aria-label="Toggle exchange"
                          style={{ flexShrink: 0 }}
                        >
                          <Icon
                            icon={
                              isOpen
                                ? 'material-symbols:keyboard-arrow-up'
                                : 'material-symbols:keyboard-arrow-down'
                            }
                            width={16}
                          />
                        </ActionIcon>
                        <Badge
                          size="xs"
                          variant="light"
                          color={ex.mode === 'mutate' ? 'grape' : AI_COLOR}
                          style={{ flexShrink: 0 }}
                        >
                          {ex.mode === 'mutate' ? 'Update' : 'Interpret'}
                        </Badge>
                        <Text
                          size="xs"
                          fw={600}
                          lineClamp={isOpen ? undefined : 1}
                          style={{ flex: 1, minWidth: 0, userSelect: 'text', cursor: 'text' }}
                        >
                          {ex.user.content}
                        </Text>
                        <Text size="xs" c="dimmed" style={{ flexShrink: 0 }}>
                          {new Date(ex.user.ts).toLocaleTimeString()}
                        </Text>
                        {/* Applied is always visible in the header; the header
                            Apply button only stands in while the exchange is
                            folded — unfolded, the Apply lives inside the
                            actions box next to the plan it applies. Both
                            states render the same button (size, icon, shape)
                            so nothing shifts when a plan is applied — only
                            color and clickability change. */}
                        {applicable && (isApplied || !isOpen) && (
                          <Tooltip
                            label={
                              isApplied
                                ? 'This plan is currently applied'
                                : appliedId
                                  ? 'Apply this plan (replaces the currently applied one)'
                                  : 'Apply this plan to the dashboard'
                            }
                          >
                            <Button
                              size="compact-xs"
                              variant="light"
                              color={isApplied ? 'teal' : AI_COLOR}
                              style={{
                                flexShrink: 0,
                                ...(isApplied ? { cursor: 'default' as const } : {}),
                              }}
                              leftSection={<Icon icon="material-symbols:check" width={12} />}
                              onClick={isApplied ? undefined : applyExchange}
                            >
                              {isApplied ? 'Applied' : 'Apply'}
                            </Button>
                          </Tooltip>
                        )}
                        <Tooltip label="Remove this exchange">
                          <ActionIcon
                            size="sm"
                            variant="subtle"
                            color="gray"
                            aria-label="Remove exchange"
                            style={{ flexShrink: 0 }}
                            onClick={() => {
                              removeMessages(
                                dashboardId,
                                [ex.user.id, a?.id].filter((x): x is string => Boolean(x)),
                              );
                              if (isApplied) setAppliedId(null);
                            }}
                          >
                            <Icon icon="material-symbols:close" width={14} />
                          </ActionIcon>
                        </Tooltip>
                      </Group>

                      <Collapse in={isOpen}>
                        <Stack gap={6} mt={6} pl={22}>
                          {a?.content && <MarkdownLite text={a.content} />}
                          {a && !a.content && !session.pending && (
                            <Text size="xs" c="dimmed" fs="italic">
                              The run ended without an answer — check the execution
                              trace below for the failing step.
                            </Text>
                          )}
                          {a?.steps && a.steps.length > 0 && <ExecutionTrace steps={a.steps} />}
                          {/* A read-only reply never gets an actions surface at
                              all: the server has already stripped them, and
                              rendering an empty preview would imply the model
                              simply had nothing to propose. Unfolded, the plan
                              and its Apply share one box; folded, a compact
                              Apply stands in on the header row. */}
                          {a?.result?.actions && a.result.mode !== 'analyze' && (
                            <ActionsPreview
                              actions={a.result.actions}
                              resolved={a.result.resolved_filters ?? []}
                              applied={isApplied}
                              onApply={applicable ? () => applyExchange() : undefined}
                              applyTooltip={
                                appliedId && !isApplied
                                  ? 'Replaces the currently applied plan'
                                  : undefined
                              }
                            />
                          )}
                          {(a?.result?.warnings?.length ?? 0) > 0 && (
                            <Stack gap={2}>
                              {a?.result?.warnings?.map((w, i) => (
                                <Text key={i} size="xs" c="dimmed">
                                  {w}
                                </Text>
                              ))}
                            </Stack>
                          )}
                        </Stack>
                      </Collapse>
                    </Paper>
                  );
                })}
              </Stack>
            </ScrollArea.Autosize>
        )}
        </Stack>
        </Collapse>
      </Stack>

      <AIAnalysisModal
        dashboardId={dashboardId}
        opened={analysisOpen}
        onClose={() => setAnalysisOpen(false)}
        activeFilters={activeFilters}
      />
    </Paper>
  );
};

export default AIAnalyzePanel;
