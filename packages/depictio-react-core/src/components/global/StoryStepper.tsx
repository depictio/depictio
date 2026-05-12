/**
 * Ordered tab stepper that appears at the top of the main grid when a story
 * is active. Shows "Step n of N: <tab title>" with Prev / Next CTAs that
 * navigate inside the story's ordered tab list — independent of the dashboard
 * default tab order, so the same tab can appear at different positions
 * across stories.
 */

import React from 'react';
import { Button, Group, Paper, Stepper, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import type { DashboardSummary, Story } from '../../api';

export interface StoryStepperProps {
  story: Story;
  /** All child tabs of the parent dashboard — used to resolve titles & icons
   *  for the steps. Tabs not in `story.tab_order` are filtered out. */
  childTabs: DashboardSummary[];
  /** The currently rendered tab's dashboard ID (so the stepper knows which
   *  step is active). */
  currentTabId: string;
  /** Navigate to a tab; called when Prev / Next or a Stepper.Step is clicked. */
  onNavigate: (tabDashboardId: string) => void;
  /** Exit the story → drops to Free Explore. */
  onExitStory: () => void;
}

const StoryStepper: React.FC<StoryStepperProps> = ({
  story,
  childTabs,
  currentTabId,
  onNavigate,
  onExitStory,
}) => {
  const tabById = new Map(childTabs.map((t) => [t.dashboard_id, t]));
  const orderedSteps = story.tab_order
    .map((id) => tabById.get(id))
    .filter((t): t is DashboardSummary => Boolean(t));

  if (orderedSteps.length === 0) return null;

  const activeIndex = orderedSteps.findIndex((t) => t.dashboard_id === currentTabId);
  const hasPrev = activeIndex > 0;
  const hasNext = activeIndex >= 0 && activeIndex < orderedSteps.length - 1;
  const currentStep = activeIndex >= 0 ? orderedSteps[activeIndex] : null;

  return (
    <Paper withBorder p="xs" radius="md" mb="sm">
      <Group justify="space-between" align="center" wrap="nowrap">
        <Group gap="xs" wrap="nowrap" style={{ minWidth: 0 }}>
          <Icon
            icon={story.icon ?? 'tabler:route'}
            width={18}
            color={story.color ?? 'var(--mantine-color-blue-filled)'}
          />
          <Text size="sm" fw={600} truncate>
            {story.name}
          </Text>
          {currentStep && activeIndex >= 0 && (
            <Text size="xs" c="dimmed" truncate>
              · Step {activeIndex + 1} of {orderedSteps.length}: {currentStep.title}
            </Text>
          )}
        </Group>
        <Group gap="xs" wrap="nowrap">
          <Button
            size="xs"
            variant="subtle"
            leftSection={<Icon icon="tabler:chevron-left" width={14} />}
            disabled={!hasPrev}
            onClick={() => hasPrev && onNavigate(orderedSteps[activeIndex - 1].dashboard_id)}
          >
            Prev
          </Button>
          <Button
            size="xs"
            variant="filled"
            rightSection={<Icon icon="tabler:chevron-right" width={14} />}
            disabled={!hasNext}
            onClick={() => hasNext && onNavigate(orderedSteps[activeIndex + 1].dashboard_id)}
          >
            Next
          </Button>
          <Button
            size="xs"
            variant="subtle"
            color="gray"
            onClick={onExitStory}
            leftSection={<Icon icon="tabler:x" width={14} />}
          >
            Exit story
          </Button>
        </Group>
      </Group>
      {orderedSteps.length > 1 && (
        <Stepper
          mt="xs"
          size="xs"
          active={activeIndex < 0 ? 0 : activeIndex}
          onStepClick={(idx) => onNavigate(orderedSteps[idx].dashboard_id)}
          allowNextStepsSelect
        >
          {orderedSteps.map((tab) => (
            <Stepper.Step
              key={tab.dashboard_id}
              label={tab.title}
              icon={tab.tab_icon ? <Icon icon={tab.tab_icon} width={14} /> : undefined}
            />
          ))}
        </Stepper>
      )}
    </Paper>
  );
};

export default StoryStepper;
