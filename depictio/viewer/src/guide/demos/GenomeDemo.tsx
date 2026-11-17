/**
 * The "Browse the genome" part's demo: the dashboard's own genome browser in
 * a few lines, not the browser.
 *
 * No JBrowse instance is mounted: it is heavy, and the tile on the tab is the
 * real thing. This summarises the tile the Guide picked (its assembly, how
 * many tracks it opens, what drives it) and points at the metadata icon, which
 * lists every track with where it comes from. The tracks are not listed here
 * for that reason: the list belongs to the tile, and is always current.
 */
import React from 'react';
import { Anchor, Badge, Box, Group, Skeleton, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import { dashboardHref, dashboardLinkClickHandler } from '../../dashboards/lib/dashboardLinks';
import { genomeConfigOf } from 'depictio-react-core';
import type { GenomeDemoSource } from '../useGuideSources';

function titleOf(title: unknown): string {
  return typeof title === 'string' && title.trim() ? title : 'Genome browser';
}

export const GenomeDemo: React.FC<{ source: GenomeDemoSource | null | undefined }> = ({
  source,
}) => {
  if (source === undefined) return <Skeleton h={96} radius="md" />;
  if (!source) return null;
  const { metadata, tabLabel, here } = source.tile;
  const config = genomeConfigOf(metadata);
  const selectionDriver =
    config.selectionMode === 'visible_tracks' ? 'the tracks you open' : 'the track you click';
  const drivers = [
    config.locusFromDc && `the rows you filter in ${config.locusFromDc}`,
    config.selects && selectionDriver,
  ].filter(Boolean) as string[];

  return (
    <Stack gap="xs" data-testid="guide-genome-demo">
      <Box
        className="depictio-guide-tile"
        p="sm"
        data-guide-genome
        data-guide-genome-tile={metadata.index}
      >
        <Group gap={8} wrap="nowrap">
          <Icon
            icon="mdi:dna"
            width={18}
            style={{ flexShrink: 0, color: 'var(--mantine-primary-color-filled)' }}
          />
          <Text size="sm" fw={600} truncate>
            {titleOf(metadata.title)}
          </Text>
          <Text size="xs" c="dimmed" truncate>
            {here ? 'on this tab' : `on ${tabLabel}`}
          </Text>
        </Group>
        <Group gap={6} mt={8} wrap="wrap">
          {config.assembly && (
            <Badge size="sm" variant="light" color="gray">
              {config.assembly}
            </Badge>
          )}
          {config.maxTracks !== null && (
            <Badge size="sm" variant="light" color="gray">
              up to {config.maxTracks} tracks
            </Badge>
          )}
          {config.ucscTracks.length > 0 && (
            <Badge size="sm" variant="light" color="gray">
              {config.ucscTracks.length} from UCSC
            </Badge>
          )}
        </Group>
        <Text size="xs" c="dimmed" mt={8} lh={1.45}>
          {drivers.length > 0
            ? `Follows ${drivers.join(' and ')}.`
            : 'Opens where its author set it; you move it yourself.'}
        </Text>
      </Box>
      <Group gap={6} wrap="nowrap" align="flex-start">
        <Icon
          icon="mdi:information-outline"
          width={15}
          style={{ flexShrink: 0, marginTop: 2, color: 'var(--mantine-color-cyan-filled)' }}
        />
        <Text size="xs" c="dimmed" lh={1.45}>
          The information icon in the tile's corner lists every track it holds, with where each one
          comes from.
        </Text>
      </Group>
    </Stack>
  );
};

/**
 * "Where the browser appears": each tab of the family that holds one, as a
 * link, with the author's own line on why it is there (the description of the
 * section that holds it, as written). The open tab's link closes the Guide.
 */
export const GenomeWhere: React.FC<{
  tabs: GenomeDemoSource['tabs'];
  mode: 'view' | 'edit';
  onCurrent: () => void;
}> = ({ tabs, mode, onCurrent }) => (
  <Stack gap={6} data-testid="guide-genome-where">
    <Text size="xs" c="dimmed" tt="uppercase" fw={700} style={{ letterSpacing: '0.06em' }}>
      Where the browser appears
    </Text>
    {tabs.map((t) => {
      const described = t.sections.filter((s) => s.description);
      return (
        <Box key={t.dashboardId} data-testid="guide-genome-tab">
          <Anchor
            size="sm"
            fw={600}
            href={dashboardHref(t.dashboardId, mode)}
            onClick={t.here ? dashboardLinkClickHandler(onCurrent) : undefined}
          >
            {t.tabLabel}
            {t.here ? ' · you are here' : ''}
          </Anchor>
          {described.map((s) => (
            <Text key={s.name ?? ''} size="xs" c="dimmed" lh={1.45}>
              {described.length > 1 && s.name ? `${s.name}: ` : ''}
              {s.description}
            </Text>
          ))}
        </Box>
      );
    })}
  </Stack>
);

export default GenomeDemo;
