/**
 * What to do with a folder once Depictio has read it: use the template that
 * fits as it is, start from that template and edit it in the Project
 * Builder, or define the collections from scratch. Offered as soon as a
 * template is known, so the reader never lands in the builder by accident.
 *
 * Three tiles in a row, each a short title, one line and, for the edit, how
 * much of the template the builder can carry over. What the choice means
 * (and, for the edit, what is left out) is said once, below the tiles, for
 * the tile selected, so the tiles stay scannable.
 *
 * Editing is read from `useTemplateDraft`; it is disabled, with the reason,
 * when nothing can be carried over. When no template fits the folder
 * (`noTemplate`), the same three tiles are shown with the two template ones
 * locked and starting from scratch selected: the way forward is as visible as
 * with a template.
 */
import React, { useState } from 'react';
import {
  Alert,
  Anchor,
  Badge,
  Collapse,
  Group,
  Loader,
  SimpleGrid,
  Stack,
  Text,
  ThemeIcon,
  UnstyledButton,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { useBrandAccents } from 'depictio-react-core';
import type { BuilderTemplateDraft } from 'depictio-react-core';

import { plural } from './plural';
import type { TemplateDraftState } from './useTemplateDraft';

export type NextStep = 'use' | 'edit' | 'scratch';

/** Dropped items named by their tag, not as a feature of the template. */
export const ITEM_KINDS: ReadonlySet<string> = new Set(['collection', 'link', 'option']);

/** What the builder cannot carry over from a template, one line each. */
export const LeftOutList: React.FC<{ items: BuilderTemplateDraft['dropped']; testId: string }> = ({
  items,
  testId,
}) => (
  <Stack gap={2} data-testid={testId}>
    {items.map((item, i) => (
      <Text key={`${item.kind}-${item.tag ?? i}`} size="xs" c="dimmed">
        {item.tag ? `${item.tag}: ` : ''}
        {item.reason}
      </Text>
    ))}
  </Stack>
);

interface NextStepChoiceProps {
  value: NextStep;
  onChange: (value: NextStep) => void;
  templateTitle: string | null;
  /** The workflow engine the template was written for, when the catalog says. */
  engine?: string | null;
  draft: TemplateDraftState;
  /** Why no choice can be made now (a private bucket not yet connected...). */
  disabledReason?: string | null;
  /** The folder was read and no template fits it: only scratch is open. */
  noTemplate?: boolean;
}

/** How much of the template the builder carries over. */
function carryOver(result: BuilderTemplateDraft) {
  const lostCollections = result.dropped.filter((d) => d.kind === 'collection').length;
  const total = result.carried.collections + lostCollections;
  const features = [
    ...new Set(result.dropped.filter((d) => !ITEM_KINDS.has(d.kind)).map((d) => d.kind)),
  ];
  return {
    carried: result.carried.collections,
    links: result.carried.links,
    lostCollections,
    total,
    features,
    /** Less than half: the draft is a sketch of the template. */
    sketch: total > 0 && result.carried.collections * 2 < total,
  };
}

interface TileProps {
  step: NextStep;
  active: boolean;
  disabledReason: string | null;
  icon: string;
  title: string;
  recommended?: boolean;
  onSelect: () => void;
  children: React.ReactNode;
  /** A last line under the description (what the choice keeps). */
  meta?: React.ReactNode;
}

const Tile: React.FC<TileProps> = ({
  step,
  active,
  disabledReason,
  icon,
  title,
  recommended,
  onSelect,
  children,
  meta,
}) => {
  const accent = useBrandAccents();
  const disabled = Boolean(disabledReason);
  return (
    <UnstyledButton
      role="radio"
      aria-checked={active}
      aria-disabled={disabled || undefined}
      onClick={() => {
        if (!disabled) onSelect();
      }}
      data-testid={`run-next-${step}`}
      data-active={active || undefined}
      style={{
        height: '100%',
        borderRadius: 'var(--mantine-radius-md)',
        border: `1px solid ${
          active ? `var(--mantine-color-${accent.secondary}-6)` : 'var(--mantine-color-default-border)'
        }`,
        // A selected tile is outlined by a shadow, not a thicker border, so
        // the three tiles never change size.
        boxShadow: active ? `0 0 0 1px var(--mantine-color-${accent.secondary}-6)` : undefined,
        background: active ? `var(--mantine-color-${accent.secondary}-light)` : undefined,
        opacity: disabled ? 0.55 : 1,
        cursor: disabled ? 'not-allowed' : 'pointer',
        padding: 'var(--mantine-spacing-sm)',
      }}
    >
      <Stack gap={8} h="100%" justify="space-between">
        <Stack gap={6}>
          <Group gap="xs" wrap="nowrap" justify="space-between" align="flex-start">
            <ThemeIcon variant={active ? 'filled' : 'light'} color={accent.secondary} size="lg" radius="md">
              <Icon icon={icon} width={20} />
            </ThemeIcon>
            {active ? (
              <Icon icon="mdi:check-circle" width={20} color={`var(--mantine-color-${accent.secondary}-6)`} />
            ) : (
              recommended && (
                <Badge size="xs" variant="light" color={accent.secondary}>
                  Recommended
                </Badge>
              )
            )}
          </Group>
          <Text fw={600} size="sm" lh={1.25}>
            {title}
          </Text>
          <Text size="xs" c="dimmed">
            {children}
          </Text>
        </Stack>
        {(meta || disabledReason) && (
          <Text size="xs" fw={500} data-testid={disabledReason ? `run-next-${step}-reason` : undefined}>
            {disabledReason ? (
              <>
                <Icon icon="mdi:lock-outline" width={12} style={{ verticalAlign: '-2px' }} /> {disabledReason}
              </>
            ) : (
              meta
            )}
          </Text>
        )}
      </Stack>
    </UnstyledButton>
  );
};

/** What the selected tile does, in a sentence or two. */
const Detail: React.FC<{
  value: NextStep;
  name: string;
  engine: string | null;
  draft: TemplateDraftState;
  noTemplate: boolean;
}> = ({ value, name, engine, draft, noTemplate }) => {
  const [showLeftOut, setShowLeftOut] = useState(false);

  if (noTemplate) {
    return (
      <Text size="xs" c="dimmed" data-testid="run-next-detail">
        No template fits this folder. The Project Builder opens on an empty draft: you tick files in the
        folder, group them into collections and see what each one matches before anything is created. To
        use a template instead, pick its pipeline above.
      </Text>
    );
  }

  if (value === 'use') {
    return (
      <Text size="xs" c="dimmed" data-testid="run-next-detail">
        Creates the project from {name} as shipped, dashboards included. Next shows what it finds in this
        folder before anything is created.
      </Text>
    );
  }
  if (value === 'scratch') {
    return (
      <Text size="xs" c="dimmed" data-testid="run-next-detail">
        Opens the Project Builder on an empty draft, with no template
        {engine ? `, and sets the workflow engine to ${engine}` : ''}. You group the files into collections
        yourself.
      </Text>
    );
  }
  if (draft.status === 'loading') {
    return (
      <Group gap={6} data-testid="run-next-detail">
        <Loader size={12} />
        <Text size="xs" c="dimmed">
          Checking what the builder can carry over...
        </Text>
      </Group>
    );
  }
  if (draft.status !== 'ready') return null;

  const c = carryOver(draft.result);
  const leftOut = draft.result.dropped;
  return (
    <Alert
      variant="light"
      color={c.sketch ? 'yellow' : 'gray'}
      icon={<Icon icon={c.sketch ? 'mdi:alert-outline' : 'mdi:information-outline'} width={16} />}
      p="xs"
      data-testid="run-next-detail"
      data-sketch={c.sketch || undefined}
    >
      <Stack gap={4}>
        <Text size="xs">
          <Text span fw={600} inherit>
            {c.carried} of {plural(c.total, 'collection')}
          </Text>{' '}
          and {plural(c.links, 'link')} carry over to the builder
          {c.sketch ? ': the draft is a sketch of the template' : ''}.
          {c.lostCollections > 0 &&
            ' The rest is built from other collections, which the builder cannot express.'}
        </Text>
        <Text size="xs" c="dimmed">
          The project then follows your edits, not the shipped template
          {c.features.length > 0 ? `, and does not get its ${c.features.join(', ')}` : ''}.
        </Text>
        {leftOut.length > 0 && (
          <>
            <Anchor
              size="xs"
              component="button"
              type="button"
              onClick={() => setShowLeftOut((v) => !v)}
              data-testid="run-next-left-out-toggle"
              style={{ alignSelf: 'flex-start' }}
            >
              {showLeftOut ? 'Hide' : 'Show'} what is left out
            </Anchor>
            <Collapse in={showLeftOut}>
              <LeftOutList items={leftOut} testId="run-next-left-out" />
            </Collapse>
          </>
        )}
      </Stack>
    </Alert>
  );
};

export const NextStepChoice: React.FC<NextStepChoiceProps> = ({
  value,
  onChange,
  templateTitle,
  engine = null,
  draft,
  disabledReason = null,
  noTemplate = false,
}) => {
  const name = templateTitle ?? 'this template';
  const noTemplateReason = noTemplate ? 'No template fits this folder' : null;
  const useReason = disabledReason ?? noTemplateReason;
  let editReason = useReason;
  if (!editReason && draft.status === 'error') {
    editReason = 'Not available for this template';
  } else if (!editReason && draft.status === 'ready' && !draft.result.editable) {
    editReason = 'Nothing of it carries over';
  }

  let editMeta: React.ReactNode = null;
  if (draft.status === 'loading') {
    editMeta = (
      <Group gap={6} component="span" display="inline-flex" wrap="nowrap">
        <Loader size={10} /> Checking...
      </Group>
    );
  } else if (draft.status === 'ready' && draft.result.editable) {
    const c = carryOver(draft.result);
    editMeta = (
      <Text span size="xs" fw={500} c={c.sketch ? 'yellow.8' : undefined}>
        {c.carried} of {plural(c.total, 'collection')} carry over
      </Text>
    );
  }

  return (
    <Stack gap="xs" data-testid="run-next-choice">
      <Text size="sm" fw={600}>
        What do you want to do with this folder?
      </Text>
      <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="xs" role="radiogroup" aria-label="What to do with this folder">
        <Tile
          step="use"
          active={value === 'use'}
          disabledReason={useReason}
          icon="mdi:check-decagram-outline"
          title="Use the template"
          recommended={!noTemplate}
          onSelect={() => onChange('use')}
        >
          Preview what it finds, then create the project. Nothing to define.
        </Tile>
        <Tile
          step="edit"
          active={value === 'edit'}
          disabledReason={editReason}
          icon="mdi:file-edit-outline"
          title="Edit the template"
          onSelect={() => onChange('edit')}
          meta={editMeta}
        >
          Open it in the Project Builder as a draft, and change it.
        </Tile>
        <Tile
          step="scratch"
          active={value === 'scratch'}
          disabledReason={disabledReason}
          icon="mdi:folder-cog-outline"
          title="Start from scratch"
          recommended={noTemplate}
          onSelect={() => onChange('scratch')}
        >
          Open the Project Builder empty and define the collections yourself.
        </Tile>
      </SimpleGrid>
      <Detail value={value} name={name} engine={engine} draft={draft} noTemplate={noTemplate} />
    </Stack>
  );
};

export default NextStepChoice;
