/**
 * Shared bits for the catalog-preview bundle's two views (Gallery + OutputView):
 * the component-type badge palette and a couple of small presentational helpers.
 * Kept in one place so the gallery grid and the detail page stay visually in sync.
 */
import React from 'react';
import { ActionIcon, Anchor, Avatar, Badge, Box, Button, CopyButton, Group, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';
import logoRaw from '../../public/logos/logo_black.svg?raw';
import logoWhiteRaw from '../../public/logos/logo_white.svg?raw';

/** depictio logo as inline data URIs (shared by the gallery + detail headers).
 *  Pick `LOGO_WHITE_SRC` on dark surfaces so the wordmark stays legible. */
export const LOGO_SRC = `data:image/svg+xml;utf8,${encodeURIComponent(logoRaw)}`;
export const LOGO_WHITE_SRC = `data:image/svg+xml;utf8,${encodeURIComponent(logoWhiteRaw)}`;
export const logoFor = (theme?: string) => (theme === 'dark' ? LOGO_WHITE_SRC : LOGO_SRC);

/** The catalog's section accent — one constant so the gallery + detail agree
 *  (Projects uses teal; each app/section gets its own flat Mantine color). */
export const CATALOG_ACCENT = 'violet';

/** Component type → badge style, mirrored from depictio/dash/component_metadata.py
 *  (colors/icons kept in sync by hand to stay Dash-free). */
export const COMPONENT_META: Record<string, { name: string; color: string; icon: string }> = {
  figure: { name: 'Figure', color: '#9966cc', icon: 'mdi:graph-box' },
  card: { name: 'Card', color: '#45b8ac', icon: 'formkit:number' },
  interactive: { name: 'Interactive', color: '#8bc34a', icon: 'bx:slider-alt' },
  table: { name: 'Table', color: '#6495ed', icon: 'octicon:table-24' },
  advanced_viz: { name: 'Advanced viz', color: '#f68b33', icon: 'mdi:chart-scatter-plot' },
  multiqc: { name: 'MultiQC', color: '#f68b33', icon: 'mdi:chart-line' },
  map: { name: 'Map', color: '#7a5dc7', icon: 'mdi:map-marker-multiple' },
  image: { name: 'Image', color: '#e6779f', icon: 'mdi:image-area' },
  text: { name: 'Text', color: '#e6779f', icon: 'mdi:text-box-edit' },
};

export const metaFor = (t: string) =>
  COMPONENT_META[t] || { name: t, color: '#868e96', icon: 'mdi:shape-outline' };

// --- Tool identity avatar (curated logo, else Gmail-style letter monogram) ---

// Deterministic Mantine palette color so a tool's monogram is stable across renders.
const MONOGRAM_COLORS = ['violet', 'teal', 'blue', 'grape', 'cyan', 'indigo', 'pink', 'green'];
const colorForTool = (id: string): string => {
  let h = 0;
  for (let i = 0; i < id.length; i += 1) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  return MONOGRAM_COLORS[h % MONOGRAM_COLORS.length];
};

/** Square tool-identity tile: the tool's curated logo when one is set, otherwise
 *  a Gmail-style colored letter monogram (Mantine `Avatar`'s built-in fallback).
 *  No derived favicons / GitHub OG cards — a tool either has a real logo or a
 *  clean monogram. Used as the gallery section thumbnail. */
export const ToolLogo: React.FC<{
  tool: { id: string; name?: string; logo?: string | null };
  size?: number;
}> = ({ tool, size = 40 }) => {
  const initial = (tool.name || tool.id || '?').trim().charAt(0).toUpperCase() || '?';
  return (
    <Avatar
      src={tool.logo || undefined}
      alt={tool.name || tool.id}
      size={size}
      radius="md"
      color={colorForTool(tool.id)}
      style={{ flexShrink: 0 }}
    >
      {initial}
    </Avatar>
  );
};

/** Colored depictio-style component-type badge. */
export const TypeBadge: React.FC<{ type: string; size?: string }> = ({ type, size = 'sm' }) => {
  const meta = metaFor(type);
  return (
    <Badge
      color={meta.color}
      variant="light"
      radius="sm"
      size={size}
      leftSection={<Icon icon={meta.icon} width={13} />}
    >
      {meta.name}
    </Badge>
  );
};

export const DEFAULT_HEIGHT: Record<string, number> = {
  figure: 540,
  map: 480,
  advanced_viz: 480,
  multiqc: 480,
  image: 480,
  table: 520,
};

export const InfoRow: React.FC<{ label: string; children: React.ReactNode; align?: string }> = ({
  label,
  children,
  align = 'baseline',
}) => (
  <Group gap="xs" wrap="nowrap" align={align}>
    <Text size="xs" fw={700} c="dimmed" style={{ minWidth: 92 }}>
      {label}
    </Text>
    <Box style={{ minWidth: 0 }}>{children}</Box>
  </Group>
);

/** External link showing its real destination: icon + readable label, full URL on hover. */
export const IdentityLink: React.FC<{ href: string; icon: string; label: string }> = ({
  href,
  icon,
  label,
}) => (
  <Anchor href={href} target="_blank" rel="noreferrer" size="xs" title={href}>
    <Group gap={4} wrap="nowrap" component="span" display="inline-flex">
      <Icon icon={icon} width={13} />
      <Text span>{label}</Text>
      <Icon icon="mdi:open-in-new" width={11} />
    </Group>
  </Anchor>
);

/** Copy-to-clipboard control for a YAML snippet (idle → copied tick).
 *  `icon` shows a subtle ActionIcon; `button` shows a labelled Button. */
export const CopyYaml: React.FC<{
  yaml: string;
  label: string;
  variant?: 'icon' | 'button';
  buttonVariant?: string;
}> = ({ yaml, label, variant = 'icon', buttonVariant = 'light' }) => (
  <CopyButton value={yaml} timeout={1500}>
    {({ copied, copy }) =>
      variant === 'button' ? (
        <Button
          size="xs"
          variant={buttonVariant}
          color={copied ? 'teal' : 'gray'}
          leftSection={<Icon icon={copied ? 'mdi:check' : 'mdi:content-copy'} width={14} />}
          onClick={copy}
        >
          {copied ? 'Copied' : label}
        </Button>
      ) : (
        <Tooltip label={copied ? 'Copied' : label} withArrow>
          <ActionIcon
            variant="subtle"
            color={copied ? 'teal' : 'gray'}
            onClick={(e) => {
              e.stopPropagation();
              copy();
            }}
          >
            <Icon icon={copied ? 'mdi:check' : 'mdi:content-copy'} width={16} />
          </ActionIcon>
        </Tooltip>
      )
    }
  </CopyButton>
);

export const edamShort = (url: string) => url.replace('http://edamontology.org/', '');
export const lastSeg = (url: string) => url.replace(/\/+$/, '').split('/').pop() || url;
/** Readable nf-core destination: the module path after `/modules/nf-core/`. */
export const nfCoreLabel = (url: string) => {
  const m = url.match(/modules\/nf-core\/(.+?)\/?$/);
  return m ? `nf-core/modules: ${m[1]}` : url.replace(/^https?:\/\//, '');
};

export interface OutputInfo {
  id: string;
  description?: string;
  mode?: string | null;
  find?: Record<string, unknown>;
  recipe?: string | null;
  fixture?: string | null;
  nf_core_url?: string | null;
  biotools_url?: string | null;
  edam?: string[];
  n_rows?: number;
  n_cols?: number;
  columns?: string[];
}

export interface FixturePreview {
  columns: string[];
  rows: Record<string, unknown>[];
  total: number;
}

export interface OutputEntry {
  output: OutputInfo;
  fixturePreview?: FixturePreview | null;
  renders: Record<string, unknown>[];
  ok: boolean;
  error?: string;
}

export interface ToolEntry {
  id: string;
  name: string;
  description?: string;
  logo?: string | null;
  homepage?: string | null;
  nf_core_url?: string | null;
  biotools_url?: string | null;
  edam_topics?: string[];
  outputs: OutputEntry[];
}

export interface CatalogGlobal {
  theme?: 'light' | 'dark';
  initialOutputId?: string | null;
  /** When set, the viewer skips all catalog chrome and renders only this render. */
  initialRenderId?: string | null;
  tools: ToolEntry[];
  data: unknown;
}

/** A render's copyable `renders_as` YAML, joined across an output's renders. */
export const allRendersYaml = (renders: Record<string, unknown>[]): string =>
  renders
    .map((r) => r._yaml as string | undefined)
    .filter(Boolean)
    .join('\n');
