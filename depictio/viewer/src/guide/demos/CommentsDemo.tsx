/**
 * The Comments part's demo: one of the dashboard's own figures, drawn by the
 * real renderer in the real chrome, with a made-up thread on it and an
 * annotation the figure itself draws.
 *
 * No comment of the dashboard is read or written here. The comments icon is
 * the chrome's own, fed by a control of this demo (`CommentsControlProvider`),
 * so it opens this demo's thread and never the dashboard's drawer. The
 * annotation goes through the real layer (`AnnotationLayerProvider`): the
 * example range is built from the axis the figure drew, and an editor can draw
 * one more with the chrome's own Annotate button. Both live in this
 * component's state. What the reader can do follows their role: an editor
 * annotates and resolves, a signed-in viewer replies, a guest tries the
 * thread here without an account and is told to sign in on the dashboard
 * itself. A dashboard without a figure falls back to a stand-in tile.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Group,
  Paper,
  Skeleton,
  Stack,
  Text,
  TextInput,
  ThemeIcon,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import {
  AnnotationLayerProvider,
  CommentsControlProvider,
  ComponentRenderer,
  componentSupportsAnnotation,
} from 'depictio-react-core';
import type {
  AnnotateState,
  AnnotateTool,
  AnnotationDraft,
  CommentsControl,
  RenderableAnnotation,
  StoredMetadata,
} from 'depictio-react-core';

import { GuideSandbox } from '../GuideSandbox';
import { pickedSource, useFamilyPick } from '../useGuideSources';
import type { GuideFamily } from '../useGuideSources';

/** Figures whose x axis is a plain number line, where a range is easy to read. */
const SIMPLE_AXIS = new Set(['scatter', 'line', 'histogram', 'box', 'violin', 'strip']);

/** A figure an annotation can be drawn on beats any other figure, and a plain
 *  x/y plot beats a panelled one. */
const annotatableFigureRank = (m: StoredMetadata): number | null => {
  if (m.component_type !== 'figure') return null;
  if (!componentSupportsAnnotation('figure', m as Record<string, unknown>)) return 3;
  return SIMPLE_AXIS.has(String(m.visu_type ?? '')) ? 0 : 1;
};

const NO_FILTERS: never[] = [];

export type CommentsRole = 'moderator' | 'commenter' | 'guest';

interface Message {
  author: string;
  body: string;
}

const OPENING: Message[] = [
  { author: 'Alex', body: 'What explains the points in this range?' },
  { author: 'Sam', body: 'Worth checking against the notes of the run.' },
];

const EXAMPLE_ID = 'guide-example-annotation';

/** The drawn axis of a Plotly figure inside `root`, when it is a number line. */
function numericXRange(root: HTMLElement): [number, number] | null {
  const gd = root.querySelector<HTMLElement & { _fullLayout?: Record<string, unknown> }>(
    '.js-plotly-plot',
  );
  const axis = gd?._fullLayout?.xaxis as { type?: string; range?: unknown } | undefined;
  const range = axis?.range;
  if (
    axis?.type === 'linear' &&
    Array.isArray(range) &&
    typeof range[0] === 'number' &&
    typeof range[1] === 'number' &&
    range[1] > range[0]
  ) {
    return [range[0], range[1]];
  }
  return null;
}

/**
 * The example range, once the figure has drawn: the middle fifth of its x
 * axis, polled for a few seconds because the plot arrives after the data.
 * Null while waiting, and for good when the figure has no number line.
 */
function useExampleRange(host: React.RefObject<HTMLElement | null>, ready: boolean) {
  const [range, setRange] = useState<[number, number] | null>(null);
  useEffect(() => {
    if (!ready) return undefined;
    let tries = 0;
    const timer = window.setInterval(() => {
      tries += 1;
      const found = host.current ? numericXRange(host.current) : null;
      if (found) {
        setRange(found);
        window.clearInterval(timer);
      } else if (tries > 40) {
        window.clearInterval(timer);
      }
    }, 500);
    return () => window.clearInterval(timer);
  }, [host, ready]);
  return range;
}

const Author: React.FC<{ name: string }> = ({ name }) => (
  <Group gap={6} wrap="nowrap">
    <ThemeIcon size={20} radius="xl" variant="light">
      <Text size="10px" fw={700} lh={1}>
        {name[0]}
      </Text>
    </ThemeIcon>
    <Text size="xs" fw={600}>
      {name}
    </Text>
  </Group>
);

/** The tile when the dashboard has no figure to borrow. */
const StandIn: React.FC<{ onClick: () => void }> = ({ onClick }) => (
  <Box className="depictio-guide-tile" p={8}>
    <Group justify="space-between" wrap="nowrap" gap={6} mb={6}>
      <Text size="xs" c="dimmed" truncate>
        A figure
      </Text>
      <Tooltip label="Comments" withArrow>
        <ActionIcon variant="subtle" size="sm" aria-label="Comments" onClick={onClick}>
          <Icon icon="mdi:comment-plus-outline" width={16} height={16} />
        </ActionIcon>
      </Tooltip>
    </Group>
    <Box className="depictio-guide-bars" style={{ height: 70 }}>
      {[55, 80, 35, 65].map((h, i) => (
        <span key={i} style={{ height: `${h}%` }} />
      ))}
    </Box>
  </Box>
);

export const CommentsDemo: React.FC<{ role: CommentsRole; family: GuideFamily }> = ({
  role,
  family,
}) => {
  const guest = role === 'guest';
  const moderator = role === 'moderator';
  const [open, setOpen] = useState(true);
  const [resolved, setResolved] = useState(false);
  const [messages, setMessages] = useState(OPENING);
  const [draft, setDraft] = useState('');
  const [annotate, setAnnotate] = useState<AnnotateState | null>(null);
  const [drawn, setDrawn] = useState<RenderableAnnotation[]>([]);
  const source = pickedSource(family, useFamilyPick(family, annotatableFigureRank, { acrossTabs: true }));
  const metadata = source?.metadata ?? null;
  const index = metadata ? String(metadata.index) : '';
  const title = String(metadata?.title ?? '') || 'a figure';
  const host = useRef<HTMLDivElement>(null);
  const canDraw =
    Boolean(metadata) &&
    componentSupportsAnnotation('figure', (metadata ?? {}) as Record<string, unknown>);
  const range = useExampleRange(host, canDraw);

  const reply = () => {
    const body = draft.trim();
    if (!body) return;
    setMessages((m) => [...m, { author: 'You', body }]);
    setDraft('');
  };

  // The chrome's own comments icon, wired to this demo's thread.
  const control = useMemo<CommentsControl | null>(
    () =>
      metadata
        ? {
            openCounts: { [metadata.index]: resolved ? 0 : 1 },
            proposedCounts: {},
            staleCounts: {},
            openDrawer: () => setOpen((o) => !o),
            canComment: true,
            canModerate: moderator,
          }
        : null,
    [metadata, moderator, resolved],
  );

  // What the figure draws: the example range, published so viewers see it too,
  // then whatever an editor adds here.
  const items = useMemo<Record<string, RenderableAnnotation[]>>(() => {
    if (!index) return {};
    const example: RenderableAnnotation[] = range
      ? [
          {
            id: EXAMPLE_ID,
            number: 1,
            status: resolved ? 'resolved' : 'open',
            annotation: {
              kind: 'range',
              geometry: {
                kind: 'x_range',
                x0: range[0] + (range[1] - range[0]) * 0.4,
                x1: range[0] + (range[1] - range[0]) * 0.6,
              },
              label: 'Worth a look',
              color: 'blue',
              published: true,
            },
          },
        ]
      : [];
    return { [index]: [...example, ...drawn] };
  }, [index, range, resolved, drawn]);

  const onSave = useCallback(async (componentIndex: string, d: AnnotationDraft) => {
    setDrawn((prev) => [
      ...prev,
      {
        id: `guide-drawn-${prev.length + 1}`,
        number: prev.length + 2,
        status: 'open',
        annotation: d.annotation,
      },
    ]);
    setAnnotate(null);
    if (componentIndex) setOpen(true);
  }, []);
  const onSetAnnotate = useCallback((componentIndex: string | null, tool?: AnnotateTool | null) => {
    setAnnotate(componentIndex ? { componentIndex, tool: tool ?? 'range' } : null);
  }, []);

  return (
    <Group gap="md" align="flex-start" wrap="wrap" data-testid="guide-comments-demo">
      <Box style={{ flex: '1 1 380px', minWidth: 0, maxWidth: 560 }}>
        {source === undefined ? (
          <Skeleton h={260} radius="md" />
        ) : source && metadata && control ? (
          <Box
            className="depictio-guide-demo-tile"
            h={330}
            data-testid="guide-comments-figure"
            data-guide-comments-icon
          >
            <div className="depictio-guide-demo-cell" ref={host}>
              <GuideSandbox metadata={[metadata]}>
                <CommentsControlProvider value={control}>
                  <AnnotationLayerProvider
                    items={items}
                    canAnnotate={moderator}
                    annotate={annotate}
                    setAnnotate={onSetAnnotate}
                    onSave={onSave}
                    onAnnotationClick={() => setOpen(true)}
                  >
                    <ComponentRenderer
                      metadata={metadata}
                      dashboardId={source.dashboardId}
                      filters={NO_FILTERS}
                    />
                  </AnnotationLayerProvider>
                </CommentsControlProvider>
              </GuideSandbox>
            </div>
          </Box>
        ) : (
          <StandIn onClick={() => setOpen((o) => !o)} />
        )}
        <Text size="xs" c="dimmed" mt={6}>
          {source
            ? `The dashboard's own figure, from ${source.tabLabel}. The comment and the annotation on it are made up.`
            : 'A made-up figure: this dashboard has none to borrow.'}
          {source && moderator && canDraw ? ' Use Annotate to draw one of your own.' : ''}
        </Text>
      </Box>

      <Box style={{ flex: '2 1 260px', minWidth: 0 }}>
        {open ? (
          <Paper withBorder radius="md" p="sm" data-testid="guide-comments-thread">
            <Stack gap="xs">
              <Group justify="space-between" wrap="nowrap" gap="xs">
                <Text size="xs" c="dimmed" truncate>
                  {moderator && range ? 'Annotation on ' : 'Commenting on '}
                  {title}
                </Text>
                <Badge size="xs" variant="light" color={resolved ? 'teal' : 'blue'}>
                  {resolved ? 'Resolved' : 'Open'}
                </Badge>
              </Group>
              {messages.map((m, i) => (
                <Stack key={i} gap={2}>
                  <Author name={m.author} />
                  <Text size="sm" pl={26}>
                    {m.body}
                  </Text>
                </Stack>
              ))}
              <Group gap="xs" wrap="nowrap">
                <TextInput
                  size="xs"
                  placeholder="Reply…"
                  aria-label="Reply"
                  value={draft}
                  onChange={(e) => setDraft(e.currentTarget.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') reply();
                  }}
                  style={{ flex: 1 }}
                />
                <Button size="compact-sm" variant="light" onClick={reply} disabled={!draft.trim()}>
                  Reply
                </Button>
              </Group>
              {moderator && (
                <Button
                  size="compact-sm"
                  variant="subtle"
                  color={resolved ? 'gray' : 'teal'}
                  leftSection={
                    <Icon icon={resolved ? 'mdi:restore' : 'mdi:check-circle-outline'} width={14} />
                  }
                  onClick={() => setResolved((r) => !r)}
                  style={{ alignSelf: 'flex-start' }}
                >
                  {resolved ? 'Reopen' : 'Resolve'}
                </Button>
              )}
              {guest && (
                <Group gap={6} wrap="nowrap" align="flex-start" data-testid="guide-comments-signin">
                  <Icon icon="mdi:login" width={14} style={{ marginTop: 2, flexShrink: 0 }} />
                  <Text size="xs" c="dimmed">
                    This is an example, so it works without an account. On the dashboard itself,
                    sign in first.
                  </Text>
                </Group>
              )}
            </Stack>
          </Paper>
        ) : (
          <Text size="sm" c="dimmed">
            Click the comments icon to open the thread.
          </Text>
        )}
      </Box>
    </Group>
  );
};
