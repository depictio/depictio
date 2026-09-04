import React, { useState } from 'react';
import {
  Alert,
  Button,
  Collapse,
  Group,
  List,
  Modal,
  Progress,
  Stack,
  Text,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { AI_COLOR, AI_ICON } from '../icons';
import type { AIGenerationInfo } from '../types';
import type { DraftTile } from './DraftReviewPanel';

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
  /** The draft's generated tiles. The banner only counts them; the decisions
   *  themselves live in `DraftReviewPanel`, which the host opens from here. */
  tiles?: DraftTile[];
  /** Open the review panel. Absent on a host that has none, which takes the
   *  review button off the banner. */
  onOpenReview?: () => void;
  /** The panel is already up, so its button has nothing left to do. */
  reviewOpen?: boolean;
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
 * Editor-only notice on a dashboard the AI generated whole and nobody has
 * reviewed yet. Two exits: Promote keeps it as a regular dashboard, Discard
 * deletes it (behind a confirm). Everything else about the dashboard is
 * already editable underneath.
 *
 * The banner is the provenance and the progress, not the review: it says what
 * made the dashboard, how far the review has got and what the two exits are,
 * and hands off to `DraftReviewPanel` for the per-tile decisions. It sits at
 * the top of a canvas the reviewer scrolls, which is exactly why the
 * decisions cannot live here.
 */
const AIDraftBanner: React.FC<Props> = ({
  info,
  total = 0,
  reviewed = 0,
  tiles,
  onOpenReview,
  reviewOpen = false,
  onPromote,
  onDiscard,
}) => {
  const [promoting, setPromoting] = useState(false);
  const [discarding, setDiscarding] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [promoteConfirmOpen, setPromoteConfirmOpen] = useState(false);
  const [warningsOpen, setWarningsOpen] = useState(false);
  const [rationaleOpen, setRationaleOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const busy = promoting || discarding;
  const when = formatGeneratedAt(info.generated_at);
  const warnings = info.warnings ?? [];
  // A section the planner gave no reason for explains nothing, so it is left
  // out rather than shown as a bare name.
  const sections = (info.sections ?? []).filter((s) => (s.rationale ?? '').trim());
  // The tile list carries the counts too, so a host that passes it does not
  // also have to keep two numbers in step. Without it the numbers are all
  // there is, exactly as before the review existed.
  const tileList = tiles ?? [];
  const tracksReview = tiles !== undefined;
  const tileTotal = tracksReview ? tileList.length : total;
  const tileReviewed = tracksReview ? tileList.filter((t) => t.reviewed).length : reviewed;
  // Removing a tile is a decision too, so a draft whose leftovers were all
  // deleted counts as fully reviewed: the total only ever counts the tiles
  // still there.
  const pendingReview = Math.max(0, tileTotal - tileReviewed);
  const allReviewed = tileTotal === 0 || pendingReview === 0;
  const reviewedPct = tileTotal > 0 ? Math.min(100, (tileReviewed / tileTotal) * 100) : 0;

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

  return (
    <>
      <Alert
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
            <Stack gap={4} align="flex-start">
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
                w="100%"
                aria-label={`Reviewed ${tileReviewed} of ${tileTotal} components`}
              />
              {onOpenReview && (
                <Button
                  size="xs"
                  variant="light"
                  color={AI_COLOR}
                  leftSection={<Icon icon="mdi:clipboard-check-outline" width={14} />}
                  // Not hidden while the panel is up: the button is the one
                  // place that names how many components there are to go
                  // through, and a control that vanishes is a control nobody
                  // finds again.
                  disabled={reviewOpen}
                  onClick={onOpenReview}
                  data-testid="draft-review-open"
                >
                  Review {tileTotal} component{tileTotal === 1 ? '' : 's'}
                </Button>
              )}
            </Stack>
          )}
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
            editable afterwards, but the draft banner and its review panel go away.
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
