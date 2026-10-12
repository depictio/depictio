/**
 * What a workflow's repository said about it (`POST /projects/builder/metadata`),
 * read-only: including what the template does not store (description,
 * author, license, homepage), and which sources contributed.
 */
import React from 'react';
import {
  Alert,
  Anchor,
  Badge,
  Group,
  Paper,
  Stack,
  Text,
  useComputedColorScheme,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { useBrandAccents } from 'depictio-react-core';
import type { BuilderRepoMetadata } from 'depictio-react-core';

/** The repository's own logo for the current scheme, else the other one. */
export function metadataLogo(
  meta: BuilderRepoMetadata | null | undefined,
  scheme: 'light' | 'dark',
): string | null {
  if (!meta) return null;
  return scheme === 'dark'
    ? meta.logo_dark || meta.logo_light || null
    : meta.logo_light || meta.logo_dark || null;
}

export const RepoMetadata: React.FC<{ meta: BuilderRepoMetadata }> = ({ meta }) => {
  const accent = useBrandAccents();
  const scheme = useComputedColorScheme('light');
  const logo = metadataLogo(meta, scheme);
  const rows: [string, React.ReactNode][] = [];
  if (meta.description) rows.push(['Description', meta.description]);
  if (meta.author) rows.push(['Author', meta.author]);
  if (meta.license) rows.push(['License', meta.license]);
  if (meta.homepage) {
    rows.push([
      'Homepage',
      <Anchor key="homepage" href={meta.homepage} target="_blank" rel="noreferrer" size="xs">
        {meta.homepage}
      </Anchor>,
    ]);
  }
  return (
    <Paper withBorder radius="sm" p="sm" data-testid="builder-repo-metadata">
      <Stack gap={6}>
        <Group gap={6} wrap="wrap">
          <Icon icon="mdi:information-outline" width={15} color={`var(--mantine-color-${accent.secondary}-6)`} />
          <Text size="xs" fw={700} tt="uppercase" c="dimmed">
            From the repository
          </Text>
          {meta.sources.length ? (
            meta.sources.map((s) => (
              <Badge key={s} size="xs" variant="light" color={accent.secondary} tt="none">
                {s}
              </Badge>
            ))
          ) : (
            <Text size="xs" c="dimmed">
              nothing found: fill the fields yourself
            </Text>
          )}
          {logo && (
            <img
              src={logo}
              alt=""
              style={{ height: 28, maxWidth: 200, objectFit: 'contain', marginLeft: 'auto' }}
            />
          )}
        </Group>
        {meta.blocked && (
          <Alert color="yellow" variant="light" p="xs" icon={<Icon icon="mdi:shield-alert-outline" width={14} />}>
            <Text size="xs">This server may not fetch that address, so nothing was read from it.</Text>
          </Alert>
        )}
        {rows.map(([label, value]) => (
          <Group key={label} gap="xs" wrap="nowrap" align="flex-start">
            <Text size="xs" c="dimmed" fw={600} style={{ minWidth: 76, flexShrink: 0 }}>
              {label}
            </Text>
            {/* Some sources put a whole README in the description: clamp it. */}
            <Text size="xs" lineClamp={4} style={{ minWidth: 0 }}>
              {value}
            </Text>
          </Group>
        ))}
      </Stack>
    </Paper>
  );
};
