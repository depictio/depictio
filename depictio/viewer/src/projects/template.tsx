import React from 'react';
import { Anchor, Avatar, Badge, Box, Group, Stack, Text, Tooltip } from '@mantine/core';

import type { ProjectListEntry } from 'depictio-react-core';

export interface ParsedTemplate {
  /** Original full identifier, e.g. `nf-core/viralrecon/3.0.0` */
  full: string;
  /** First slash-separated segment, e.g. `nf-core` */
  source: string;
  /** Middle segment if present, e.g. `viralrecon` */
  repo: string;
  /** Trailing segment if it looks like a semver, otherwise empty */
  version: string;
}

/** Parse `template_origin.template_id` (e.g. `nf-core/viralrecon/3.0.0`) into
 *  source/repo/version. Backwards-compatible with `template_origin` passed as
 *  a plain string and with shorter ids that omit the version segment. Returns
 *  null when the project wasn't created from a template. */
export function parseTemplate(project: ProjectListEntry): ParsedTemplate | null {
  const origin = project.template_origin as
    | { template_id?: string }
    | string
    | undefined;
  let raw: string | null = null;
  if (typeof origin === 'string') raw = origin.trim();
  else if (origin && typeof origin === 'object' && origin.template_id) {
    raw = origin.template_id.trim();
  }
  if (!raw) return null;
  const parts = raw.split('/').map((s) => s.trim()).filter(Boolean);
  const looksVersion = (s: string) => /^v?\d/.test(s);
  let version = '';
  if (parts.length >= 2 && looksVersion(parts[parts.length - 1])) {
    version = parts.pop() || '';
  }
  const source = parts[0] || raw;
  const repo = parts[1] || '';
  return { full: raw, source, repo, version };
}

/** Build the depictio-docs page URL for a parsed template. Pattern:
 *  ``https://depictio.github.io/depictio-docs/stable/pipeline-templates/{source}/{repo}/``
 *  Falls back to the templates index when there's no repo segment. */
export function templateDocsUrl(parsed: ParsedTemplate): string {
  const base = 'https://depictio.github.io/depictio-docs/stable/pipeline-templates';
  if (parsed.source && parsed.repo) {
    return `${base}/${parsed.source}/${parsed.repo}/`;
  }
  return `${base}/`;
}

const LOGO = (name: string) => `${import.meta.env.BASE_URL}logos/workflows/${name}`;

const BrandImg: React.FC<{ src: string; alt: string; size?: number }> = ({
  src,
  alt,
  size = 22,
}) => (
  <img
    src={src}
    alt={alt}
    width={size}
    height={size}
    style={{ objectFit: 'contain', display: 'block' }}
  />
);

const NfCoreLogo: React.FC<{ size?: number }> = ({ size = 22 }) => (
  <BrandImg src={LOGO('nf-core.png')} alt="nf-core" size={size} />
);
const SnakemakeLogo: React.FC<{ size?: number }> = ({ size = 22 }) => (
  <BrandImg src={LOGO('snakemake.svg')} alt="Snakemake" size={size} />
);
const GalaxyLogo: React.FC<{ size?: number }> = ({ size = 22 }) => (
  <BrandImg src={LOGO('galaxy.png')} alt="Galaxy" size={size} />
);
const IwcLogo: React.FC<{ size?: number }> = ({ size = 22 }) => (
  <BrandImg src={LOGO('iwc.png')} alt="IWC" size={size} />
);

interface SourceMeta {
  color: string;
  Logo?: React.FC<{ size?: number }>;
  initials?: string;
}

/** Registry of well-known template sources. New sources slot in here and
 *  inherit the chip rendering. The chip's homepage link points to the
 *  depictio-docs page for the template (see ``templateDocsUrl``). */
const TEMPLATE_SOURCES: Record<string, SourceMeta> = {
  'nf-core': { color: 'green', Logo: NfCoreLogo, initials: 'NF' },
  'snakemake-workflows': { color: 'blue', Logo: SnakemakeLogo, initials: 'SW' },
  galaxy: { color: 'orange', Logo: GalaxyLogo, initials: 'GX' },
  iwc: { color: 'grape', Logo: IwcLogo, initials: 'IW' },
  bioconda: { color: 'teal', initials: 'BC' },
  depictio: { color: 'grape', initials: 'DE' },
};

function sourceMeta(source: string): SourceMeta {
  return (
    TEMPLATE_SOURCES[source.toLowerCase()] || {
      color: 'gray',
      initials: source.replace(/[^a-zA-Z0-9]/g, '').slice(0, 2).toUpperCase() || '??',
    }
  );
}

/** Shared chip that renders a template's brand mark (or letter fallback) +
 *  version pill, wrapped in an anchor pointing to the depictio-docs page for
 *  that template. The Anchor stops click propagation so opening the link
 *  doesn't toggle a surrounding accordion. */
export const TemplateChip: React.FC<{
  parsed: ParsedTemplate;
  /** Verbose mode renders the source/repo text alongside the chip. */
  verbose?: boolean;
}> = ({ parsed, verbose }) => {
  const meta = sourceMeta(parsed.source);
  const Logo = meta.Logo;
  const docsUrl = templateDocsUrl(parsed);
  const tooltipLabel = (
    <Stack gap={2}>
      <Text size="xs" fw={600}>
        Template
      </Text>
      <Text size="xs" ff="monospace">
        {parsed.full}
      </Text>
      <Text size="xs" c="dimmed">
        Open Depictio docs
      </Text>
    </Stack>
  );

  const chip = (
    <Group gap={4} wrap="nowrap" style={{ flexShrink: 0 }}>
      {Logo ? (
        <Box
          w={22}
          h={22}
          style={{
            borderRadius: '50%',
            overflow: 'hidden',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <Logo size={22} />
        </Box>
      ) : (
        <Avatar
          size={22}
          radius="xl"
          color={meta.color}
          variant="filled"
          style={{ fontSize: 10, fontWeight: 700 }}
        >
          {meta.initials}
        </Avatar>
      )}
      {parsed.version && (
        <Badge
          color={meta.color}
          variant="light"
          size="xs"
          radius="sm"
          style={{ textTransform: 'none', fontWeight: 600 }}
        >
          v{parsed.version.replace(/^v/i, '')}
        </Badge>
      )}
      {verbose && (
        <Text size="xs" c="dimmed" ff="monospace" truncate>
          {parsed.repo ? `${parsed.source}/${parsed.repo}` : parsed.source}
        </Text>
      )}
    </Group>
  );

  return (
    <Tooltip
      label={tooltipLabel}
      withArrow
      position="top"
      withinPortal
      // Delays let the cursor traverse from the chip to nearby UI without
      // the tooltip thrashing; closeDelay > openDelay means the tip stays
      // around long enough to read after a quick hover. The tooltip itself
      // doesn't intercept clicks (events=false) — clicks always reach the
      // underlying Anchor.
      openDelay={150}
      closeDelay={120}
      events={{ hover: true, focus: true, touch: false }}
    >
      <Anchor
        href={docsUrl}
        target="_blank"
        rel="noreferrer"
        underline="never"
        onClick={(e) => e.stopPropagation()}
        style={{ display: 'inline-flex', alignItems: 'center' }}
      >
        {chip}
      </Anchor>
    </Tooltip>
  );
};
