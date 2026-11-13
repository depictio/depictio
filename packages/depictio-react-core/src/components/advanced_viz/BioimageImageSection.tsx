import React, { useEffect, useState } from 'react';
import { Badge, Box, Code, Group, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import { fetchBioimageProvenance, type BioimageProvenance } from '../../api';
import { useImageInfo, type PublishedImageInfo } from './bioimage/imageInfoRegistry';

interface BioimageImageSectionProps {
  /** The image DC the tile reads (`config.image_dc_id`). */
  dcId: string;
  /** The component's index: the key its tile publishes the loaded image under. */
  componentKey: string;
}

const Heading: React.FC<{ icon: string; children: React.ReactNode }> = ({ icon, children }) => (
  <Group gap={6} mb={6} wrap="nowrap">
    <Icon icon={icon} width={13} color="var(--mantine-color-gray-6)" />
    <Text size="xs" fw={700} c="dimmed" tt="uppercase">
      {children}
    </Text>
  </Group>
);

const Row: React.FC<{ label: string; mono?: boolean; children: React.ReactNode }> = ({
  label,
  mono,
  children,
}) => (
  <Group gap={8} wrap="nowrap" align="flex-start">
    <Text size="xs" c="dimmed" w={78} style={{ flexShrink: 0 }}>
      {label}
    </Text>
    {mono ? (
      <Code fz={11} style={{ wordBreak: 'break-all' }}>
        {children}
      </Code>
    ) : (
      <Text size="xs" style={{ lineHeight: 1.4, wordBreak: 'break-word' }}>
        {children}
      </Text>
    )}
  </Group>
);

/** Intensities as the viewer shows them: whole numbers stay whole, floats get
 *  four significant digits. */
const intensity = (v: number): string =>
  Number.isInteger(v) ? String(v) : String(Number(v.toPrecision(4)));

const bytes = (n: number): string => {
  if (n < 1024) return `${n} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let value = n / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value < 10 ? 1 : 0)} ${units[unit]}`;
};

const ImageRows: React.FC<{ published: PublishedImageInfo }> = ({ published }) => {
  const { store, info } = published;
  const x = info.labels.indexOf('x');
  const y = info.labels.indexOf('y');
  const axes = info.labels.map((label, i) => `${label} ${info.shape[i]}`).join(' · ');
  const pyramid = info.levelShapes
    .map((shape) => `${shape[x] ?? '?'}×${shape[y] ?? '?'}`)
    .join(' → ');
  return (
    <Stack gap={3}>
      <Row label="Store" mono>
        {store}
      </Row>
      <Row label="Axes">{axes}</Row>
      <Row label="Size">{`${info.width} × ${info.height} px`}</Row>
      <Row label="Data type">{info.dtype}</Row>
      <Row label="Pyramid">{`${info.levels} levels: ${pyramid}`}</Row>
      <Row label="Pixel size">
        {info.physicalSize
          ? `${info.physicalSize.value} ${info.physicalSize.unit} per pixel`
          : 'not in the store'}
      </Row>
      {info.channels.map((channel) => (
        <Row key={channel.index} label={channel.name}>
          <Group gap={6} wrap="nowrap" component="span" style={{ display: 'inline-flex' }}>
            <Box
              component="span"
              style={{
                width: 10,
                height: 10,
                borderRadius: 2,
                background: channel.color,
                flexShrink: 0,
              }}
            />
            <span>
              window {intensity(channel.contrastLimits[0])} – {intensity(channel.contrastLimits[1])}
              {' · '}data {intensity(channel.domain[0])} – {intensity(channel.domain[1])}
            </span>
          </Group>
        </Row>
      ))}
    </Stack>
  );
};

const ProvenanceRows: React.FC<{ provenance: BioimageProvenance }> = ({ provenance }) => {
  const format = [
    provenance.format,
    provenance.ngff_version ? `NGFF ${provenance.ngff_version}` : null,
  ]
    .filter(Boolean)
    .join(' · ');
  return (
    <Stack gap={3}>
      {provenance.description && <Row label="About">{provenance.description}</Row>}
      <Row label="Format">{format}</Row>
      {provenance.image_path && (
        <Row label="Element" mono>
          {provenance.image_path}
        </Row>
      )}
      {provenance.scan_source && (
        <Row label="Scanned" mono>
          {provenance.scan_source}
        </Row>
      )}
      <Row label="Storage">
        {provenance.upload
          ? 'Uploaded to object storage'
          : 'Read from the registered path (not uploaded)'}
      </Row>
      {provenance.stores.map((store) => (
        <Box key={store.name} mt={4}>
          <Group gap={6} wrap="nowrap" mb={2}>
            <Text size="xs" fw={600}>
              {store.name}
            </Text>
            {store.remote && (
              <Badge size="xs" color="gray" variant="light" radius="sm" tt="none">
                remote
              </Badge>
            )}
          </Group>
          <Stack gap={3}>
            {store.location && (
              <Row label="Location" mono>
                {store.location}
              </Row>
            )}
            {store.registration_time && (
              <Row label="Registered">{store.registration_time}</Row>
            )}
            {store.creation_time && <Row label="Created">{store.creation_time}</Row>}
            {store.filesize !== null && store.filesize > 0 && (
              <Row label="Size">{bytes(store.filesize)}</Row>
            )}
          </Stack>
        </Box>
      ))}
    </Stack>
  );
};

/**
 * The image behind a bioimage tile, for the component's Info tab: what the tile
 * is drawing (size, axes, channels, pixel size, read from the loaded image) and
 * where it comes from (the project's description, the scanned path, and each
 * store's registration record).
 */
const BioimageImageSection: React.FC<BioimageImageSectionProps> = ({ dcId, componentKey }) => {
  const published = useImageInfo(componentKey);
  const [provenance, setProvenance] = useState<BioimageProvenance | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setProvenance(null);
    setError(null);
    fetchBioimageProvenance(dcId)
      .then((next) => {
        if (!cancelled) setProvenance(next);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [dcId]);

  return (
    <Stack gap="sm">
      <Box>
        <Heading icon="mdi:image-outline">Image</Heading>
        {published ? (
          <ImageRows published={published} />
        ) : (
          <Text size="xs" c="dimmed">
            Shown once the tile has loaded its image.
          </Text>
        )}
      </Box>
      <Box>
        <Heading icon="mdi:source-branch">Source</Heading>
        {error && (
          <Text size="xs" c="red">
            {error}
          </Text>
        )}
        {!error && !provenance && (
          <Text size="xs" c="dimmed">
            Loading…
          </Text>
        )}
        {provenance && <ProvenanceRows provenance={provenance} />}
      </Box>
    </Stack>
  );
};

export default BioimageImageSection;
