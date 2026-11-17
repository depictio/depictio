/**
 * Where a derived collection comes from, as a chain: the collections and
 * files it is built from, the recipe that builds it, and the collection it
 * makes. Shown in the ingestion report and in the collection viewer.
 */
import React from 'react';
import {
  ActionIcon,
  Anchor,
  Badge,
  CopyButton,
  Group,
  Paper,
  Stack,
  Text,
  Tooltip,
  UnstyledButton,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import type { RecipeInput } from 'depictio-react-core';

import { DcTypeIcon } from '../dcTypeIcon';

export interface LineageResult {
  tag: string;
  type: string;
  rows?: number | null;
  columns?: number | null;
  location?: string | null;
}

const CopyPath: React.FC<{ value: string; label: string }> = ({ value, label }) => (
  <CopyButton value={value} timeout={1500}>
    {({ copied, copy }) => (
      <Tooltip label={copied ? 'Copied' : `${label}: ${value}`} withArrow multiline maw={420} style={{ wordBreak: 'break-all' }}>
        <ActionIcon
          size="sm"
          variant="subtle"
          color="gray"
          onClick={(e) => {
            e.stopPropagation();
            copy();
          }}
          aria-label={label}
        >
          <Icon icon={copied ? 'mdi:check' : 'mdi:content-copy'} width={14} />
        </ActionIcon>
      </Tooltip>
    )}
  </CopyButton>
);

const Step: React.FC<{ label: string; icon: string; children: React.ReactNode; testId: string }> = ({
  label,
  icon,
  children,
  testId,
}) => (
  <Paper withBorder radius="md" p="sm" style={{ flex: '1 1 220px', minWidth: 0 }} data-testid={testId}>
    <Group gap={6} mb={8} wrap="nowrap">
      <Icon icon={icon} width={14} style={{ opacity: 0.6 }} />
      <Text size="xs" c="dimmed" fw={600} tt="uppercase">
        {label}
      </Text>
    </Group>
    {children}
  </Paper>
);

const Arrow = () => (
  <Icon
    icon="mdi:arrow-right"
    width={18}
    style={{ opacity: 0.45, alignSelf: 'center', flexShrink: 0 }}
    aria-hidden
  />
);

export const DerivedLineage: React.FC<{
  inputs: RecipeInput[];
  recipe: string | null;
  recipeUrl?: string | null;
  summary?: string | null;
  description?: string | null;
  result: LineageResult;
  /** Tag → type, for each input collection's icon. */
  typeByTag: Record<string, string>;
  /** Input collections that hold no data: the result will be empty too. */
  emptyInputs?: Set<string>;
  idByTag?: Record<string, string>;
  onOpenDc?: (dcId: string) => void;
  /** Makes the result's name a link to its own page (not set when already on it). */
  onOpenResult?: () => void;
}> = ({
  inputs,
  recipe,
  recipeUrl,
  summary,
  description,
  result,
  typeByTag,
  emptyInputs,
  idByTag,
  onOpenDc,
  onOpenResult,
}) => {
  const recipeName = recipe ? (recipe.split('/').pop() ?? recipe) : null;
  const empty = inputs.filter((i) => i.kind === 'collection' && emptyInputs?.has(i.name));
  return (
    <Stack gap="xs" data-testid="derived-lineage">
      <Group gap="xs" align="stretch" wrap="wrap">
        <Step label="Built from" icon="mdi:source-branch" testId="lineage-inputs">
          <Stack gap={4}>
            {inputs.map((input) => {
              if (input.kind === 'collection') {
                const id = idByTag?.[input.name];
                const isEmpty = emptyInputs?.has(input.name);
                const chip = (
                  <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
                    <DcTypeIcon type={typeByTag[input.name] ?? 'table'} size={15} withTooltip={false} />
                    <Text size="sm" fw={500} c={isEmpty ? 'orange' : undefined} truncate="end">
                      {input.name}
                    </Text>
                    {isEmpty && (
                      <Tooltip label="This collection holds no data" withArrow>
                        <Text span c="orange" lh={1}>
                          <Icon icon="mdi:alert-outline" width={14} />
                        </Text>
                      </Tooltip>
                    )}
                  </Group>
                );
                return id && onOpenDc ? (
                  <Tooltip key={input.name} label="Open this collection" withArrow>
                    <UnstyledButton
                      onClick={(e) => {
                        e.stopPropagation();
                        onOpenDc(id);
                      }}
                      style={{ minWidth: 0 }}
                    >
                      {chip}
                    </UnstyledButton>
                  </Tooltip>
                ) : (
                  <React.Fragment key={input.name}>{chip}</React.Fragment>
                );
              }
              return (
                <Group key={`${input.name}-${input.path}`} gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
                  <Icon icon="mdi:file-outline" width={15} style={{ opacity: 0.6, flexShrink: 0 }} />
                  <Text size="sm" fw={500} truncate="end">
                    {input.name}
                  </Text>
                  {input.path && <CopyPath value={input.path} label="Copy the file's location" />}
                </Group>
              );
            })}
            {inputs.length === 0 && (
              <Text size="sm" c="dimmed">
                Not recorded
              </Text>
            )}
          </Stack>
        </Step>
        <Arrow />
        <Step label="Recipe" icon="mdi:flask-outline" testId="lineage-recipe">
          <Stack gap={4}>
            {recipeName ? (
              <Group gap={6} wrap="nowrap">
                {recipeUrl ? (
                  <Anchor
                    href={recipeUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    size="sm"
                    fw={500}
                    onClick={(e) => e.stopPropagation()}
                  >
                    <Group gap={4} wrap="nowrap">
                      <Text span inherit ff="monospace">
                        {recipeName}
                      </Text>
                      <Icon icon="mdi:open-in-new" width={13} />
                    </Group>
                  </Anchor>
                ) : (
                  <Text size="sm" fw={500} ff="monospace">
                    {recipeName}
                  </Text>
                )}
              </Group>
            ) : (
              <Text size="sm" c="dimmed">
                Not recorded
              </Text>
            )}
            {summary && (
              <Tooltip label={description} disabled={!description} multiline maw={420} withArrow>
                <Text size="sm" c="dimmed" lineClamp={2}>
                  {summary}
                </Text>
              </Tooltip>
            )}
          </Stack>
        </Step>
        <Arrow />
        <Step label="Result" icon="mdi:table-check" testId="lineage-result">
          <Stack gap={4}>
            <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
              {onOpenResult ? (
                <Tooltip label="Open this collection" withArrow>
                  <UnstyledButton
                    data-testid="lineage-result-open"
                    onClick={(e) => {
                      e.stopPropagation();
                      onOpenResult();
                    }}
                    style={{ minWidth: 0 }}
                  >
                    <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
                      <DcTypeIcon type={result.type} size={15} withTooltip={false} />
                      <Text size="sm" fw={600} truncate="end">
                        {result.tag}
                      </Text>
                    </Group>
                  </UnstyledButton>
                </Tooltip>
              ) : (
                <>
                  <DcTypeIcon type={result.type} size={15} withTooltip={false} />
                  <Text size="sm" fw={600} truncate="end">
                    {result.tag}
                  </Text>
                </>
              )}
              {result.location && <CopyPath value={result.location} label="Copy where the table is stored" />}
            </Group>
            {(result.rows != null || result.columns != null) && (
              <Text size="sm" c="dimmed">
                {[
                  result.rows != null ? `${result.rows.toLocaleString()} rows` : null,
                  result.columns != null ? `${result.columns} columns` : null,
                ]
                  .filter(Boolean)
                  .join(' · ')}
              </Text>
            )}
          </Stack>
        </Step>
      </Group>
      {empty.length > 0 && (
        <Badge variant="light" color="orange" radius="sm" tt="none" fw={500} w="fit-content">
          {`${empty.map((i) => i.name).join(', ')} ${empty.length === 1 ? 'holds' : 'hold'} no data: this collection will be empty too.`}
        </Badge>
      )}
    </Stack>
  );
};

export default DerivedLineage;
