/**
 * How Depictio reads a folder, from the least to the most structured:
 *
 *  1. Flat tables: a standard project, each table file one collection.
 *  2. Custom workflows: the reader's own workflows and the collections each
 *     produces, defined in the Project Builder.
 *  3. Pipeline template: a recognised pipeline, read with Depictio's template
 *     for it (one workflow). When only some of its collections have files
 *     here, the tile asks whether to keep all of them or only those found.
 *     "Adjust in the builder" opens that choice in the Project Builder.
 *     Nothing recognised: the tile itself offers to choose the pipeline.
 *
 * Shown as soon as the folder is read. The most structured level that fits is
 * preselected; a level that does not fit stays in view, locked with the
 * reason, so the three are always the same choice in the same place.
 */
import React from 'react';
import { Badge, Button, Group, SimpleGrid, Stack, Text, ThemeIcon, Tooltip, UnstyledButton } from '@mantine/core';
import { Icon } from '@iconify/react';

import { useBrandAccents } from 'depictio-react-core';

export type ReadLevel = 'flat' | 'custom' | 'template';

interface LevelTileProps {
  level: ReadLevel;
  rank: number;
  active: boolean;
  recommended: boolean;
  lockedReason: string | null;
  icon: string;
  title: string;
  onSelect: () => void;
  children: React.ReactNode;
  /** Under the tile's text; shown even when locked (a way to unlock it). */
  footer?: React.ReactNode;
  /** Above the footer: what the reader should know before choosing it. */
  partialNote?: React.ReactNode;
}

const LevelTile: React.FC<LevelTileProps> = ({
  level,
  rank,
  active,
  recommended,
  lockedReason,
  icon,
  title,
  onSelect,
  children,
  footer,
  partialNote,
}) => {
  const accent = useBrandAccents();
  const locked = Boolean(lockedReason);
  return (
    <UnstyledButton
      role="radio"
      aria-checked={active}
      aria-disabled={locked || undefined}
      onClick={() => {
        if (!locked) onSelect();
      }}
      data-testid={`read-level-${level}`}
      data-active={active || undefined}
      style={{
        height: '100%',
        borderRadius: 'var(--mantine-radius-md)',
        border: `1px solid ${
          active ? `var(--mantine-color-${accent.secondary}-6)` : 'var(--mantine-color-default-border)'
        }`,
        // Outlined by a shadow, not a thicker border: the tiles never resize.
        boxShadow: active ? `0 0 0 1px var(--mantine-color-${accent.secondary}-6)` : undefined,
        background: active ? `var(--mantine-color-${accent.secondary}-light)` : undefined,
        cursor: locked ? 'not-allowed' : 'pointer',
        padding: 'var(--mantine-spacing-sm)',
      }}
    >
      <Stack gap={8} h="100%" justify="space-between">
        {/* Dimmed when locked, but not the footer: it may unlock the tile. */}
        <Stack gap={6} style={{ opacity: locked ? 0.55 : 1 }}>
          <Group gap="xs" wrap="nowrap" justify="space-between" align="center">
            <Group gap="sm" wrap="nowrap" align="center" style={{ minWidth: 0 }}>
              {/* The rank says the progression: 1 to 3, least to most structured. */}
              <ThemeIcon
                variant={active ? 'filled' : 'light'}
                color={accent.secondary}
                size={34}
                radius="xl"
              >
                <Text fw={700} size="md" inherit>
                  {rank}
                </Text>
              </ThemeIcon>
              <Icon
                icon={icon}
                width={26}
                color={`var(--mantine-color-${accent.secondary}-6)`}
                style={{ flexShrink: 0 }}
              />
              <Text fw={700} size="md" lh={1.2}>
                {title}
              </Text>
            </Group>
            {active ? (
              <Icon
                icon="mdi:check-circle"
                width={22}
                color={`var(--mantine-color-${accent.secondary}-6)`}
                style={{ flexShrink: 0 }}
              />
            ) : (
              recommended && (
                <Badge size="sm" variant="light" color={accent.secondary} style={{ flexShrink: 0 }}>
                  Recommended
                </Badge>
              )
            )}
          </Group>
          <Text size="sm" c="dimmed">
            {children}
          </Text>
        </Stack>
        <Stack gap={6}>
          {lockedReason && (
            <Text size="xs" fw={500} c="dimmed" data-testid={`read-level-${level}-reason`}>
              <Icon icon="mdi:lock-outline" width={12} style={{ verticalAlign: '-2px' }} /> {lockedReason}
            </Text>
          )}
          {partialNote}
          {footer}
        </Stack>
      </Stack>
    </UnstyledButton>
  );
};

type Scope = NonNullable<ReadLevelChoiceProps['template']['scope']>;

/** "All N" or "Only the M found": which of the template's collections the
 *  project gets. Buttons rendered as divs: the tile is a button already. */
const TemplateScope: React.FC<{ scope: Scope; onSelectTile: () => void }> = ({ scope, onSelectTile }) => {
  const accent = useBrandAccents();
  const parts = [
    scope.empty ? `${scope.empty} empty for now` : null,
    scope.absent ? `${scope.absent} not in this run` : null,
  ].filter(Boolean);
  const without = parts.join(', ');
  const option = (all: boolean, label: string) => {
    const on = scope.keepAll === all;
    return (
      <Button
        component="div"
        role="radio"
        aria-checked={on}
        size="compact-xs"
        flex={1}
        // Light, not filled: the filled button under it is the tile's action.
        variant={on ? 'light' : 'default'}
        style={on ? { boxShadow: `inset 0 0 0 1px var(--mantine-color-${accent.secondary}-6)` } : undefined}
        color={accent.secondary}
        onClick={(event: React.MouseEvent) => {
          event.stopPropagation();
          onSelectTile();
          scope.onChange(all);
        }}
        data-testid={`read-level-template-scope-${all ? 'all' : 'found'}`}
        data-active={on || undefined}
      >
        {label}
      </Button>
    );
  };
  return (
    <Stack gap={4} data-testid="read-level-template-scope">
      <Group gap={4} wrap="nowrap" role="radiogroup" aria-label="Collections of the template">
        {option(false, `Only the ${scope.found} found`)}
        {option(true, 'Whole template')}
      </Group>
      <Text size="xs" c="dimmed">
        {scope.keepAll
          ? `Kept too: ${without}. Created empty, filled at a later refresh once their files exist.`
          : `Left out: ${without}. Add them back here or in the builder.`}
      </Text>
    </Stack>
  );
};

export interface ReadLevelChoiceProps {
  value: ReadLevel;
  onChange: (level: ReadLevel) => void;
  /** The level preselected for this folder (badged "Recommended"). */
  recommended: ReadLevel;
  flat: { tables: number; lockedReason: string | null };
  template: {
    /** e.g. "nf-core/ampliseq 2.14.0"; null when none fits. */
    title: string | null;
    lockedReason: string | null;
    /** Down to "Custom workflows" with this template as the start. */
    onEdit: () => void;
    /** Why the builder cannot start from it (still reading it...). */
    editReason: string | null;
    /** Open or close the list of pipelines, to name the one that made it. */
    onPick: () => void;
    pickOpen: boolean;
    /** Some of the template's collections have no files here: keep them all
     *  (filled at a later refresh) or only the ones found. Null when every
     *  one, or none, is found. */
    scope?: {
      found: number;
      /** Required ones without files that "Only the found" leaves out. */
      empty: number;
      /** Optional or conditional ones this run did not produce, left out. */
      absent: number;
      keepAll: boolean;
      onChange: (keepAll: boolean) => void;
    } | null;
  };
}

export const ReadLevelChoice: React.FC<ReadLevelChoiceProps> = ({
  value,
  onChange,
  recommended,
  flat,
  template,
}) => {
  const accent = useBrandAccents();
  return (
    <Stack gap="xs" data-testid="read-level-choice" role="radiogroup" aria-label="How Depictio reads this folder">
      <div>
        <Text fw={600} size="sm">
          How should Depictio read this folder?
        </Text>
        <Text size="xs" c="dimmed">
          From the least to the most structured. The best fit is selected.
        </Text>
      </div>
      <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="sm">
        <LevelTile
          level="flat"
          rank={1}
          active={value === 'flat'}
          recommended={recommended === 'flat'}
          lockedReason={flat.lockedReason}
          icon="mdi:table-multiple"
          title="Flat tables"
          onSelect={() => onChange('flat')}
        >
          One collection per table file, no workflow and no dashboards.
          {flat.tables > 0 ? ` ${flat.tables} found at the top of the folder.` : ''}
        </LevelTile>
        <LevelTile
          level="custom"
          rank={2}
          active={value === 'custom'}
          recommended={recommended === 'custom'}
          lockedReason={null}
          icon="mdi:folder-cog-outline"
          title="Custom workflows"
          onSelect={() => onChange('custom')}
        >
          Collections you define yourself in the Project Builder, grouped by the workflow that made
          them. No dashboards to start with; kept as a template for the next runs.
        </LevelTile>
        <LevelTile
          level="template"
          rank={3}
          active={value === 'template'}
          recommended={recommended === 'template'}
          lockedReason={template.lockedReason}
          icon="mdi:file-document-multiple-outline"
          title="Pipeline template"
          onSelect={() => onChange('template')}
          footer={
            template.lockedReason ? (
              <Button
                component="div"
                role="button"
                fullWidth
                size="xs"
                variant={template.pickOpen ? 'subtle' : 'light'}
                color={accent.secondary}
                leftSection={
                  <Icon icon={template.pickOpen ? 'mdi:chevron-up' : 'mdi:format-list-bulleted'} width={14} />
                }
                onClick={(event: React.MouseEvent) => {
                  // The tile is locked; only this button acts.
                  event.stopPropagation();
                  template.onPick();
                }}
                data-testid="read-level-template-pick"
              >
                {template.pickOpen ? 'Hide the pipelines' : 'Choose the pipeline'}
              </Button>
            ) : (
              <Tooltip label={template.editReason} disabled={!template.editReason} withArrow multiline maw={280}>
                {/* A span keeps the tooltip on a disabled button. */}
                <span>
                  <Button
                    component="div"
                    role="button"
                    fullWidth
                    size="xs"
                    // Filled on the tinted, selected tile: light would melt into it.
                    variant={value === 'template' ? 'filled' : 'light'}
                    color={accent.secondary}
                    leftSection={<Icon icon="mdi:pencil-outline" width={14} />}
                    data-disabled={template.editReason ? true : undefined}
                    aria-disabled={template.editReason ? true : undefined}
                    onClick={(event: React.MouseEvent) => {
                      // The tile is a button too: only this one acts.
                      event.stopPropagation();
                      if (!template.editReason) template.onEdit();
                    }}
                    data-testid="read-level-template-edit"
                  >
                    Adjust in the builder
                  </Button>
                </span>
              </Tooltip>
            )
          }
          partialNote={
            !template.lockedReason && template.scope ? (
              <TemplateScope scope={template.scope} onSelectTile={() => onChange('template')} />
            ) : null
          }
        >
          {template.title
            ? `Collections defined by Depictio's template for ${template.title}, with its recipes and dashboards ready to use.`
            : "Collections defined by Depictio's template for a recognised pipeline, with its dashboards."}
        </LevelTile>
      </SimpleGrid>
    </Stack>
  );
};
