import React from 'react';
import { Badge, List, Stack, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import type { BioimageFormat, BioimageNgffValidation } from '../../../api';
import type { NgffContainerLayout } from './layout';

const FORMAT_LABELS: Record<BioimageFormat, string> = {
  'ome-zarr': 'OME-Zarr',
  'ome-tiff': 'OME-TIFF',
  spatialdata: 'SpatialData',
  tiff: 'TIFF',
};

export function formatLabel(format: BioimageFormat | null | undefined): string {
  return format ? (FORMAT_LABELS[format] ?? format) : 'Image';
}

/** The axes of an image as one word, in its own order (`TCZYX`, `CYX`). */
export function axesWord(labels: readonly string[] | null | undefined): string | null {
  if (!labels || labels.length === 0) return null;
  return labels.map((l) => l.replace(/^_/, '').toUpperCase()).join('');
}

/** Every bioimage badge has one look: Mantine's light xs badge, small radius. */
const Chip: React.FC<{
  color?: string;
  icon?: string;
  tooltip?: React.ReactNode;
  testId?: string;
  children: React.ReactNode;
}> = ({ color = 'gray', icon, tooltip, testId, children }) => {
  const badge = (
    <Badge
      size="xs"
      variant="light"
      radius="sm"
      tt="none"
      color={color}
      data-testid={testId}
      leftSection={icon ? <Icon icon={icon} width={11} /> : undefined}
    >
      {children}
    </Badge>
  );
  return tooltip ? (
    <Tooltip label={tooltip} multiline maw={320} withArrow openDelay={250}>
      {badge}
    </Tooltip>
  ) : (
    badge
  );
};

const ValidationTooltip: React.FC<{ validation: BioimageNgffValidation }> = ({ validation }) => (
  <Stack gap={4}>
    <Text size="xs" fw={600}>
      {validation.ok
        ? 'The NGFF metadata passes the spec checks'
        : 'Other viewers may refuse this store: the metadata breaks the NGFF spec'}
    </Text>
    {validation.issues.length ? (
      <List size="xs" spacing={2}>
        {validation.issues.slice(0, 6).map((issue) => (
          <List.Item key={issue}>{issue}</List.Item>
        ))}
      </List>
    ) : null}
    {validation.issues.length > 6 ? (
      <Text size="xs">+{validation.issues.length - 6} more in the Info tab</Text>
    ) : null}
    {validation.validator ? (
      <Text size="xs" c="dimmed">
        Checked at ingest by {validation.validator}
        {validation.checked ? `: ${validation.checked}` : ''}
      </Text>
    ) : null}
  </Stack>
);

export interface BioimageBadgesProps {
  format?: BioimageFormat | null;
  validation?: BioimageNgffValidation | null;
  /** The NGFF version when there is no ingest report to take it from. */
  ngffVersion?: string | null;
  /** Axis labels of the open image, in order. */
  axes?: readonly string[] | null;
  layout?: NgffContainerLayout | null;
  labels?: boolean;
  remote?: boolean;
}

/**
 * What an image store is, as a row of badges: format, NGFF version and
 * whether its metadata passes the spec, axes, plate, labels, remote. One
 * component for the viewer tile and the data-collection pages, so a store
 * reads the same everywhere.
 */
const BioimageBadges: React.FC<BioimageBadgesProps> = ({
  format,
  validation,
  ngffVersion,
  axes,
  layout,
  labels,
  remote,
}) => {
  const version = validation?.ngff_version ?? ngffVersion ?? null;
  const axesText = axesWord(axes);
  return (
    <>
      <Chip testId="bioimage-badge-format">{formatLabel(format)}</Chip>
      {validation ? (
        <Chip
          testId="bioimage-badge-ngff"
          color={validation.ok ? 'teal' : 'orange'}
          icon={validation.ok ? 'tabler:circle-check' : 'tabler:alert-triangle'}
          tooltip={<ValidationTooltip validation={validation} />}
        >
          {version ? `NGFF ${version}` : 'NGFF'}
        </Chip>
      ) : version ? (
        <Chip testId="bioimage-badge-ngff">NGFF {version}</Chip>
      ) : null}
      {axesText ? (
        <Chip testId="bioimage-badge-axes" tooltip="Axes of the open image, in store order">
          {axesText}
        </Chip>
      ) : null}
      {layout === 'plate' || layout === 'well' ? (
        <Chip testId="bioimage-badge-layout" icon="tabler:grid-dots">
          {layout === 'plate' ? 'Plate' : 'Well'}
        </Chip>
      ) : null}
      {labels ? (
        <Chip testId="bioimage-badge-labels" icon="tabler:shape">
          Labels
        </Chip>
      ) : null}
      {remote ? (
        <Chip
          testId="bioimage-badge-remote"
          icon="tabler:cloud"
          tooltip="Read in place from its own host, through this server"
        >
          Remote
        </Chip>
      ) : null}
    </>
  );
};

export default BioimageBadges;
