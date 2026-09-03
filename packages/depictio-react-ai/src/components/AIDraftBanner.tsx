import React, { useState } from 'react';
import {
  ActionIcon,
  Alert,
  Badge,
  Box,
  Button,
  Collapse,
  Group,
  List,
  Loader,
  Modal,
  Paper,
  Popover,
  Portal,
  Progress,
  Stack,
  Text,
  Textarea,
  Tooltip,
} from '@mantine/core';
import { useIntersection } from '@mantine/hooks';
import { Icon } from '@iconify/react';

import { AI_COLOR, AI_ICON, aiColorVar } from '../icons';
import type { AIGenerationInfo } from '../types';

/** One generated tile of the draft, as the review bar addresses it. */
export interface DraftTile {
  /** Generation handle: what the review and regenerate routes address the
   *  tile by. The canvas addresses it by `componentId` instead. */
  tag: string;
  componentId: string;
  /** What to call the tile in the bar. The host falls back to the tag on a
   *  component that carries no title of its own. */
  title: string;
  componentType: string;
  /** Section the tile sits in, filter-panel folds included: their rationale
   *  is worth showing even though a fold cannot be regenerated as a section
   *  (see `sectionRegenerable`). */
  section: string | null;
  /** The planner's brief for this tile, stamped on it at generation time.
   *  Null on a draft made before the planner was asked to explain itself. */
  intent: string | null;
  reviewed: boolean;
}

interface Props {
  info: AIGenerationInfo;
  /** Generated tiles still on the dashboard. Zero means the host tracks no
   *  per-tile review (an older draft whose tiles carry no generation tag),
   *  and the banner then behaves exactly as it did before the review flow:
   *  no counter, Promote enabled outright. Ignored when `tiles` is passed,
   *  which carries the same count and more. */
  total?: number;
  /** How many of those the owner has been through. */
  reviewed?: number;
  /** The draft's generated tiles in reading order (filter panel first, then
   *  each grid section), as the host reads them off the dashboard. Passing
   *  them is what turns the review bar on. */
  tiles?: DraftTile[];
  /** Index of the tile under review, owned by the host so the canvas and the
   *  bar cannot disagree about which one it is. */
  currentIndex?: number;
  onSelect?: (index: number) => void;
  onKeep?: (tile: DraftTile) => void | Promise<void>;
  onRemove?: (tile: DraftTile) => void | Promise<void>;
  onRegenerate?: (tile: DraftTile, instruction: string) => void | Promise<void>;
  onRegenerateSection?: (tile: DraftTile, instruction: string) => void | Promise<void>;
  /** A regeneration is in flight; the bar's actions go inert. */
  reviewBusy?: boolean;
  /** Last regeneration failure, shown in the bar. */
  reviewError?: string | null;
  /** Flip the draft into a regular dashboard. A rejection is shown inline;
   *  on success the host updates its own dashboard state, which unmounts
   *  this banner. */
  onPromote: () => Promise<void>;
  /** Delete the draft. Runs only after the confirm dialog; on success the
   *  host navigates away. */
  onDiscard: () => Promise<void>;
}

/** API timestamps arrive as naive UTC (no offset). `Date` would read such a
 *  string as local time, so pin it to UTC before formatting. Exported for
 *  `GenerationHistory`, which reads the same timestamps off the run records. */
export function formatGeneratedAt(raw: string): string {
  if (!raw) return '';
  const pinned = /(Z|[+-]\d{2}:?\d{2})$/.test(raw) ? raw : `${raw}Z`;
  const d = new Date(pinned);
  return Number.isNaN(d.getTime()) ? raw : d.toLocaleString();
}

/**
 * Stacking level of the floating review dock.
 *
 * Above `--mantine-z-index-app` (100), which is where the editor chrome and
 * the grid sit, so the dock is never painted under a tile. Below
 * `--mantine-z-index-modal` (200) and `--mantine-z-index-popover` (300), so
 * the promote and discard confirms cover it and its own regenerate popover
 * opens on top of it.
 */
const DOCK_Z_INDEX = 150;

/** Everything the review bar renders from, lifted into the banner so the two
 *  mounts (inline and docked) share one set of state and handlers. A second
 *  copy of the keep/regenerate/remove wiring is exactly what would drift. */
interface ReviewBarProps {
  /** Docked form: no chrome of its own, verdicts as icon buttons, one line. */
  compact?: boolean;
  tiles: DraftTile[];
  index: number;
  current?: DraftTile;
  allReviewed: boolean;
  tileTotal: number;
  /** The planner's brief for the current tile, already trimmed. */
  brief: string;
  sectionRationale: string;
  sectionRegenerable: boolean;
  reviewBusy: boolean;
  reviewError?: string | null;
  regenerateOpen: boolean;
  instruction: string;
  onSelect?: (index: number) => void;
  onInstructionChange: (value: string) => void;
  onRegenerateOpenChange: (opened: boolean) => void;
  onKeep: () => void;
  onRemove: () => void;
  onRegenerate: () => void;
  onRegenerateSection: () => void;
}

/**
 * The review itself: one tile at a time, in the plan's own order. A cursor
 * rather than a list, because the decision is about the tile on the canvas
 * and only one tile can be outlined there.
 *
 * Rendered twice from the same props, never at the same time: inline in the
 * banner while the banner is on screen, and inside the floating dock once it
 * is not. Reviewing scrolls the tile under judgement into view, and on a real
 * dashboard that takes the banner off the top of the canvas along with every
 * control on it.
 */
const ReviewBar: React.FC<ReviewBarProps> = ({
  compact = false,
  tiles,
  index,
  current,
  allReviewed,
  tileTotal,
  brief,
  sectionRationale,
  sectionRegenerable,
  reviewBusy,
  reviewError,
  regenerateOpen,
  instruction,
  onSelect,
  onInstructionChange,
  onRegenerateOpenChange,
  onKeep,
  onRemove,
  onRegenerate,
  onRegenerateSection,
}) => {
  // In the dock the surrounding Paper already carries the border and the
  // padding, so the bar's own frame would only double it up.
  const frame = { withBorder: !compact, p: compact ? 0 : ('xs' as const) };

  if (!current || allReviewed) {
    return (
      <Paper {...frame} radius="sm" data-testid="draft-review-bar">
        <Group gap={6} wrap="nowrap">
          <Box component="span" c="dimmed" style={{ display: 'inline-flex' }}>
            <Icon icon="mdi:check-circle" width={14} height={14} />
          </Box>
          <Text size="xs" c="dimmed">
            {tileTotal === 0
              ? 'No generated components left to review.'
              : `All ${tileTotal} generated component${tileTotal === 1 ? '' : 's'} reviewed.`}
          </Text>
        </Group>
      </Paper>
    );
  }

  const keepLabel = current.reviewed ? 'Reviewed - undo' : 'Keep';
  // The dock sits at the bottom of the viewport, so its dropdown has to open
  // upwards or it would be off screen the moment it is asked for.
  const regenerateForm = (
    <Popover
      opened={regenerateOpen}
      onChange={onRegenerateOpenChange}
      position={compact ? 'top-start' : 'bottom-start'}
      width={320}
      shadow="md"
      trapFocus
    >
      <Popover.Target>
        {compact ? (
          <Tooltip label="Regenerate" withArrow>
            <ActionIcon
              size="sm"
              variant="light"
              color={AI_COLOR}
              aria-label="Regenerate"
              disabled={reviewBusy}
              onClick={() => onRegenerateOpenChange(!regenerateOpen)}
              data-testid="draft-review-regenerate"
            >
              <Icon icon="mdi:refresh" width={14} height={14} />
            </ActionIcon>
          </Tooltip>
        ) : (
          <Button
            size="compact-xs"
            variant="light"
            color={AI_COLOR}
            leftSection={<Icon icon="mdi:refresh" width={14} />}
            disabled={reviewBusy}
            onClick={() => onRegenerateOpenChange(!regenerateOpen)}
            data-testid="draft-review-regenerate"
          >
            Regenerate
          </Button>
        )}
      </Popover.Target>
      <Popover.Dropdown>
        <Stack gap="xs">
          <Textarea
            label="Anything to change?"
            description="Optional. Left empty, the component is filled again from the plan's own intent."
            placeholder="e.g. use a box plot, group by cohort"
            autosize
            minRows={2}
            maxRows={5}
            value={instruction}
            onChange={(e) => onInstructionChange(e.currentTarget.value)}
            data-testid="draft-review-instruction"
          />
          <Group gap="xs" wrap="nowrap">
            <Button
              size="compact-sm"
              color={AI_COLOR}
              leftSection={<Icon icon="mdi:refresh" width={14} />}
              disabled={reviewBusy}
              onClick={onRegenerate}
              data-testid="draft-review-regenerate-run"
            >
              Regenerate
            </Button>
            {sectionRegenerable && (
              <Button
                size="compact-xs"
                variant="subtle"
                color={AI_COLOR}
                disabled={reviewBusy}
                onClick={onRegenerateSection}
                data-testid="draft-review-regenerate-section"
              >
                Whole section
              </Button>
            )}
          </Group>
        </Stack>
      </Popover.Dropdown>
    </Popover>
  );

  const verdicts = compact ? (
    // Never the part that gives way when the dock hits its max width: the
    // three verdicts are the whole reason it is on screen.
    <Group gap={4} wrap="nowrap" style={{ flexShrink: 0 }}>
      <Tooltip label={keepLabel} withArrow>
        <ActionIcon
          size="sm"
          variant="light"
          color="teal"
          aria-label={keepLabel}
          disabled={reviewBusy}
          onClick={onKeep}
          data-testid="draft-review-keep"
        >
          <Icon icon="mdi:check" width={14} height={14} />
        </ActionIcon>
      </Tooltip>
      {regenerateForm}
      <Tooltip label="Remove" withArrow>
        <ActionIcon
          size="sm"
          variant="subtle"
          color="red"
          aria-label="Remove"
          disabled={reviewBusy}
          onClick={onRemove}
          data-testid="draft-review-remove"
        >
          <Icon icon="mdi:delete-outline" width={14} height={14} />
        </ActionIcon>
      </Tooltip>
    </Group>
  ) : (
    <Group gap="xs" wrap="nowrap">
      <Button
        size="compact-xs"
        variant="light"
        color="teal"
        leftSection={<Icon icon="mdi:check" width={14} />}
        disabled={reviewBusy}
        onClick={onKeep}
        data-testid="draft-review-keep"
      >
        {keepLabel}
      </Button>
      {regenerateForm}
      <Button
        size="compact-xs"
        variant="subtle"
        color="red"
        leftSection={<Icon icon="mdi:delete-outline" width={14} />}
        disabled={reviewBusy}
        onClick={onRemove}
        data-testid="draft-review-remove"
      >
        Remove
      </Button>
    </Group>
  );

  // The dock has no room for the quoted brief, so it travels on the tile name
  // instead: the reviewer still gets the planner's reason on hover.
  const nameTitle = compact && brief ? `${current.title}: “${brief}”` : current.title;

  return (
    <Paper {...frame} radius="sm" data-testid="draft-review-bar">
      <Stack gap={6}>
        <Group gap={6} wrap="nowrap">
          {!compact && (
            <Text size="xs" fw={600}>
              Review
            </Text>
          )}
          <ActionIcon
            size="sm"
            variant="subtle"
            color="gray"
            aria-label="Previous component"
            disabled={reviewBusy || index === 0}
            onClick={() => onSelect?.(index - 1)}
            data-testid="draft-review-prev"
          >
            <Icon icon="mdi:chevron-left" width={16} height={16} />
          </ActionIcon>
          <Text
            size="xs"
            c="dimmed"
            style={{ whiteSpace: 'nowrap' }}
            data-testid="draft-review-position"
          >
            {index + 1} / {tiles.length}
          </Text>
          <ActionIcon
            size="sm"
            variant="subtle"
            color="gray"
            aria-label="Next component"
            disabled={reviewBusy || index >= tiles.length - 1}
            onClick={() => onSelect?.(index + 1)}
            data-testid="draft-review-next"
          >
            <Icon icon="mdi:chevron-right" width={16} height={16} />
          </ActionIcon>
          <Text
            size="sm"
            fw={600}
            truncate
            // `truncate` alone never fires in a nowrap flex row: the name has
            // to be allowed to shrink below its own content width first, and
            // in the dock it is the one thing that may give up space.
            style={compact ? { flex: '1 1 auto', minWidth: 0 } : undefined}
            title={nameTitle}
            data-testid="draft-review-current"
            data-tag={current.tag}
            data-reviewed={current.reviewed ? 'true' : 'false'}
          >
            {current.title}
          </Text>
          {current.reviewed && (
            // Settled, not finished with: Keep is still the way back out, so
            // the mark is subdued rather than celebratory.
            <Box
              component="span"
              c="dimmed"
              title="Already reviewed"
              style={{ display: 'inline-flex' }}
            >
              <Icon icon="mdi:check-circle" width={14} height={14} />
            </Box>
          )}
          {!compact && (
            <Badge size="xs" variant="light" color="gray">
              {current.componentType}
            </Badge>
          )}
          {reviewBusy && <Loader size="xs" color={AI_COLOR} />}
          {/* One line in the dock: the verdicts follow the name rather than
              opening a second row the floating bar has no height for. */}
          {compact && verdicts}
        </Group>

        {/* The planner's own words, quoted rather than alerted: this is
            context for the decision, not something that went wrong. */}
        {!compact && (brief || sectionRationale) && (
          <Box pl="xs" style={{ borderLeft: `2px solid ${aiColorVar(3)}` }}>
            {brief && (
              <Text size="xs" c="dimmed">
                {`“${brief}”`}
              </Text>
            )}
            {sectionRationale && (
              <Text size="xs" c="dimmed" mt={brief ? 2 : 0}>
                {`${current.section}: “${sectionRationale}”`}
              </Text>
            )}
          </Box>
        )}

        {!compact && verdicts}
        {reviewError && (
          <Text size="xs" c="red">
            {reviewError}
          </Text>
        )}
      </Stack>
    </Paper>
  );
};

/**
 * Editor-only notice on a dashboard the AI generated whole and nobody has
 * reviewed yet. Two exits: Promote keeps it as a regular dashboard, Discard
 * deletes it (behind a confirm). Everything else about the dashboard is
 * already editable underneath.
 *
 * The per-tile review lives here too, as a cursor over the generated tiles
 * rather than as controls on the tiles themselves. A draft of a dozen tiles
 * that grows a toolbar per tile is a dashboard nobody can read while judging
 * it; one bar walks the same twelve decisions from a single place, and the
 * canvas answers "which one" by outlining the tile under review.
 *
 * That outlining is also why the bar has a second home: selecting a tile
 * scrolls it into view, and a tile halfway down a real dashboard takes the
 * banner off the top of the canvas with it. Once the banner is out of sight a
 * compact copy of the bar docks to the bottom of the viewport, so the tile
 * under judgement and the verdict buttons are never on separate screens.
 */
const AIDraftBanner: React.FC<Props> = ({
  info,
  total = 0,
  reviewed = 0,
  tiles,
  currentIndex = 0,
  onSelect,
  onKeep,
  onRemove,
  onRegenerate,
  onRegenerateSection,
  reviewBusy = false,
  reviewError,
  onPromote,
  onDiscard,
}) => {
  const [promoting, setPromoting] = useState(false);
  const [discarding, setDiscarding] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [promoteConfirmOpen, setPromoteConfirmOpen] = useState(false);
  const [warningsOpen, setWarningsOpen] = useState(false);
  const [rationaleOpen, setRationaleOpen] = useState(false);
  const [regenerateOpen, setRegenerateOpen] = useState(false);
  const [instruction, setInstruction] = useState('');
  const [error, setError] = useState<string | null>(null);
  // Is the banner still on screen? The editor scrolls the canvas, not the
  // window, but an element clipped by a scrolling ancestor stops intersecting
  // the viewport all the same, so the implicit root is the right one here.
  // The hook disconnects its observer when React hands the ref back as null.
  const { ref: bannerRef, entry: bannerEntry } = useIntersection<HTMLDivElement>({ threshold: 0 });
  // No entry yet means the observer has not reported once. Assume the banner
  // is there, so the dock never flashes over a banner sitting in plain sight.
  const bannerVisible = bannerEntry ? bannerEntry.isIntersecting : true;
  const busy = promoting || discarding;
  const when = formatGeneratedAt(info.generated_at);
  const warnings = info.warnings ?? [];
  // A section the planner gave no reason for explains nothing, so it is left
  // out rather than shown as a bare name.
  const sections = (info.sections ?? []).filter((s) => (s.rationale ?? '').trim());
  // The tile list carries the counts too, so a host that passes it does not
  // also have to keep two numbers in step. Without it the numbers are all
  // there is, exactly as before the bar existed.
  const tileList = tiles ?? [];
  const reviewBar = tiles !== undefined;
  const tileTotal = reviewBar ? tileList.length : total;
  const tileReviewed = reviewBar ? tileList.filter((t) => t.reviewed).length : reviewed;
  // Removing a tile is a decision too, so a draft whose leftovers were all
  // deleted counts as fully reviewed: the total only ever counts the tiles
  // still there.
  const pendingReview = Math.max(0, tileTotal - tileReviewed);
  const allReviewed = tileTotal === 0 || pendingReview === 0;
  const reviewedPct = tileTotal > 0 ? Math.min(100, (tileReviewed / tileTotal) * 100) : 0;

  // The host owns the cursor, but a list that just lost a tile can reach the
  // bar one render before the clamp does, so read it defensively.
  const index = Math.min(Math.max(currentIndex, 0), Math.max(0, tileList.length - 1));
  const current: DraftTile | undefined = tileList[index];
  const brief = (current?.intent ?? '').trim();
  const sectionRationale = current?.section
    ? (sections.find((s) => s.name === current.section)?.rationale ?? '').trim()
    : '';
  // Grid sections only: the section regenerate re-runs the layout pass for a
  // row of boxes, and a filter-panel control's section is a fold of the left
  // panel. Its rationale still shows above, it just has no section to refill.
  const sectionRegenerable =
    Boolean(current?.section) &&
    current?.componentType !== 'interactive' &&
    Boolean(onRegenerateSection);

  /** Next tile still to review, wrapping past the end so a reviewer who
   *  started in the middle still lands on whatever is left behind them.
   *  Stays put once nothing is left. */
  const advanceFrom = (from: number) => {
    for (let step = 1; step < tileList.length; step += 1) {
      const next = (from + step) % tileList.length;
      if (!tileList[next].reviewed) {
        onSelect?.(next);
        return;
      }
    }
  };

  const keepCurrent = () => {
    if (!current) return;
    const wasReviewed = current.reviewed;
    void onKeep?.(current);
    // Keeping a tile is the click that finishes it, so the bar moves on by
    // itself: twelve tiles are twelve clicks, not twenty four. Undoing a Keep
    // reopens the tile instead, so that one stays put.
    if (!wasReviewed) advanceFrom(index);
  };

  const removeCurrent = () => {
    if (!current) return;
    // No `onSelect`: the removed tile leaves the list, so this same slot now
    // holds the one after it. The host clamps when the last tile goes.
    void onRemove?.(current);
  };

  const regenerateCurrent = () => {
    if (!current) return;
    setRegenerateOpen(false);
    // The cursor does not move: the result of the regeneration is the thing
    // the reviewer was about to judge.
    void onRegenerate?.(current, instruction.trim());
  };

  const regenerateCurrentSection = () => {
    if (!current || !onRegenerateSection) return;
    setRegenerateOpen(false);
    void onRegenerateSection(current, instruction.trim());
  };

  const promote = async () => {
    setPromoting(true);
    setError(null);
    try {
      await onPromote();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPromoting(false);
      setPromoteConfirmOpen(false);
    }
  };

  /** Promoting with tiles left unreviewed is allowed but never accidental:
   *  it is the click that turns the draft into an ordinary dashboard. */
  const requestPromote = () => {
    if (allReviewed) {
      void promote();
      return;
    }
    setPromoteConfirmOpen(true);
  };

  const discard = async () => {
    setDiscarding(true);
    setError(null);
    try {
      await onDiscard();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setDiscarding(false);
      setConfirmOpen(false);
    }
  };

  /** One set of state and handlers, rendered by whichever of the two mounts
   *  is up. `compact` is the only thing that differs between them. */
  const reviewBarProps: ReviewBarProps = {
    tiles: tileList,
    index,
    current,
    allReviewed,
    tileTotal,
    brief,
    sectionRationale,
    sectionRegenerable,
    reviewBusy,
    reviewError,
    regenerateOpen,
    instruction,
    onSelect,
    onInstructionChange: setInstruction,
    onRegenerateOpenChange: setRegenerateOpen,
    onKeep: keepCurrent,
    onRemove: removeCurrent,
    onRegenerate: regenerateCurrent,
    onRegenerateSection: regenerateCurrentSection,
  };

  // The dock earns its place only while there is a verdict left to give, and
  // it steps aside for this component's own confirms rather than sitting
  // under them.
  const dockUsable =
    reviewBar && Boolean(current) && !allReviewed && !confirmOpen && !promoteConfirmOpen;
  // Exactly one of the two mounts exists at any time, which is what keeps
  // every `draft-review-*` test id unique in the DOM.
  const showDock = dockUsable && !bannerVisible;
  const showInlineBar = reviewBar && !showDock;

  return (
    <>
      <Alert
        ref={bannerRef}
        variant="light"
        color={AI_COLOR}
        icon={<Icon icon={AI_ICON} width={18} />}
        title="AI-generated draft"
        mb="sm"
        data-testid="ai-draft-banner"
      >
        <Stack gap="xs">
          <Text size="sm">
            Generated by{' '}
            <Text span fw={600}>
              {info.model}
            </Text>
            {when ? ` on ${when}` : ''}. Review the components, then promote the dashboard to
            keep it or discard it.
          </Text>
          {info.prompt && (
            <Text size="xs" c="dimmed" lineClamp={2} title={info.prompt}>
              Prompt: {info.prompt}
            </Text>
          )}
          {tileTotal > 0 && (
            <Stack gap={4}>
              <Group gap="xs">
                <Text size="xs" c="dimmed" data-testid="ai-draft-review-count">
                  Reviewed {tileReviewed} of {tileTotal}
                </Text>
                {!allReviewed && (
                  <Text size="xs" c="dimmed">
                    · {pendingReview} left to keep, regenerate or remove
                  </Text>
                )}
              </Group>
              <Progress
                value={reviewedPct}
                size="xs"
                color={AI_COLOR}
                aria-label={`Reviewed ${tileReviewed} of ${tileTotal} components`}
              />
            </Stack>
          )}
          {/* The bar lives in the banner while the banner is on screen. Once
              it is not, the dock below renders the very same bar instead, and
              never at the same time: that is what keeps each `draft-review-*`
              id unique in the DOM. */}
          {showInlineBar && <ReviewBar {...reviewBarProps} />}
          {/* Above the warnings on purpose: this one explains the dashboard
              the reviewer is looking at, the warnings only explain the run. */}
          {sections.length > 0 && (
            <Stack gap={2} align="flex-start">
              <Button
                size="compact-xs"
                variant="subtle"
                color="gray"
                rightSection={
                  <Icon icon={rationaleOpen ? 'mdi:chevron-up' : 'mdi:chevron-down'} width={14} />
                }
                onClick={() => setRationaleOpen((o) => !o)}
                data-testid="ai-draft-rationale-toggle"
              >
                Why this layout
              </Button>
              <Collapse in={rationaleOpen} data-testid="ai-draft-rationale">
                <Stack gap={6}>
                  {sections.map((s, i) => (
                    <Group key={`${s.name}-${i}`} gap={6} wrap="nowrap" align="flex-start">
                      <Icon
                        icon={s.kind === 'filter' ? 'mdi:filter-variant' : 'mdi:view-grid-outline'}
                        width={14}
                        height={14}
                        style={{ flexShrink: 0, marginTop: 2 }}
                      />
                      <Stack gap={0}>
                        <Text fw={600} size="xs">
                          {s.name}
                        </Text>
                        <Text size="xs" c="dimmed">
                          {s.rationale}
                        </Text>
                      </Stack>
                    </Group>
                  ))}
                </Stack>
              </Collapse>
            </Stack>
          )}
          {warnings.length > 0 && (
            <Stack gap={2} align="flex-start">
              <Button
                size="compact-xs"
                variant="subtle"
                color="gray"
                rightSection={
                  <Icon icon={warningsOpen ? 'mdi:chevron-up' : 'mdi:chevron-down'} width={14} />
                }
                onClick={() => setWarningsOpen((o) => !o)}
                data-testid="ai-draft-warnings-toggle"
              >
                {warnings.length} warning{warnings.length === 1 ? '' : 's'}
              </Button>
              <Collapse in={warningsOpen}>
                <List size="xs" spacing={2}>
                  {warnings.map((w, i) => (
                    <List.Item key={i}>{w}</List.Item>
                  ))}
                </List>
              </Collapse>
            </Stack>
          )}
          {error && (
            <Text size="xs" c="red">
              {error}
            </Text>
          )}
          <Group gap="xs">
            <Button
              size="xs"
              color={AI_COLOR}
              leftSection={<Icon icon="mdi:check" width={14} />}
              loading={promoting}
              disabled={busy}
              onClick={requestPromote}
              data-testid="ai-draft-promote"
            >
              Promote
            </Button>
            <Button
              size="xs"
              variant="subtle"
              color="red"
              leftSection={<Icon icon="mdi:delete-outline" width={14} />}
              disabled={busy}
              onClick={() => setConfirmOpen(true)}
              data-testid="ai-draft-discard"
            >
              Discard
            </Button>
          </Group>
        </Stack>
      </Alert>

      {/* Through a Portal because the banner renders inside the editor's
          scrolling canvas: an ancestor's `overflow` or `transform` would
          otherwise clip a fixed child or re-anchor it to the wrong box. */}
      {showDock && (
        <Portal>
          <Paper
            withBorder
            shadow="md"
            radius="md"
            p="xs"
            data-testid="draft-review-dock"
            style={{
              position: 'fixed',
              bottom: 'var(--mantine-spacing-lg)',
              // `left`/`right` plus auto margins centre a fixed box without a
              // transform, which a Popover anchored inside it would inherit.
              left: 0,
              right: 0,
              marginInline: 'auto',
              width: 'fit-content',
              maxWidth: 'min(640px, calc(100vw - 2 * var(--mantine-spacing-xl)))',
              // Opaque on purpose: this floats over dashboard tiles, and a
              // translucent surface would leave the labels unreadable.
              backgroundColor: 'var(--mantine-color-body)',
              zIndex: DOCK_Z_INDEX,
            }}
          >
            <ReviewBar {...reviewBarProps} compact />
          </Paper>
        </Portal>
      )}

      <Modal
        opened={promoteConfirmOpen}
        onClose={() => {
          if (!promoting) setPromoteConfirmOpen(false);
        }}
        title="Promote without finishing the review?"
        centered
      >
        <Stack gap="md">
          <Text size="sm">
            {pendingReview} of {tileTotal} generated component
            {tileTotal === 1 ? '' : 's'} {pendingReview === 1 ? 'has' : 'have'} not been
            reviewed. Promoting keeps the dashboard as it is; the components stay
            editable afterwards, but the draft banner and its review bar go away.
          </Text>
          <Group justify="flex-end" gap="xs">
            <Button
              variant="default"
              onClick={() => setPromoteConfirmOpen(false)}
              disabled={promoting}
            >
              Keep reviewing
            </Button>
            <Button
              color={AI_COLOR}
              loading={promoting}
              onClick={() => void promote()}
              data-testid="ai-draft-promote-confirm"
            >
              Promote anyway
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal
        opened={confirmOpen}
        onClose={() => {
          if (!discarding) setConfirmOpen(false);
        }}
        title="Discard this draft?"
        centered
      >
        <Stack gap="md">
          <Text size="sm">
            The dashboard and every component in it are deleted. This cannot be undone.
          </Text>
          <Group justify="flex-end" gap="xs">
            <Button variant="default" onClick={() => setConfirmOpen(false)} disabled={discarding}>
              Keep draft
            </Button>
            <Button
              color="red"
              loading={discarding}
              onClick={() => void discard()}
              data-testid="ai-draft-discard-confirm"
            >
              Discard
            </Button>
          </Group>
        </Stack>
      </Modal>
    </>
  );
};

export default AIDraftBanner;
