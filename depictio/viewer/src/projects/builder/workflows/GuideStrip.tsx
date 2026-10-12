/**
 * The four moves of the Data collections step, as a strip the reader can
 * follow and click: describe the workflows, pick files, define the collection,
 * review. The step in progress is lit, the ones behind are checked and the
 * ones ahead are dimmed. A step that cannot be reached yet says why on hover.
 */
import React from 'react';
import { SimpleGrid, Text, ThemeIcon, Tooltip, UnstyledButton } from '@mantine/core';
import { Icon } from '@iconify/react';

import { useBrandAccents } from 'depictio-react-core';

export type GuideStage = 'workflow' | 'pick' | 'define' | 'review';

const STEPS: { stage: GuideStage; icon: string; title: string; hint: string }[] = [
  {
    stage: 'workflow',
    icon: 'mdi:sitemap-outline',
    title: 'Describe the workflows',
    hint: 'What produced these files, and how their folders are laid out.',
  },
  {
    stage: 'pick',
    icon: 'mdi:cursor-default-click-outline',
    title: 'Pick files',
    hint: 'Click a file in the tree, tick its siblings to cover every sample.',
  },
  {
    stage: 'define',
    icon: 'mdi:table-edit',
    title: 'Define the collection',
    hint: 'Name it, check its type and what it matches, then save it.',
  },
  {
    stage: 'review',
    icon: 'mdi:clipboard-check-outline',
    title: 'Review & create',
    hint: 'Add more collections, or check the plan and create the project.',
  },
];

const ORDER: GuideStage[] = ['workflow', 'pick', 'define', 'review'];

/** Where the reader is: a file or collection open is defining; otherwise the
 *  step they last chose, else the first one with nothing done yet. */
export function guideStage(options: {
  hasFile: boolean;
  editing: boolean;
  collections: number;
  /** The step the reader chose by clicking the strip. */
  chosen: GuideStage | null;
  workflowDescribed: boolean;
}): GuideStage {
  if (options.editing || options.hasFile) return 'define';
  if (options.chosen) return options.chosen;
  if (options.collections > 0) return 'review';
  return options.workflowDescribed ? 'pick' : 'workflow';
}

export const GuideStrip: React.FC<{
  stage: GuideStage;
  /** The workflow has been given something beyond the builder's defaults. */
  workflowDescribed: boolean;
  onSelect: (stage: GuideStage) => void;
  /** Why a step cannot be opened now; absent when it can. */
  disabled?: Partial<Record<GuideStage, string>>;
  /** One line per step, with no hint: for the collection form, where room is short. */
  compact?: boolean;
}> = ({ stage, workflowDescribed, onSelect, disabled = {}, compact = false }) => {
  const accent = useBrandAccents();
  const at = ORDER.indexOf(stage);
  return (
    <SimpleGrid
      cols={{ base: 1, xs: 2, md: 4 }}
      spacing="xs"
      role="tablist"
      aria-label="Steps of the data collections"
      data-testid="builder-guide"
      data-stage={stage}
    >
      {STEPS.map((step, index) => {
        // The workflow step is done once something was entered, or once the
        // reader moved on knowing it: the defaults are a start, not an answer.
        const done = step.stage === 'workflow' ? (workflowDescribed || at > 1) && at > 0 : index < at;
        const current = index === at;
        let state = 'next';
        if (done) state = 'done';
        else if (current) state = 'current';
        const reason = disabled[step.stage] ?? null;
        const hint =
          step.stage === 'workflow' && !workflowDescribed && at > 0 && !done
            ? 'Still on the defaults: open it to name the workflow.'
            : step.hint;
        const button = (
          <UnstyledButton
            role="tab"
            aria-selected={current}
            aria-disabled={reason ? true : undefined}
            onClick={() => {
              if (!reason) onSelect(step.stage);
            }}
            data-testid={`builder-guide-${step.stage}`}
            data-state={state}
            style={{
              display: 'flex',
              gap: 'var(--mantine-spacing-xs)',
              alignItems: compact ? 'center' : 'flex-start',
              width: '100%',
              height: '100%',
              padding: 'var(--mantine-spacing-xs)',
              borderRadius: 'var(--mantine-radius-md)',
              border: `1px solid ${
                current ? `var(--mantine-color-${accent.secondary}-6)` : 'var(--mantine-color-default-border)'
              }`,
              background: current ? `var(--mantine-color-${accent.secondary}-light)` : undefined,
              opacity: reason ? 0.45 : done || current ? 1 : 0.8,
              cursor: reason ? 'not-allowed' : 'pointer',
            }}
          >
            <ThemeIcon
              variant={current ? 'filled' : 'light'}
              color={done ? 'green' : accent.secondary}
              size="md"
              radius="xl"
            >
              <Icon icon={done ? 'mdi:check' : step.icon} width={16} />
            </ThemeIcon>
            <div style={{ minWidth: 0 }}>
              <Text size="sm" fw={600} lh={1.25}>
                {index + 1}. {step.title}
              </Text>
              {!compact && (
                <Text size="xs" c="dimmed" mt={2}>
                  {hint}
                </Text>
              )}
            </div>
          </UnstyledButton>
        );
        return reason ? (
          <Tooltip key={step.stage} label={reason} withArrow>
            <div>{button}</div>
          </Tooltip>
        ) : (
          <React.Fragment key={step.stage}>{button}</React.Fragment>
        );
      })}
    </SimpleGrid>
  );
};

export default GuideStrip;
