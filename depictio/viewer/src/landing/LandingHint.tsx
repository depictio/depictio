import React from 'react';
import { Button, Group, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import { CoachCard } from '../coach';
import DepictioRose from '../components/rose/DepictioRose';

/** Where the card points, in order: Depictio's own credit (the card is
 *  Depictio introducing itself, over the free top-right of the canvas), then
 *  the mark, then the Guide. None drawn (a phone, the Classic chrome) puts the
 *  card in the bottom-right corner instead. */
const ANCHORS = ['powered-by', 'home-mark', 'guide'] as const;
const SIDES = { 'powered-by': 'bottom-end', 'home-mark': 'bottom-start', guide: 'right' } as const;

export interface LandingNews {
  /** "3 changes since yesterday". */
  headline: string;
  /** "2 new runs · 1 dashboard edit". */
  detail: string;
}

interface LandingHintProps {
  /** What this dashboard is: its subtitle, else its title. */
  description: string | null;
  /** A public-mode guest (introduced to Depictio itself), or a signed-in
   *  reader (introduced to the dashboard). */
  audience: 'guest' | 'reader';
  /** Introduce the dashboard: the reader's first visit. */
  intro: boolean;
  /** Something changed since the reader's last visit. */
  news: LandingNews | null;
  onOpenGuide: () => void;
  onOpenNews: () => void;
  onDismiss: () => void;
}

/**
 * A reader's first look at a dashboard, and their return to one that changed:
 * one card saying what Depictio or this dashboard is, where to learn how it
 * works and what is new since last time. It dims nothing and blocks nothing;
 * the page stays usable beneath it.
 */
const LandingHint: React.FC<LandingHintProps> = ({
  description,
  audience,
  intro,
  news,
  onOpenGuide,
  onOpenNews,
  onDismiss,
}) => {
  const newsOnly = !intro && news !== null;
  const title = newsOnly
    ? news.headline
    : audience === 'guest'
      ? "Depictio turns a pipeline's results into interactive dashboards."
      : 'First time on this dashboard?';
  const eyebrow = newsOnly ? "What's new" : audience === 'guest' ? 'Welcome' : 'About this dashboard';

  return (
    <CoachCard
      target={ANCHORS}
      position={SIDES}
      mark={
        newsOnly ? (
          <Icon icon="mdi:update" width={20} height={20} />
        ) : (
          <DepictioRose mode="petals" size={26} label="" />
        )
      }
      eyebrow={eyebrow}
      title={title}
      onClose={onDismiss}
      closeLabel="Dismiss"
      width={360}
      testId="landing-hint"
      footer={
        <Group gap={6} wrap="nowrap" mt={2}>
          {newsOnly ? (
            <Button
              size="xs"
              onClick={onOpenNews}
              rightSection={<Icon icon="mdi:arrow-right" width={14} />}
              data-testid="landing-hint-news"
            >
              See what&apos;s new
            </Button>
          ) : (
            <Button
              size="xs"
              variant="light"
              onClick={onOpenGuide}
              rightSection={<Icon icon="mdi:arrow-right" width={14} />}
              data-testid="landing-hint-guide"
            >
              See how this dashboard works
            </Button>
          )}
          <Button size="xs" variant="subtle" color="gray" onClick={onDismiss} data-testid="landing-hint-dismiss">
            Got it
          </Button>
        </Group>
      }
    >
      <Stack gap="xs">
        {newsOnly ? (
          <Text inherit c="dimmed">
            {news.detail}
          </Text>
        ) : (
          description && (
            <Text inherit c="dimmed">
              {description}
            </Text>
          )
        )}
        {!newsOnly && news && (
          <button
            type="button"
            className="depictio-coach-journey"
            onClick={onOpenNews}
            data-testid="landing-hint-news"
          >
            <span className="depictio-coach-mark" aria-hidden>
              <Icon icon="mdi:update" width={18} height={18} />
            </span>
            <span style={{ minWidth: 0 }}>
              <Text fw={600} size="sm" lh={1.3}>
                {news.headline}
              </Text>
              <Text size="xs" c="dimmed" lh={1.4}>
                {news.detail}
              </Text>
            </span>
          </button>
        )}
      </Stack>
    </CoachCard>
  );
};

export default LandingHint;
