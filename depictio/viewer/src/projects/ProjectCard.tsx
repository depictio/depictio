import React, { useState } from 'react';
import {
  Accordion,
  Anchor,
  Avatar,
  Badge,
  Box,
  Button,
  Group,
  Stack,
  Text,
  Tooltip,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';

import { exportProjectZip } from 'depictio-react-core';
import type { ProjectListEntry } from 'depictio-react-core';

interface ProjectCardProps {
  project: ProjectListEntry;
  currentUserId: string | null;
  isAdmin: boolean;
  onEdit: (project: ProjectListEntry) => void;
  onDelete: (project: ProjectListEntry) => void;
}

type Role = 'Owner' | 'Editor' | 'Viewer';

/** Determine the user's role on a project. Mirrors `_determine_user_role`
 *  in `depictio/dash/layouts/projects.py:1303`. Owner > Editor > Viewer. */
function determineRole(project: ProjectListEntry, userId: string | null): Role | null {
  if (!userId) return null;
  const perms = project.permissions ?? {};
  const isInList = (list?: Array<{ _id?: string; id?: string }>) =>
    !!list?.some((u) => (u._id ?? u.id) === userId);
  if (isInList(perms.owners)) return 'Owner';
  if (isInList(perms.editors)) return 'Editor';
  if (isInList(perms.viewers)) return 'Viewer';
  return null;
}

const ROLE_COLOR: Record<Role, string> = {
  Owner: 'blue',
  Editor: 'cyan',
  Viewer: 'gray',
};

interface ParsedTemplate {
  /** Original full identifier, e.g. `nf-core/viralrecon/3.0.0` */
  full: string;
  /** First slash-separated segment, e.g. `nf-core` */
  source: string;
  /** Middle segment if present, e.g. `viralrecon` */
  repo: string;
  /** Trailing segment if it looks like a semver, otherwise empty */
  version: string;
}

/** Parse `template_origin.template_id` (e.g. `nf-core/viralrecon/3.0.0`)
 *  into source/repo/version. Backwards-compatible with `template_origin`
 *  passed as a plain string and with shorter ids that omit the version
 *  segment. Returns null when the project wasn't created from a template. */
function parseTemplate(project: ProjectListEntry): ParsedTemplate | null {
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
  // Last segment is treated as the version when it looks numeric/semver.
  const looksVersion = (s: string) => /^v?\d/.test(s);
  let version = '';
  if (parts.length >= 2 && looksVersion(parts[parts.length - 1])) {
    version = parts.pop() || '';
  }
  const source = parts[0] || raw;
  const repo = parts[1] || '';
  return { full: raw, source, repo, version };
}

/** Brand marks for the well-known template sources. The PNG/SVG files come
 *  from the canonical workflow logos already in `depictio/dash/assets/images/
 *  workflows/` (mirrored into `depictio/viewer/public/logos/workflows/` so
 *  Vite copies them into the bundle). FastAPI serves them at
 *  `/dashboard-beta/logos/workflows/<name>.png`; we resolve via Vite's
 *  base URL to stay correct under any deployment prefix. */
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
  /** Mantine color name for the version pill */
  color: string;
  /** Inline SVG component for the avatar slot — undefined → letter fallback */
  Logo?: React.FC<{ size?: number }>;
  /** Two-letter fallback for the avatar when no Logo is registered */
  initials?: string;
  /** Build a homepage URL from the parsed template (clickable chip) */
  homepage?: (parsed: ParsedTemplate) => string;
}

/** Registry of well-known template sources. New sources slot in here and
 *  inherit the chip rendering — no changes to ProjectCard needed. */
const TEMPLATE_SOURCES: Record<string, SourceMeta> = {
  'nf-core': {
    color: 'green',
    Logo: NfCoreLogo,
    initials: 'NF',
    homepage: (t) =>
      t.repo
        ? `https://nf-co.re/${t.repo}` + (t.version ? `/${t.version.replace(/^v/i, '')}` : '')
        : 'https://nf-co.re/',
  },
  'snakemake-workflows': {
    color: 'blue',
    Logo: SnakemakeLogo,
    initials: 'SW',
    homepage: (t) =>
      t.repo
        ? `https://github.com/snakemake-workflows/${t.repo}`
        : 'https://github.com/snakemake-workflows',
  },
  galaxy: {
    color: 'orange',
    Logo: GalaxyLogo,
    initials: 'GX',
    homepage: () => 'https://galaxyproject.org/',
  },
  iwc: {
    color: 'grape',
    Logo: IwcLogo,
    initials: 'IW',
    homepage: () => 'https://iwc.galaxyproject.org/',
  },
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

/** Shared chip that renders a template's brand mark (or letter fallback)
 *  + version pill, optionally wrapped in a homepage link. Used in both the
 *  project row header and the inline Details panel. The Anchor stops click
 *  propagation so opening the link doesn't toggle the accordion. */
const TemplateChip: React.FC<{
  parsed: ParsedTemplate;
  /** Verbose mode renders the source/repo text alongside the chip. */
  verbose?: boolean;
}> = ({ parsed, verbose }) => {
  const meta = sourceMeta(parsed.source);
  const Logo = meta.Logo;
  const homepage = meta.homepage?.(parsed);
  const tooltipLabel = (
    <Stack gap={2}>
      <Text size="xs" fw={600}>
        Template
      </Text>
      <Text size="xs" ff="monospace">
        {parsed.full}
      </Text>
      {homepage && (
        <Text size="xs" c="dimmed">
          Click to open homepage
        </Text>
      )}
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
    <Tooltip label={tooltipLabel} withArrow position="top">
      {homepage ? (
        <Anchor
          href={homepage}
          target="_blank"
          rel="noreferrer"
          underline="never"
          // Stop the click from bubbling to the Accordion.Control so opening
          // the homepage doesn't also toggle the row.
          onClick={(e) => e.stopPropagation()}
        >
          {chip}
        </Anchor>
      ) : (
        chip
      )}
    </Tooltip>
  );
};

const ProjectCard: React.FC<ProjectCardProps> = ({
  project,
  currentUserId,
  isAdmin,
  onEdit,
  onDelete,
}) => {
  const projectId = (project._id ?? project.id) as string;
  const isAdvanced = project.project_type === 'advanced';
  const isPublic = Boolean(project.is_public);
  const role = determineRole(project, currentUserId);
  const tmpl = parseTemplate(project);
  const canMutate = role === 'Owner' || isAdmin;
  const [exporting, setExporting] = useState(false);

  const handleExport = async () => {
    setExporting(true);
    try {
      await exportProjectZip(projectId);
      notifications.show({
        color: 'teal',
        title: 'Export started',
        message: `depictio_export_${projectId}.zip is downloading.`,
        autoClose: 2500,
      });
    } catch (err) {
      notifications.show({
        color: 'red',
        title: 'Export failed',
        message: (err as Error).message,
      });
    } finally {
      setExporting(false);
    }
  };

  return (
    <Accordion.Item value={projectId}>
      <Accordion.Control>
        <Group gap="sm" wrap="nowrap" align="center">
          {/* Project Type — light-variant badge (cyan/orange tint).
           *  All three fixed-width slots use textAlign: center so the
           *  badge sits centered under its column header, matching the
           *  Dash visual. */}
          <Box style={{ width: 100, flexShrink: 0, textAlign: 'center' }}>
            <Badge
              color={isAdvanced ? 'orange' : 'cyan'}
              variant="light"
              radius="sm"
              size="sm"
            >
              {isAdvanced ? 'Advanced' : 'Basic'}
            </Badge>
          </Box>

          {/* Visibility — filled green (public) / gray (private) */}
          <Box style={{ width: 80, flexShrink: 0, textAlign: 'center' }}>
            <Badge
              color={isPublic ? 'green' : 'gray'}
              variant="filled"
              radius="sm"
              size="sm"
            >
              {isPublic ? 'Public' : 'Private'}
            </Badge>
          </Box>

          {/* Permission badge — Owner / Editor / Viewer */}
          <Box style={{ width: 80, flexShrink: 0, textAlign: 'center' }}>
            {role && (
              <Badge
                color={ROLE_COLOR[role]}
                variant="filled"
                radius="sm"
                size="sm"
              >
                {role}
              </Badge>
            )}
          </Box>

          {/* Project name + optional template provenance chip. The chip
           *  sits inline before the name so the row keeps the same height
           *  whether or not the project is template-derived. When the
           *  source has a known homepage, the chip becomes a link. */}
          <Group gap="xs" wrap="nowrap" style={{ flex: 1, minWidth: 0 }}>
            {tmpl && <TemplateChip parsed={tmpl} />}
            <Text fw={600} size="sm" truncate style={{ flex: 1 }}>
              {project.name}
            </Text>
          </Group>
        </Group>
      </Accordion.Control>
      <Accordion.Panel>
        <Stack gap="xs">
          <Accordion variant="contained" radius="md" multiple>
            <Accordion.Item value="details">
              <Accordion.Control
                icon={
                  <Icon
                    icon="mdi:information-outline"
                    width={20}
                    color="var(--mantine-color-gray-6)"
                  />
                }
              >
                <Text fw={500}>Details</Text>
              </Accordion.Control>
              <Accordion.Panel>
                <ProjectDetailsPanel project={project} parsedTemplate={tmpl} />
              </Accordion.Panel>
            </Accordion.Item>

            <Accordion.Item value="data-collections">
              <Accordion.Control
                icon={
                  <Icon
                    icon="mdi:database-outline"
                    width={20}
                    color="var(--mantine-color-cyan-6)"
                  />
                }
              >
                <Group justify="space-between" wrap="nowrap" pr="md">
                  <Text fw={500}>Workflows & Data</Text>
                  <Anchor
                    component="a"
                    href={`/projects-beta/${projectId}`}
                    size="sm"
                    onClick={(e) => e.stopPropagation()}
                  >
                    Open manager →
                  </Anchor>
                </Group>
              </Accordion.Control>
              <Accordion.Panel>
                <Text size="sm" c="dimmed">
                  Open the project's manager to browse workflows, add, rename,
                  preview, or remove data collections.
                </Text>
              </Accordion.Panel>
            </Accordion.Item>

            <Accordion.Item value="permissions">
              <Accordion.Control
                icon={
                  <Icon
                    icon="mdi:shield-account-outline"
                    width={20}
                    color="var(--mantine-color-blue-6)"
                  />
                }
              >
                <Group justify="space-between" wrap="nowrap" pr="md">
                  <Text fw={500}>Roles and permissions</Text>
                  <Anchor
                    component="a"
                    href={`/projects-beta/${projectId}/permissions`}
                    size="sm"
                    onClick={(e) => e.stopPropagation()}
                  >
                    Manage →
                  </Anchor>
                </Group>
              </Accordion.Control>
              <Accordion.Panel>
                <PermissionsSummary project={project} />
              </Accordion.Panel>
            </Accordion.Item>

            <Accordion.Item value="management">
              <Accordion.Control
                icon={
                  <Icon
                    icon="mdi:cog-outline"
                    width={20}
                    color="var(--mantine-color-gray-7)"
                  />
                }
              >
                <Text fw={500}>Management</Text>
              </Accordion.Control>
              <Accordion.Panel>
                <Group gap="sm" wrap="wrap">
                  <Button
                    variant="light"
                    color="blue"
                    size="sm"
                    leftSection={<Icon icon="mdi:pencil" width={16} />}
                    disabled={!canMutate}
                    onClick={() => onEdit(project)}
                  >
                    Edit
                  </Button>
                  <Button
                    variant="light"
                    color="teal"
                    size="sm"
                    leftSection={<Icon icon="mdi:export" width={16} />}
                    onClick={handleExport}
                    loading={exporting}
                  >
                    Export
                  </Button>
                  <Button
                    variant="light"
                    color="red"
                    size="sm"
                    leftSection={<Icon icon="mdi:delete" width={16} />}
                    disabled={!canMutate}
                    onClick={() => onDelete(project)}
                  >
                    Delete
                  </Button>
                  {!canMutate && (
                    <Text size="xs" c="dimmed">
                      You need owner permission to edit or delete this project.
                    </Text>
                  )}
                </Group>
              </Accordion.Panel>
            </Accordion.Item>
          </Accordion>
        </Stack>
      </Accordion.Panel>
    </Accordion.Item>
  );
};

const ProjectDetailsPanel: React.FC<{
  project: ProjectListEntry;
  parsedTemplate: ParsedTemplate | null;
}> = ({ project, parsedTemplate }) => {
  const projectId = (project._id ?? project.id) as string;
  const description =
    typeof project.description === 'string' ? project.description : null;
  const dmpUrl =
    typeof project.data_management_platform_project_url === 'string'
      ? project.data_management_platform_project_url
      : null;
  const created = typeof project.registration_time === 'string'
    ? project.registration_time
    : null;
  const owners = (project.permissions?.owners ?? []) as Array<{
    email?: string;
    _id?: string;
    id?: string;
  }>;

  return (
    <Stack gap={6}>
      <DetailRow label="Name" value={project.name} />
      <DetailRow label="Database ID" value={projectId} mono />
      <DetailRow label="Description" value={description || 'Not defined'} />
      <DetailRow
        label="Data Management Platform URL"
        value={dmpUrl || 'Not defined'}
        link={dmpUrl || undefined}
      />
      <DetailRow label="Created at" value={created || 'Unknown'} />
      {parsedTemplate && (
        <Group gap="xs" align="center">
          <Text size="sm" fw={600} miw={140}>
            Template:
          </Text>
          <TemplateChip parsed={parsedTemplate} verbose />
        </Group>
      )}
      <DetailRow
        label="Owners"
        value={
          owners.length === 0
            ? 'None'
            : owners
                .map((u) => `${u.email || ''} - ${u._id ?? u.id ?? ''}`.trim())
                .join(', ')
        }
      />
      <Group gap="xs">
        <Text size="sm" fw={600}>
          Is public:
        </Text>
        <Badge
          color={project.is_public ? 'green' : 'gray'}
          variant={project.is_public ? 'filled' : 'light'}
          radius="sm"
          size="sm"
        >
          {project.is_public ? 'Public' : 'Private'}
        </Badge>
      </Group>
      <Group gap="xs">
        <Text size="sm" fw={600}>
          Project type:
        </Text>
        <Badge
          color={project.project_type === 'advanced' ? 'orange' : 'cyan'}
          variant="light"
          radius="sm"
          size="sm"
        >
          {project.project_type === 'advanced' ? 'Advanced' : 'Basic'}
        </Badge>
      </Group>
    </Stack>
  );
};

const DetailRow: React.FC<{
  label: string;
  value: string;
  mono?: boolean;
  link?: string;
}> = ({ label, value, mono, link }) => (
  <Group gap="xs" wrap="nowrap" align="baseline">
    <Text size="sm" fw={600} miw={140}>
      {label}:
    </Text>
    {link ? (
      <Anchor href={link} target="_blank" rel="noreferrer" size="sm">
        {value}
      </Anchor>
    ) : (
      <Text
        size="sm"
        style={mono ? { fontFamily: 'monospace' } : undefined}
      >
        {value}
      </Text>
    )}
  </Group>
);

const PermissionsSummary: React.FC<{ project: ProjectListEntry }> = ({ project }) => {
  const fmt = (list?: Array<{ email?: string; _id?: string; id?: string }>) =>
    !list || list.length === 0
      ? 'None'
      : list.map((u) => u.email || u._id || u.id || '').filter(Boolean).join(', ');
  return (
    <Stack gap={4}>
      <DetailRow label="Owners" value={fmt(project.permissions?.owners)} />
      <DetailRow label="Editors" value={fmt(project.permissions?.editors)} />
      <DetailRow label="Viewers" value={fmt(project.permissions?.viewers)} />
    </Stack>
  );
};

export default ProjectCard;
