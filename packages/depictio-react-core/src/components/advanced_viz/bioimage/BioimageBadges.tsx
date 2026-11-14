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
  onClick?: () => void;
  children: React.ReactNode;
}> = ({ color = 'gray', icon, tooltip, testId, onClick, children }) => {
  const badge = (
    <Badge
      component={onClick ? 'button' : undefined}
      onClick={onClick}
      style={onClick ? { cursor: 'pointer' } : undefined}
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
        Checked by {validation.validator}
        {validation.checked ? `: ${validation.checked}` : ''}
      </Text>
    ) : null}
  </Stack>
);

/** What the tile read from the open image, for the size badge. */
export interface BadgeImageInfo {
  labels: readonly string[];
  shape: readonly number[];
  dtype: string;
  levels: number;
  width: number;
  height: number;
  sizes: { c: number; z: number; t: number };
  physicalSize: { value: number; unit: string } | null;
  zStep?: { value: number; unit: string } | null;
  tStep?: { value: number; unit: string } | null;
}

const DTYPE_BYTES: Record<string, number> = {
  Int8: 1,
  Uint8: 1,
  Int16: 2,
  Uint16: 2,
  Int32: 4,
  Uint32: 4,
  Float32: 4,
  Float64: 8,
};

/** `96 000`: thin-space groups, readable in a badge at any locale. */
export function groupDigits(n: number): string {
  return Math.round(n)
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
}

/** `16.0 GB`, from bytes. */
export function formatBytes(bytes: number): string {
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let v = bytes;
  let i = 0;
  while (v >= 1000 && i < units.length - 1) {
    v /= 1000;
    i += 1;
  }
  return `${i === 0 ? v : v.toPrecision(3)} ${units[i]}`;
}

function trimNumber(v: number): string {
  return Number(v.toPrecision(3)).toString();
}

/**
 * The size badge in words rather than axis letters: `96 000 × 55 296 · RGB ·
 * 0.45 µm/px`, `512 × 512 · 3 ch · 18 z · 40 t`. A three-channel 8-bit image is
 * called RGB, which is what such a store almost always is.
 */
export function sizeSummary(info: BadgeImageInfo): string {
  const parts = [`${groupDigits(info.width)} × ${groupDigits(info.height)}`];
  const { c, z, t } = info.sizes;
  if (c === 3 && info.dtype === 'Uint8') parts.push('RGB');
  else if (c > 1) parts.push(`${c} ch`);
  if (z > 1) parts.push(`${z} z`);
  if (t > 1) parts.push(`${t} t`);
  if (info.physicalSize) {
    parts.push(`${trimNumber(info.physicalSize.value)} ${info.physicalSize.unit}/px`);
  }
  return parts.join(' · ');
}

/** One line per axis, in store order: its size and, when the store says, its step. */
export function axisLines(info: BadgeImageInfo): string[] {
  return info.labels.map((label, i) => {
    const name = label.replace(/^_/, '').toLowerCase();
    const size = info.shape[i] ?? 1;
    const step =
      name === 'x' || name === 'y'
        ? info.physicalSize
        : name === 'z'
          ? (info.zStep ?? null)
          : name === 't'
            ? (info.tStep ?? null)
            : null;
    const what = name === 'c' ? 'channels' : name === 't' ? 'time points' : name === 'z' ? 'planes' : 'px';
    return `${name}: ${groupDigits(size)} ${what}${step ? `, ${trimNumber(step.value)} ${step.unit} each` : ''}`;
  });
}

const SizeTooltip: React.FC<{ info: BadgeImageInfo }> = ({ info }) => {
  const bytes = info.shape.reduce((a, b) => a * b, 1) * (DTYPE_BYTES[info.dtype] ?? 1);
  return (
    <Stack gap={4}>
      <Text size="xs" fw={600}>
        The open image
      </Text>
      <List size="xs" spacing={0}>
        {axisLines(info).map((line) => (
          <List.Item key={line}>{line}</List.Item>
        ))}
      </List>
      <Text size="xs">
        {info.dtype.toLowerCase()} pixels · {info.levels} resolution level
        {info.levels === 1 ? '' : 's'} · {formatBytes(bytes)} uncompressed at full resolution
      </Text>
      <Text size="xs" c="dimmed">
        Each tile only fetches the pieces of the pyramid it shows.
      </Text>
    </Stack>
  );
};

export interface BioimageBadgesProps {
  format?: BioimageFormat | null;
  validation?: BioimageNgffValidation | null;
  /** The NGFF version when there is no ingest report to take it from. */
  ngffVersion?: string | null;
  /** What the tile read from the open image. */
  image?: BadgeImageInfo | null;
  layout?: NgffContainerLayout | null;
  labels?: boolean;
  remote?: boolean;
  /** Where a remote store is read from. */
  host?: string | null;
  /** A click on a badge: the component's Info panel, with everything. */
  onOpenInfo?: () => void;
}

/**
 * What an image store is, as a short row of badges a reader can parse:
 * format and NGFF version with its check in one badge, the image's size in
 * words (not axis letters), where it is read from, and plate / labels only
 * when there are any. Each has the detail in its tooltip; a click opens the
 * Info panel.
 */
const BioimageBadges: React.FC<BioimageBadgesProps> = ({
  format,
  validation,
  ngffVersion,
  image,
  layout,
  labels,
  remote,
  host,
  onOpenInfo,
}) => {
  const version = format === 'ome-tiff' ? null : (validation?.ngff_version ?? ngffVersion ?? null);
  const identity = `${formatLabel(format)}${version ? ` ${version}` : ''}`;
  return (
    <>
      <Chip
        testId="bioimage-badge-format"
        color={validation ? (validation.ok ? 'teal' : 'orange') : 'gray'}
        icon={
          validation ? (validation.ok ? 'tabler:circle-check' : 'tabler:alert-triangle') : undefined
        }
        tooltip={
          validation ? (
            <ValidationTooltip validation={validation} />
          ) : version ? (
            `OME-NGFF ${version}: not checked against the spec`
          ) : undefined
        }
        onClick={onOpenInfo}
      >
        {identity}
      </Chip>
      {image ? (
        <Chip
          testId="bioimage-badge-size"
          tooltip={<SizeTooltip info={image} />}
          onClick={onOpenInfo}
        >
          {sizeSummary(image)}
        </Chip>
      ) : null}
      {remote ? (
        <Chip
          testId="bioimage-badge-remote"
          icon="tabler:cloud"
          tooltip={`Read in place from ${host ?? 'its own host'}, through this server: nothing is copied.`}
          onClick={onOpenInfo}
        >
          {host ?? 'Remote'}
        </Chip>
      ) : null}
      {layout === 'plate' || layout === 'well' ? (
        <Chip testId="bioimage-badge-layout" icon="tabler:grid-dots" onClick={onOpenInfo}>
          {layout === 'plate' ? 'Plate' : 'Well'}
        </Chip>
      ) : null}
      {labels ? (
        <Chip
          testId="bioimage-badge-labels"
          icon="tabler:shape"
          tooltip="A segmentation (labels) is drawn over the image"
          onClick={onOpenInfo}
        >
          Labels
        </Chip>
      ) : null}
    </>
  );
};

export default BioimageBadges;
