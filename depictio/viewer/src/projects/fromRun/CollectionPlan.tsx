/**
 * The data collections of a run-folder plan, grouped by what needs a look
 * first: "Not found" and "Ready to ingest" open, "Optional, not found" folded
 * (it informs, it is not a problem).
 *
 * Each collection opens onto what it looked for and what it found: the rule
 * of a scan and the first files it matched, written relative to the run
 * folder with the real path in a tooltip and one click from the clipboard;
 * for a table, the recipe that builds it and what each of its inputs found.
 *
 * Shared by the Preview step, the report after creation and the folder
 * browser's "What the template finds here".
 */
import React, { useState } from 'react';
import {
  Accordion,
  Code,
  Collapse,
  Divider,
  Group,
  Stack,
  Text,
  ThemeIcon,
  Tooltip,
  UnstyledButton,
} from '@mantine/core';
import { useId } from '@mantine/hooks';
import { Icon } from '@iconify/react';

import { groupRunCollections, relativeToRunFolder, Z_LAYERS } from 'depictio-react-core';
import type {
  FromRunDCPreview,
  FromRunRecipeSource,
  RunCollectionSection,
} from 'depictio-react-core';

import { CollectionKindIcon, collectionKindMeta } from './CollectionKindIcon';
import { FlowBadge } from './FlowBadge';
import type { FlowStatus } from './FlowBadge';
import { FolderPath } from './FolderPath';
import { plural } from './plural';
import { SectionHeader } from './SectionHeader';

const SECTIONS: Record<
  RunCollectionSection,
  { title: string; icon: string; color: string; description: string }
> = {
  missing: {
    title: 'Not found',
    icon: 'mdi:alert-circle-outline',
    color: 'red',
    description:
      'These collections found nothing in this folder. You can still create the project: they stay empty until their files exist.',
  },
  ready: {
    title: 'Ready to ingest',
    icon: 'mdi:check-circle-outline',
    color: 'green',
    description: 'Found in the run folder and ingested when the project is created.',
  },
  optional: {
    title: 'Optional, not found',
    icon: 'mdi:minus-circle-outline',
    color: 'gray',
    description: 'The template can do without these. They are skipped when their files are absent.',
  },
};

const SECTION_ORDER: RunCollectionSection[] = ['missing', 'ready', 'optional'];

function rowStatus(dc: FromRunDCPreview, section: RunCollectionSection): FlowStatus {
  if (section === 'ready') return 'ready';
  if (section === 'optional') return dc.status === 'pruned' ? 'skipped' : 'optional';
  return dc.status === 'empty' ? 'no-files' : 'not-found';
}

function countText(dc: FromRunDCPreview, unit: 'file' | 'input'): string {
  if (dc.status === 'pruned') return '';
  if (dc.matched > 0) return plural(dc.matched, unit);
  if (dc.status === 'ok') return 'Counted at ingestion';
  return `No ${unit}s`;
}

/** A matched file, relative to the run folder, its real path a hover and a
 *  click away. */
const FoundPath: React.FC<{ location: string; dataRoot: string }> = ({ location, dataRoot }) => {
  const relative = relativeToRunFolder(dataRoot, location);
  return (
    <FolderPath
      location={location}
      label={relative === null || relative === '' ? undefined : relative}
      maxLength={96}
    />
  );
};

/** The first matches, then how many more there are. */
const FoundList: React.FC<{
  samples: string[];
  matched: number;
  unit: string;
  dataRoot: string;
  testId?: string;
}> = ({ samples, matched, unit, dataRoot, testId }) => {
  if (samples.length === 0) return null;
  const more = matched - samples.length;
  return (
    <Stack gap={2} data-testid={testId}>
      {samples.map((sample) => (
        <FoundPath key={sample} location={sample} dataRoot={dataRoot} />
      ))}
      {more > 0 && (
        <Text size="xs" c="dimmed">
          and {plural(more, `more ${unit}`, `more ${unit}s`)}
        </Text>
      )}
    </Stack>
  );
};

const DetailLabel: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <Text size="xs" fw={700} c="dimmed" tt="uppercase">
    {children}
  </Text>
);

const SOURCE_KIND: Record<FromRunRecipeSource['kind'], { icon: string; label: string }> = {
  file: { icon: 'mdi:file-search-outline', label: 'Files of the run' },
  collection: { icon: 'mdi:table-arrow-right', label: 'Another collection' },
  url: { icon: 'mdi:link-variant', label: 'Read from its address' },
};

function sourceStatus(source: FromRunRecipeSource): { icon: string; color: string; label: string } {
  if (source.found === null) {
    return { icon: 'mdi:clock-outline', color: 'gray', label: 'Read at ingestion' };
  }
  if (source.found) return { icon: 'mdi:check-circle', color: 'green', label: 'Found' };
  if (source.optional) {
    return { icon: 'mdi:minus-circle-outline', color: 'gray', label: 'Optional, not found' };
  }
  return { icon: 'mdi:close-circle', color: 'red', label: 'Not found' };
}

/** One input of a recipe: what it reads, whether it was found, and where. */
const RecipeSourceRow: React.FC<{ source: FromRunRecipeSource; dataRoot: string }> = ({
  source,
  dataRoot,
}) => {
  const kind = SOURCE_KIND[source.kind];
  const status = sourceStatus(source);
  return (
    <Group
      gap="sm"
      wrap="nowrap"
      align="flex-start"
      data-testid={`recipe-source-${source.ref}`}
      data-found={source.found === null ? 'unknown' : String(source.found)}
    >
      <Tooltip label={kind.label} withArrow zIndex={Z_LAYERS.tooltip}>
        <ThemeIcon variant="light" color="gray" size="md" radius="md" aria-label={kind.label}>
          <Icon icon={kind.icon} width={14} />
        </ThemeIcon>
      </Tooltip>
      <Stack gap={4} style={{ flex: 1, minWidth: 0 }}>
        <Group gap={8} wrap="wrap">
          <Text size="sm" fw={600}>
            {source.ref}
          </Text>
          {source.optional && (
            <Text span size="xs" c="dimmed" fs="italic">
              optional
            </Text>
          )}
        </Group>
        {source.kind === 'collection' ? (
          <Text size="xs" c="dimmed">
            The table of collection <Code>{source.dc_ref}</Code>
          </Text>
        ) : (
          source.pattern && (
            <Code style={{ alignSelf: 'flex-start', wordBreak: 'break-all' }}>{source.pattern}</Code>
          )
        )}
        <FoundList samples={source.samples} matched={source.matched} unit="file" dataRoot={dataRoot} />
      </Stack>
      <Group gap={4} wrap="nowrap" style={{ flexShrink: 0 }}>
        <ThemeIcon variant="transparent" color={status.color} size="xs" aria-hidden>
          <Icon icon={status.icon} width={14} />
        </ThemeIcon>
        <Text size="xs" c="dimmed">
          {source.kind === 'file' && source.matched > 0 ? plural(source.matched, 'file') : status.label}
        </Text>
      </Group>
    </Group>
  );
};

/** What a collection looked for and what it found. */
const CollectionDetails: React.FC<{ dc: FromRunDCPreview; dataRoot: string }> = ({ dc, dataRoot }) => {
  const samples = dc.samples ?? [];
  if (dc.kind === 'recipe' && dc.recipe) {
    const { recipe } = dc;
    return (
      <Stack gap="xs" data-testid={`run-preview-details-${dc.data_collection_tag}`}>
        <Stack gap={2}>
          <DetailLabel>Recipe applied</DetailLabel>
          <Code style={{ alignSelf: 'flex-start', wordBreak: 'break-all' }} data-testid="recipe-name">
            {recipe.name}
          </Code>
          {recipe.summary && (
            <Text size="xs" c="dimmed">
              {recipe.summary}
            </Text>
          )}
        </Stack>
        {recipe.sources.length > 0 && (
          <Stack gap={6}>
            <DetailLabel>It reads</DetailLabel>
            {recipe.sources.map((source) => (
              <RecipeSourceRow key={source.ref} source={source} dataRoot={dataRoot} />
            ))}
          </Stack>
        )}
      </Stack>
    );
  }
  return (
    <Stack gap="xs" data-testid={`run-preview-details-${dc.data_collection_tag}`}>
      {dc.rule && (
        <Stack gap={2}>
          <DetailLabel>Looks for</DetailLabel>
          <Code style={{ alignSelf: 'flex-start', wordBreak: 'break-all' }}>{dc.rule}</Code>
        </Stack>
      )}
      {samples.length > 0 ? (
        <Stack gap={2}>
          <DetailLabel>Found</DetailLabel>
          <FoundList
            samples={samples}
            matched={dc.matched}
            unit="file"
            dataRoot={dataRoot}
            testId={`run-preview-samples-${dc.data_collection_tag}`}
          />
        </Stack>
      ) : (
        <Text size="xs" c="dimmed">
          {dc.status === 'ok' ? 'Its files are counted at ingestion.' : 'No file matched.'}
        </Text>
      )}
    </Stack>
  );
};

function hasDetails(dc: FromRunDCPreview): boolean {
  if (dc.status === 'pruned') return false;
  return Boolean(dc.rule || dc.recipe || (dc.samples && dc.samples.length > 0));
}

/** Where a collection looks, relative to the run folder. */
const LocationLine: React.FC<{ dc: FromRunDCPreview; dataRoot: string }> = ({ dc, dataRoot }) => {
  if (dc.status === 'pruned') {
    return (
      <Text size="xs" c="dimmed">
        Left out by the template for this run.
      </Text>
    );
  }
  if (!dc.location) return null;
  const relative = relativeToRunFolder(dataRoot, dc.location);
  if (relative === '') {
    return (
      <Text size="xs" c="dimmed">
        {dc.kind === 'recipe'
          ? 'Built from files across the run folder'
          : 'Looks through the whole run folder'}
      </Text>
    );
  }
  if (relative === null) {
    return <FolderPath location={dc.location} withCopy={false} maxLength={64} />;
  }
  return (
    <Tooltip label={dc.location} withArrow multiline maw={480} zIndex={Z_LAYERS.tooltip}>
      <Code
        data-testid={`run-preview-path-${dc.data_collection_tag}`}
        style={{ alignSelf: 'flex-start', wordBreak: 'break-all' }}
      >
        {relative}
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
  const detailsId = useId();
  const meta = collectionKindMeta(dc);
  const status = rowStatus(dc, section);
  const count = countText(dc, meta.unit);
  const details = hasDetails(dc);
  return (
    <Stack
      gap={6}
      py="xs"
      data-testid={`run-preview-row-${dc.data_collection_tag}`}
      data-status={dc.status}
      data-section={section}
    >
      <Group wrap="nowrap" align="flex-start" gap="sm">
        <CollectionKindIcon dc={dc} />
        <Stack gap={4} style={{ flex: 1, minWidth: 0 }}>
          <Group gap={8} wrap="wrap">
            <Text size="sm" fw={600} style={{ wordBreak: 'break-word' }}>
              {dc.data_collection_tag}
            </Text>
            {dc.optional && (
              <Text span size="xs" c="dimmed" fs="italic">
                optional
              </Text>
            )}
          </Group>
          <LocationLine dc={dc} dataRoot={dataRoot} />
          {dc.missing_sources.length > 0 && !dc.recipe && (
            <Stack gap={2} data-testid={`run-missing-sources-${dc.data_collection_tag}`}>
              <Text size="xs" c="dimmed">
                Looked for, not found:
              </Text>
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
          )}
          {details && (
            <UnstyledButton
              onClick={() => setOpen((o) => !o)}
              aria-expanded={open}
              aria-controls={detailsId}
              style={{ alignSelf: 'flex-start' }}
              data-testid={`run-preview-details-toggle-${dc.data_collection_tag}`}
            >
              <Group gap={2} wrap="nowrap">
                <Icon icon={open ? 'mdi:chevron-down' : 'mdi:chevron-right'} width={14} />
                <Text size="xs" c="dimmed">
                  {dc.kind === 'recipe' ? 'Recipe and inputs' : 'What it looks for and found'}
                </Text>
              </Group>
            </UnstyledButton>
          )}
        </Stack>
        <Stack gap={4} align="flex-end" style={{ flexShrink: 0 }}>
          <FlowBadge
            status={status}
            tooltip={
              status === 'skipped'
                ? 'One of the template settings turns this collection off for this run.'
                : undefined
            }
          />
          {count && (
            <Text size="xs" c="dimmed" data-testid={`run-preview-count-${dc.data_collection_tag}`}>
              {count}
            </Text>
          )}
        </Stack>
      </Group>
      {details && (
        <Collapse in={open} id={detailsId}>
          <Stack pl={46}>
            <CollectionDetails dc={dc} dataRoot={dataRoot} />
          </Stack>
        </Collapse>
      )}
    </Stack>
  );
};

/** One section of the plan: its header, then its collections in plan order. */
const CollectionSection: React.FC<{
  section: RunCollectionSection;
  rows: FromRunDCPreview[];
  dataRoot: string;
}> = ({ section, rows, dataRoot }) => {
  const meta = SECTIONS[section];
  return (
    <Accordion.Item value={section} data-testid={`run-section-${section}`}>
      <Accordion.Control>
        <SectionHeader
          icon={meta.icon}
          color={meta.color}
          title={meta.title}
          count={rows.length}
          description={meta.description}
        />
      </Accordion.Control>
      <Accordion.Panel>
        <Stack gap={0}>
          {rows.map((dc, index) => (
            <React.Fragment key={dc.data_collection_tag}>
              {index > 0 && <Divider />}
              <CollectionRow dc={dc} dataRoot={dataRoot} section={section} />
            </React.Fragment>
          ))}
        </Stack>
      </Accordion.Panel>
    </Accordion.Item>
  );
};

export const CollectionPlan: React.FC<{ rows: FromRunDCPreview[]; dataRoot: string }> = ({
  rows,
  dataRoot,
}) => {
  const groups = groupRunCollections(rows);
  const present = SECTION_ORDER.filter((s) => groups[s].length > 0);
  return (
    <Accordion
      multiple
      variant="separated"
      radius="md"
      // What needs a look, and what is ready, start open; the optional
      // collections that found nothing start folded.
      defaultValue={present.filter((s) => s !== 'optional')}
      chevronPosition="right"
    >
      {present.map((section) => (
        <CollectionSection key={section} section={section} rows={groups[section]} dataRoot={dataRoot} />
      ))}
    </Accordion>
  );
};
