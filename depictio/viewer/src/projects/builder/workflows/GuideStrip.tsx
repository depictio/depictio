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

const STEPS: { stage: GuideStage; icon: string; title: string; hint: string; detail: string }[] = [
  {
    stage: 'workflow',
    icon: 'mdi:sitemap-outline',
    title: 'Describe the workflows',
    hint: 'What made these files, and how they are laid out',
    detail:
      'Name the pipeline that produced these files, with its version and engine. Starting ' +
      'from a template fills this in for you: change only what differs.',
  },
  {
    stage: 'pick',
    icon: 'mdi:cursor-default-click-outline',
    title: 'Pick files',
    hint: 'Click a file, tick its siblings',
    detail:
      'Click a file in the tree on the left to see its first rows. Tick the matching files ' +
      'in other folders (one per sample or run) so one collection reads them all.',
  },
  {
    stage: 'define',
    icon: 'mdi:table-edit',
    title: 'Define the collection',
    hint: 'Name, type, what it matches',
    detail:
      'Give the collection a name and a type (table, MultiQC, image...). Check the pattern: ' +
      'the count shows how many files it matches, and the parts that differ become wildcards.',
  },
  {
    stage: 'review',
    icon: 'mdi:clipboard-check-outline',
    title: 'Review & create',
    hint: 'Check the plan, then create',
    detail:
      'See every collection, how many files each matches and what is still empty, then ' +
      'create the project. The project only exists once you create it here.',
  },
];

const ORDER = STEPS.map((step) => step.stage);

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
            ? 'Still on the defaults: name it'
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
              alignItems: 'center',
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
              {/* Two lines at most: the strip stays in view while scrolling. */}
              <Text size="sm" fw={600} lh={1.25} truncate>
                {index + 1}. {step.title}
              </Text>
              {!compact && (
                <Text size="xs" c="dimmed" mt={2} truncate>
                  {hint}
                </Text>
              )}
            </div>
          </UnstyledButton>
        );
        // The strip keeps two lines per step; the full description is on hover.
        const label = (
          <div data-testid={`builder-guide-${step.stage}-tooltip`}>
            <Text size="xs" fw={600}>
              {index + 1}. {step.title}
            </Text>
            <Text size="xs" mt={2}>
              {step.detail}
            </Text>
            {reason && (
              <Text size="xs" mt={4} fs="italic">
                {reason}
              </Text>
            )}
          </div>
        );
        return (
          <Tooltip key={step.stage} label={label} withArrow multiline w={300} openDelay={300}>
            <div>{button}</div>
          </Tooltip>
        );
      })}
    </SimpleGrid>
  );
};
