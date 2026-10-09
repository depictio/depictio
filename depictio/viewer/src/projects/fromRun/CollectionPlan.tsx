/**
 * The data collections of a run-folder plan, one line each, grouped by what
 * needs a look first: "Not found" and "Found" open, "Optional, not found"
 * folded (it informs, it is not a problem).
 *
 * A line says what the collection is, where it looks (relative to the run
 * folder, the real path on hover) and how much it found; a click opens what
 * it looked for and found: the rule of a scan and the first files it matched,
 * or, for a table, the recipe that builds it and what each of its inputs
 * found. Every file found opens onto its first rows.
 *
 * Shared by the checks of a folder ("Collections"), the Preview step and the
 * report after creation.
 */
import React, { useState } from 'react';
import {
  Accordion,
  ActionIcon,
  Code,
  Group,
  Stack,
  Table,
  Text,
  ThemeIcon,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { groupRunCollections, relativeToRunFolder, Z_LAYERS } from 'depictio-react-core';
import type {
  FromRunDCPreview,
  FromRunRecipeSource,
  RunCollectionSection,
  RunStorageIn,
} from 'depictio-react-core';

import { CollectionKindIcon, collectionKindMeta } from './CollectionKindIcon';
import { RunFilePath, RunFileScope } from './FilePreview';
import { plural } from './plural';

const SECTIONS: Record<
  RunCollectionSection,
  { title: string; icon: string; color: string; hint: string | null }
> = {
  missing: {
    title: 'Not found',
    icon: 'mdi:alert-circle-outline',
    color: 'red',
    hint: 'The project can still be created: these stay empty until their files exist.',
  },
  ready: {
    title: 'Found',
    icon: 'mdi:check-circle-outline',
    color: 'green',
    hint: null,
  },
  optional: {
    title: 'Optional, not found',
    icon: 'mdi:minus-circle-outline',
    color: 'gray',
    hint: 'Skipped when their files are absent.',
  },
};

const SECTION_ORDER: RunCollectionSection[] = ['missing', 'ready', 'optional'];

interface RowStatus {
  icon: string;
  color: string;
  label: string;
}

function rowStatus(dc: FromRunDCPreview, section: RunCollectionSection): RowStatus {
  if (section === 'ready') return { icon: 'mdi:check-circle', color: 'green', label: 'Found' };
  if (section === 'optional') {
    return dc.status === 'pruned'
      ? {
          icon: 'mdi:debug-step-over',
          color: 'gray',
          label: 'Left out: a template setting turns it off for this run',
        }
      : { icon: 'mdi:minus-circle-outline', color: 'gray', label: 'Optional, not found' };
  }
  return dc.status === 'empty'
    ? { icon: 'mdi:folder-alert-outline', color: 'orange', label: 'Its folder holds no matching file' }
    : { icon: 'mdi:close-circle', color: 'red', label: 'Not found' };
}

function countText(dc: FromRunDCPreview, unit: 'file' | 'input'): string {
  if (dc.status === 'pruned') return 'Left out';
  if (dc.matched > 0) return plural(dc.matched, unit);
  if (dc.status === 'ok') return 'At ingestion';
  return `No ${unit}s`;
}

const DetailLabel: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <Text size="xs" fw={700} c="dimmed" tt="uppercase" w={84} style={{ flexShrink: 0 }} pt={2}>
    {children}
  </Text>
);

/** One labelled line of a collection's details. */
const DetailLine: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <Group gap="xs" wrap="nowrap" align="flex-start">
    <DetailLabel>{label}</DetailLabel>
    <Stack gap={2} style={{ flex: 1, minWidth: 0 }}>
      {children}
    </Stack>
  </Group>
);

/** The first matches, each previewable, then how many more there are. */
const FoundList: React.FC<{
  samples: string[];
  matched: number;
  testId?: string;
}> = ({ samples, matched, testId }) => {
  if (samples.length === 0) return null;
  const more = matched - samples.length;
  return (
    <Stack gap={0} data-testid={testId}>
      {samples.map((sample) => (
        <RunFilePath key={sample} location={sample} />
      ))}
      {more > 0 && (
        <Text size="xs" c="dimmed">
          and {plural(more, 'more file')}
        </Text>
      )}
    </Stack>
  );
};

const SOURCE_KIND: Record<FromRunRecipeSource['kind'], { icon: string; label: string }> = {
  file: { icon: 'mdi:file-search-outline', label: 'Files of the run' },
  collection: { icon: 'mdi:table-arrow-right', label: 'Another collection' },
  url: { icon: 'mdi:link-variant', label: 'Read from its address' },
};

function sourceStatus(source: FromRunRecipeSource): RowStatus {
  if (source.found === null) {
    return { icon: 'mdi:clock-outline', color: 'gray', label: 'Read at ingestion' };
  }
  if (source.found) return { icon: 'mdi:check-circle', color: 'green', label: 'Found' };
  if (source.optional) {
    return { icon: 'mdi:minus-circle-outline', color: 'gray', label: 'Optional, not found' };
  }
  return { icon: 'mdi:close-circle', color: 'red', label: 'Not found' };
}

const StatusIcon: React.FC<{ status: RowStatus; size?: number }> = ({ status, size = 16 }) => (
  <Tooltip label={status.label} withArrow multiline maw={280} zIndex={Z_LAYERS.tooltip}>
    <ThemeIcon variant="transparent" color={status.color} size="sm" aria-label={status.label}>
      <Icon icon={status.icon} width={size} />
    </ThemeIcon>
  </Tooltip>
);

/** One input of a recipe: whether it was found, what it reads, and where. */
const RecipeSourceRow: React.FC<{ source: FromRunRecipeSource }> = ({ source }) => {
  const kind = SOURCE_KIND[source.kind];
  return (
    <Group
      gap={6}
      wrap="nowrap"
      align="flex-start"
      data-testid={`recipe-source-${source.ref}`}
      data-found={source.found === null ? 'unknown' : String(source.found)}
    >
      <StatusIcon status={sourceStatus(source)} size={14} />
      <Stack gap={0} style={{ flex: 1, minWidth: 0 }}>
        <Group gap={6} wrap="wrap">
          <Tooltip label={kind.label} withArrow zIndex={Z_LAYERS.tooltip}>
            <Text size="sm" fw={600} span>
              {source.ref}
            </Text>
          </Tooltip>
          {source.kind === 'collection' ? (
            <Text size="xs" c="dimmed" span>
              the table of <Code>{source.dc_ref}</Code>
            </Text>
          ) : (
            source.pattern && (
              <Code fz="xs" style={{ wordBreak: 'break-all' }}>
                {source.pattern}
              </Code>
            )
          )}
          {source.optional && (
            <Text span size="xs" c="dimmed" fs="italic">
              optional
            </Text>
          )}
        </Group>
        <FoundList samples={source.samples} matched={source.matched} />
      </Stack>
    </Group>
  );
};

/** What a collection looked for and what it found. */
const CollectionDetails: React.FC<{ dc: FromRunDCPreview; dataRoot: string }> = ({ dc, dataRoot }) => {
  const samples = dc.samples ?? [];
  const missing =
    dc.missing_sources.length > 0 && !dc.recipe ? (
      <DetailLine label="Not found">
        <Stack gap={0} data-testid={`run-missing-sources-${dc.data_collection_tag}`}>
          {dc.missing_sources.map((source) => {
            const relative = relativeToRunFolder(dataRoot, source);
            return (
              <Text
                key={source}
                size="xs"
                ff="monospace"
                c="red"
                title={source}
                style={{ wordBreak: 'break-all' }}
              >
                {relative === '' ? '(the run folder itself)' : relative ?? source}
              </Text>
            );
          })}
        </Stack>
      </DetailLine>
    ) : null;

  if (dc.kind === 'recipe' && dc.recipe) {
    const { recipe } = dc;
    return (
      <Stack gap={6} data-testid={`run-preview-details-${dc.data_collection_tag}`}>
        <DetailLine label="Recipe">
          <Group gap={6} wrap="wrap">
            <Code fz="xs" style={{ wordBreak: 'break-all' }} data-testid="recipe-name">
              {recipe.name}
            </Code>
            {recipe.summary && (
              <Text size="xs" c="dimmed" span>
                {recipe.summary}
              </Text>
            )}
          </Group>
        </DetailLine>
        {recipe.sources.length > 0 && (
          <DetailLine label="It reads">
            {recipe.sources.map((source) => (
              <RecipeSourceRow key={source.ref} source={source} />
            ))}
          </DetailLine>
        )}
      </Stack>
    );
  }
  // A rule that names one file of the run is written like the files found;
  // when it is exactly the one file found, it says nothing more.
  const ruleRelative = dc.rule ? relativeToRunFolder(dataRoot, dc.rule) : null;
  const rule = ruleRelative || dc.rule;
  const ruleIsTheFile =
    Boolean(ruleRelative) &&
    samples.length === 1 &&
    relativeToRunFolder(dataRoot, samples[0]) === ruleRelative;
  return (
    <Stack gap={6} data-testid={`run-preview-details-${dc.data_collection_tag}`}>
      {rule && !ruleIsTheFile && (
        <DetailLine label="Looks for">
          <Code
            fz="xs"
            title={dc.rule ?? undefined}
            style={{ alignSelf: 'flex-start', wordBreak: 'break-all' }}
          >
            {rule}
          </Code>
        </DetailLine>
      )}
      {samples.length > 0 ? (
        <DetailLine label="Found">
          <FoundList
            samples={samples}
            matched={dc.matched}
            testId={`run-preview-samples-${dc.data_collection_tag}`}
          />
        </DetailLine>
      ) : (
        !missing && (
          <Text size="xs" c="dimmed">
            {dc.status === 'ok' ? 'Its files are counted at ingestion.' : 'No file matched.'}
          </Text>
        )
      )}
      {missing}
    </Stack>
  );
};

function hasDetails(dc: FromRunDCPreview): boolean {
  if (dc.status === 'pruned') return false;
  return Boolean(
    dc.rule || dc.recipe || (dc.samples && dc.samples.length > 0) || dc.missing_sources.length > 0,
  );
}

/** Where a collection looks, relative to the run folder, on one line. */
const WhereCell: React.FC<{ dc: FromRunDCPreview; dataRoot: string }> = ({ dc, dataRoot }) => {
  if (dc.status === 'pruned' || !dc.location) return null;
  const relative = relativeToRunFolder(dataRoot, dc.location);
  if (relative === '') {
    return (
      <Text size="xs" c="dimmed" truncate>
        {dc.kind === 'recipe' ? 'files across the run folder' : 'the whole run folder'}
      </Text>
    );
  }
  return (
    <Tooltip label={dc.location} withArrow multiline maw={480} zIndex={Z_LAYERS.tooltip}>
      <Code
        fz="xs"
        data-testid={`run-preview-path-${dc.data_collection_tag}`}
        style={{
          display: 'block',
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
        }}
      >
        {relative ?? dc.location}
      </Code>
    </Tooltip>
  );
};

const CollectionRow: React.FC<{
  dc: FromRunDCPreview;
  dataRoot: string;
  section: RunCollectionSection;
}> = ({ dc, dataRoot, section }) => {
  const [open, setOpen] = useState(false);
  const tag = dc.data_collection_tag;
  const meta = collectionKindMeta(dc);
  const details = hasDetails(dc);
  const toggle = () => setOpen((o) => !o);
  return (
    <>
      <Table.Tr
        data-testid={`run-preview-row-${tag}`}
        data-status={dc.status}
        data-section={section}
        onClick={details ? toggle : undefined}
        style={details ? { cursor: 'pointer' } : undefined}
      >
        <Table.Td>
          <StatusIcon status={rowStatus(dc, section)} />
        </Table.Td>
        <Table.Td>
          <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
            <CollectionKindIcon dc={dc} size="sm" />
            <Text size="sm" fw={600} truncate title={tag}>
              {tag}
            </Text>
            {dc.optional && (
              <Text span size="xs" c="dimmed" fs="italic" style={{ flexShrink: 0 }}>
                optional
              </Text>
            )}
          </Group>
        </Table.Td>
        <Table.Td>
          <WhereCell dc={dc} dataRoot={dataRoot} />
        </Table.Td>
        <Table.Td ta="right">
          <Text size="xs" c="dimmed" data-testid={`run-preview-count-${tag}`}>
            {countText(dc, meta.unit)}
          </Text>
        </Table.Td>
        <Table.Td>
          {details && (
            <ActionIcon
              size="sm"
              variant="subtle"
              color="gray"
              onClick={(event) => {
                event.stopPropagation();
                toggle();
              }}
              aria-expanded={open}
              aria-label={dc.kind === 'recipe' ? 'Recipe and inputs' : 'What it looks for and found'}
              data-testid={`run-preview-details-toggle-${tag}`}
            >
              <Icon icon={open ? 'mdi:chevron-up' : 'mdi:chevron-down'} width={16} />
            </ActionIcon>
          )}
        </Table.Td>
      </Table.Tr>
      {details && (
        // Kept in the page while folded, so what was not found can be read
        // (and searched) without opening every line.
        <Table.Tr style={open ? undefined : { display: 'none' }} aria-hidden={!open}>
          <Table.Td />
          <Table.Td colSpan={4} pb="xs">
            <CollectionDetails dc={dc} dataRoot={dataRoot} />
          </Table.Td>
        </Table.Tr>
      )}
    </>
  );
};

/** One section of the plan: a one-line header, then its collections. */
const CollectionSection: React.FC<{
  section: RunCollectionSection;
  rows: FromRunDCPreview[];
  dataRoot: string;
}> = ({ section, rows, dataRoot }) => {
  const meta = SECTIONS[section];
  return (
    <Accordion.Item value={section} data-testid={`run-section-${section}`}>
      <Accordion.Control
        icon={
          <ThemeIcon variant="light" color={meta.color} size="sm" radius="xl">
            <Icon icon={meta.icon} width={14} />
          </ThemeIcon>
        }
      >
        <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
          <Text size="sm" fw={600} style={{ flexShrink: 0 }}>
            {meta.title}
          </Text>
          <Text size="sm" c="dimmed" style={{ flexShrink: 0 }}>
            {rows.length}
          </Text>
          {meta.hint && (
            <Text size="xs" c="dimmed" truncate>
              {meta.hint}
            </Text>
          )}
        </Group>
      </Accordion.Control>
      <Accordion.Panel>
        <Table.ScrollContainer minWidth={520} type="native">
          <Table layout="fixed" verticalSpacing={4} horizontalSpacing={6} highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th w={30} />
                <Table.Th w="38%">
                  <Text size="xs" c="dimmed" fw={600}>
                    Collection
                  </Text>
                </Table.Th>
                <Table.Th>
                  <Text size="xs" c="dimmed" fw={600}>
                    Looks in
                  </Text>
                </Table.Th>
                <Table.Th w={88} ta="right">
                  <Text size="xs" c="dimmed" fw={600}>
                    Found
                  </Text>
                </Table.Th>
                <Table.Th w={34} />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {rows.map((dc) => (
                <CollectionRow key={dc.data_collection_tag} dc={dc} dataRoot={dataRoot} section={section} />
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      </Accordion.Panel>
    </Accordion.Item>
  );
};

export const CollectionPlan: React.FC<{
  rows: FromRunDCPreview[];
  dataRoot: string;
  /** The private bucket's connection details, to preview its files. */
  storage?: RunStorageIn | null;
}> = ({ rows, dataRoot, storage = null }) => {
  const groups = groupRunCollections(rows);
  const present = SECTION_ORDER.filter((s) => groups[s].length > 0);
  return (
    <RunFileScope dataRoot={dataRoot} storage={storage}>
      <Accordion
        multiple
        variant="contained"
        radius="md"
        // What needs a look, and what was found, start open; the optional
        // collections that found nothing start folded.
        defaultValue={present.filter((s) => s !== 'optional')}
        chevronPosition="right"
        styles={{
          control: { paddingInlineStart: 'var(--mantine-spacing-xs)' },
          label: { paddingBlock: 6 },
          content: { padding: 0 },
        }}
      >
        {present.map((section) => (
          <CollectionSection key={section} section={section} rows={groups[section]} dataRoot={dataRoot} />
        ))}
      </Accordion>
    </RunFileScope>
  );
};
