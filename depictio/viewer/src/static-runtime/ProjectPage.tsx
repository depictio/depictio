/**
 * The project page of a static bundle: what can be known about the dashboard's
 * project without a server.
 *
 * A bundle has no `/projects/<id>` route. Every link the live app has to the
 * project (the Settings drawer's project link, the sidebar's project row) opens
 * this page instead, drawn over the canvas like the Guide: the sidebar, the top
 * bar and the tab stay where they are, and "Back to <tab>" (or Esc) returns.
 *
 * Read-only and offline by construction: it reads `manifest.project` (built by
 * producer A from an allow-list of the project document), the bundled tables'
 * `data_refs` and the export provenance. The live project page's own pieces
 * are reused where they need no server — the connections map, the run
 * parameters card, the template chip, the data-collection type icon — and the
 * rest is plain Mantine in the page language of the Guide.
 */
import React, { useEffect, useMemo, useRef } from 'react';
import {
  ActionIcon,
  Anchor,
  Badge,
  Box,
  Button,
  Container,
  Group,
  Paper,
  SimpleGrid,
  Stack,
  Table,
  Text,
  ThemeIcon,
  Title,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { parseTemplateOrigin, readTemplateRevision, useChromeStyle } from 'depictio-react-core';
import type { DCLink, LinkResolverName, LinkTargetType } from 'depictio-react-core';
import type { BundleManifest, ProjectSummary } from 'depictio-static-core';

import { useCanvasBox } from '../guide';
import { DcTypeIcon } from '../projects/dcTypeIcon';
import { TemplateChip, engineLabel } from '../projects/template';
import ConnectionsMap from '../projects/detail/ConnectionsMap';
import type { ProjectJoin } from '../projects/detail/ConnectionsMap';
import RunProvenanceCard from '../projects/detail/RunProvenanceCard';
import { groupRunProvenance } from '../chrome/DashboardInfoBody';
import { formatExportedAt, provenanceRows } from '../chrome/StaticProvenance';
import { rawBundle } from './bundle';
import {
  collectionRows,
  collectionTotals,
  formatCount,
  type CollectionPresence,
  type CollectionRow,
} from './projectModel';

const PRESENCE: Record<
  CollectionPresence,
  { label: string; color: string; icon: string; hint: string }
> = {
  bundled: {
    label: 'In this file',
    color: 'teal',
    icon: 'mdi:database-check-outline',
    hint: 'The table travels with the file: filters and live views recompute from it.',
  },
  snapshot: {
    label: 'Snapshots',
    color: 'blue',
    icon: 'mdi:camera-outline',
    hint: 'Its views were frozen at export; the table itself is not in the file.',
  },
  absent: {
    label: 'Not included',
    color: 'gray',
    icon: 'mdi:database-off-outline',
    hint: 'Part of the project; no view of this dashboard reads it.',
  },
};

/** One section of the page, framed like a Guide part. */
const Section: React.FC<{
  id: string;
  icon: string;
  title: string;
  subtitle?: React.ReactNode;
  aside?: React.ReactNode;
  children: React.ReactNode;
}> = ({ id, icon, title, subtitle, aside, children }) => (
  <Paper
    component="section"
    withBorder
    radius="lg"
    p={{ base: 'md', sm: 'lg' }}
    aria-labelledby={`bundle-project-${id}-title`}
    data-testid={`bundle-project-${id}`}
  >
    <Stack gap="md">
      <Group justify="space-between" align="flex-start" wrap="wrap" gap="sm">
        <Group gap="sm" wrap="nowrap" align="flex-start" style={{ minWidth: 0, flex: '1 1 260px' }}>
          <ThemeIcon size={36} radius="md" variant="light" style={{ flexShrink: 0 }}>
            <Icon icon={icon} width={20} height={20} />
          </ThemeIcon>
          <Box style={{ minWidth: 0 }}>
            <Title order={2} size="h4" id={`bundle-project-${id}-title`} lh={1.25}>
              {title}
            </Title>
            {subtitle && (
              <Text size="sm" c="dimmed" lh={1.4}>
                {subtitle}
              </Text>
            )}
          </Box>
        </Group>
        {aside}
      </Group>
      {children}
    </Stack>
  </Paper>
);

/** A headline number of the page head. */
const Stat: React.FC<{ label: string; value: string; note?: string }> = ({ label, value, note }) => (
  <Paper withBorder radius="md" p="sm">
    <Text size="xs" c="dimmed" tt="uppercase" fw={700} style={{ letterSpacing: '0.04em' }}>
      {label}
    </Text>
    <Text size="xl" fw={700} lh={1.2}>
      {value}
    </Text>
    {note && (
      <Text size="xs" c="dimmed">
        {note}
      </Text>
    )}
  </Paper>
);

const ColumnsNote: React.FC<{ row: CollectionRow }> = ({ row }) => {
  if (row.presence !== 'bundled') return null;
  const shown = row.columns.slice(0, 24);
  const label = (
    <Stack gap={2} maw={320}>
      <Text size="xs" fw={600}>
        Columns in this file
      </Text>
      <Text size="xs" style={{ overflowWrap: 'anywhere' }}>
        {shown.join(', ')}
        {row.columns.length > shown.length ? `, … (${row.columns.length - shown.length} more)` : ''}
      </Text>
      <Text size="xs" c="dimmed">
        Only the columns this dashboard reads are exported.
      </Text>
    </Stack>
  );
  return (
    <Tooltip label={label} multiline withArrow withinPortal disabled={row.columns.length === 0}>
      <Text size="sm" style={{ whiteSpace: 'nowrap' }} tabIndex={0}>
        {formatCount(row.rows ?? 0)} rows · {row.columns.length}{' '}
        {row.columns.length === 1 ? 'column' : 'columns'}
      </Text>
    </Tooltip>
  );
};

const CollectionsTable: React.FC<{ rows: CollectionRow[] }> = ({ rows }) => (
  <Table.ScrollContainer minWidth={560} type="native">
    <Table verticalSpacing="xs" highlightOnHover striped={false}>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>Collection</Table.Th>
          <Table.Th>Workflow</Table.Th>
          <Table.Th>In this file</Table.Th>
          <Table.Th>Size</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {rows.map((row) => {
          const presence = PRESENCE[row.presence];
          return (
            <Table.Tr key={row.id} data-presence={row.presence}>
              <Table.Td>
                <Group gap="xs" wrap="nowrap" align="flex-start">
                  <Box pt={2}>
                    <DcTypeIcon type={row.type} size={18} />
                  </Box>
                  <Box style={{ minWidth: 0 }}>
                    <Group gap={6} wrap="wrap">
                      <Text size="sm" fw={600} ff="monospace" style={{ overflowWrap: 'anywhere' }}>
                        {row.tag}
                      </Text>
                      {row.metatype && (
                        <Badge size="xs" variant="light" color="gray" radius="sm" tt="none">
                          {row.metatype}
                        </Badge>
                      )}
                    </Group>
                    {row.description && (
                      <Text size="xs" c="dimmed">
                        {row.description}
                      </Text>
                    )}
                  </Box>
                </Group>
              </Table.Td>
              <Table.Td>
                <Text size="sm" c={row.workflow ? undefined : 'dimmed'}>
                  {row.workflow ?? '—'}
                </Text>
              </Table.Td>
              <Table.Td>
                <Tooltip label={presence.hint} withArrow withinPortal multiline maw={260}>
                  <Badge
                    variant="light"
                    color={presence.color}
                    radius="sm"
                    tt="none"
                    leftSection={<Icon icon={presence.icon} width={12} />}
                  >
                    {presence.label}
                  </Badge>
                </Tooltip>
              </Table.Td>
              <Table.Td>
                {row.presence === 'bundled' ? (
                  <ColumnsNote row={row} />
                ) : (
                  <Text size="sm" c="dimmed">
                    —
                  </Text>
                )}
              </Table.Td>
            </Table.Tr>
          );
        })}
      </Table.Tbody>
    </Table>
  </Table.ScrollContainer>
);

const WorkflowsList: React.FC<{ project: ProjectSummary }> = ({ project }) => (
  <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
    {project.workflows.map((wf) => (
      <Paper key={wf.id} withBorder radius="md" p="sm">
        <Stack gap={4}>
          <Group gap={6} wrap="wrap">
            <Text fw={600}>{wf.name}</Text>
            {wf.version && (
              <Badge size="sm" variant="light" radius="sm" tt="none">
                v{wf.version.replace(/^v/i, '')}
              </Badge>
            )}
            {wf.catalog && (
              <Badge size="sm" variant="outline" color="gray" radius="sm" tt="none">
                {wf.catalog}
              </Badge>
            )}
          </Group>
          {wf.tag && wf.tag !== wf.name && (
            <Text size="xs" c="dimmed" ff="monospace">
              {wf.tag}
            </Text>
          )}
          {wf.engine && (
            <Text size="sm" c="dimmed">
              {engineLabel(wf.engine)}
              {wf.engine_version ? ` ${wf.engine_version}` : ''}
            </Text>
          )}
          {wf.repository_url && (
            <Anchor
              href={wf.repository_url}
              target="_blank"
              rel="noreferrer"
              size="sm"
              style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}
            >
              <Icon icon="mdi:source-repository" width={14} />
              Repository
              <Icon icon="mdi:open-in-new" width={12} />
            </Anchor>
          )}
        </Stack>
      </Paper>
    ))}
  </SimpleGrid>
);

/** A link as the connections map reads it (`DCLink`), without its mappings. */
function asDcLink(link: ProjectSummary['links'][number]): DCLink {
  return {
    id: link.id,
    source_dc_id: link.source_dc_id,
    source_column: link.source_column,
    target_dc_id: link.target_dc_id,
    target_type: link.target_type as LinkTargetType,
    link_config: {
      resolver: link.resolver as LinkResolverName,
      ...(link.target_field ? { target_field: link.target_field } : {}),
    },
    description: link.description ?? null,
    enabled: link.enabled,
  };
}

const LinksTable: React.FC<{ project: ProjectSummary; tagOf: (id: string) => string }> = ({
  project,
  tagOf,
}) => (
  <Table.ScrollContainer minWidth={520} type="native">
    <Table verticalSpacing="xs">
      <Table.Thead>
        <Table.Tr>
          <Table.Th>From</Table.Th>
          <Table.Th>Column</Table.Th>
          <Table.Th>To</Table.Th>
          <Table.Th>How</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {project.links.map((link) => (
          <Table.Tr key={link.id} style={link.enabled ? undefined : { opacity: 0.6 }}>
            <Table.Td ff="monospace">{link.source_dc_tag || tagOf(link.source_dc_id)}</Table.Td>
            <Table.Td>
              <Text size="sm" ff="monospace">
                {link.source_column}
              </Text>
            </Table.Td>
            <Table.Td ff="monospace">{link.target_dc_tag || tagOf(link.target_dc_id)}</Table.Td>
            <Table.Td>
              <Text size="sm">
                {link.resolver}
                {link.enabled ? '' : ' (off)'}
              </Text>
            </Table.Td>
          </Table.Tr>
        ))}
        {project.joins.map((join, i) => (
          <Table.Tr key={`join-${join.name ?? i}`}>
            <Table.Td ff="monospace">{join.left_dc}</Table.Td>
            <Table.Td>
              <Text size="sm" ff="monospace">
                {join.on_columns.join(', ')}
              </Text>
            </Table.Td>
            <Table.Td ff="monospace">{join.right_dc}</Table.Td>
            <Table.Td>
              <Text size="sm">Join{join.how ? `, ${join.how}` : ''}</Text>
            </Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  </Table.ScrollContainer>
);

const ExportFacts: React.FC<{ manifest: BundleManifest; project: ProjectSummary }> = ({
  manifest,
  project,
}) => {
  const rows = provenanceRows(manifest).filter((r) => r.label !== 'Project' && !r.href);
  const liveDashboard = manifest.provenance?.dashboard_url;
  return (
    <Stack gap="sm">
      <Text size="sm">
        This page and the dashboard are a copy taken from a Depictio instance. Nothing here is
        fetched: the numbers are those of the export, and editing, comments and data refreshes
        need the live project.
      </Text>
      <Table withRowBorders={false} verticalSpacing={4} layout="fixed">
        <Table.Tbody>
          {rows.map((row) => (
            <Table.Tr key={row.label}>
              <Table.Td w={120} pl={0}>
                <Text size="sm" c="dimmed">
                  {row.label}
                </Text>
              </Table.Td>
              <Table.Td pl={0}>
                <Text size="sm" style={{ overflowWrap: 'anywhere' }} title={row.hint}>
                  {row.value}
                  {row.hint && row.hint !== row.value ? (
                    <Text span size="xs" c="dimmed">
                      {' '}
                      ({row.hint.replace(/^Producer [A-Z] — /, '')})
                    </Text>
                  ) : null}
                </Text>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      {(project.project_url || liveDashboard || project.external_url) && (
        <Group gap="sm" wrap="wrap">
          {project.project_url && (
            <Button
              component="a"
              href={project.project_url}
              target="_blank"
              rel="noreferrer"
              variant="light"
              size="xs"
              leftSection={<Icon icon="mdi:folder-open-outline" width={14} />}
              rightSection={<Icon icon="mdi:open-in-new" width={12} />}
            >
              Live project
            </Button>
          )}
          {liveDashboard && /^https?:\/\//i.test(liveDashboard) && (
            <Button
              component="a"
              href={liveDashboard}
              target="_blank"
              rel="noreferrer"
              variant="default"
              size="xs"
              leftSection={<Icon icon="mdi:view-dashboard-outline" width={14} />}
              rightSection={<Icon icon="mdi:open-in-new" width={12} />}
            >
              Live dashboard
            </Button>
          )}
          {project.external_url && (
            <Button
              component="a"
              href={project.external_url}
              target="_blank"
              rel="noreferrer"
              variant="default"
              size="xs"
              leftSection={<Icon icon="mdi:link-variant" width={14} />}
              rightSection={<Icon icon="mdi:open-in-new" width={12} />}
            >
              Data platform
            </Button>
          )}
        </Group>
      )}
    </Stack>
  );
};

const ProjectPage: React.FC<{ tabName: string; onClose: () => void }> = ({ tabName, onClose }) => {
  const manifest = rawBundle();
  const project = manifest.project;
  const canvasBox = useCanvasBox();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const isGlass = useChromeStyle().id === 'glass';

  // Arriving on the page moves focus to its title, as the Guide does.
  useEffect(() => {
    headingRef.current?.focus({ preventScroll: true });
  }, []);

  // Esc returns to the tab, unless a menu, dialog or list is what Esc is for.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      // Visible ones only: the Settings dialog stays mounted once opened.
      const above = document.querySelectorAll('[role="dialog"], [role="menu"], [role="listbox"]');
      if (Array.from(above).some((el) => el.getClientRects().length > 0)) return;
      onClose();
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [onClose]);

  const rows = useMemo(() => collectionRows(manifest), [manifest]);
  const totals = collectionTotals(rows);
  const tagOf = useMemo(() => {
    const byId = new Map(rows.map((r) => [r.id, r.tag]));
    return (id: string) => byId.get(id) ?? id;
  }, [rows]);
  const paramGroups = useMemo(
    () => groupRunProvenance(project?.run_parameters ?? []),
    [project],
  );
  if (!project) return null;

  const templateOrigin = project.template
    ? {
        template_id: project.template.template_id,
        template_version: project.template.template_version,
        applied_at: project.template.applied_at,
      }
    : null;
  const template = parseTemplateOrigin(templateOrigin);
  const revision = readTemplateRevision(templateOrigin);
  const exportedAt = formatExportedAt(manifest.provenance?.exported_at ?? manifest.built_at);
  const highlights = project.run_parameters.filter((p) => p.highlight).length;
  const connectionCount = project.links.length + project.joins.length;

  return (
    <div
      className="depictio-guide-layer dc-bundle-project"
      role="region"
      aria-labelledby="bundle-project-heading"
      data-testid="bundle-project-page"
      style={
        canvasBox
          ? {
              top: canvasBox.top,
              left: canvasBox.left,
              width: canvasBox.width,
              height: canvasBox.height,
              right: 'auto',
              bottom: 'auto',
              transition: 'none',
            }
          : undefined
      }
    >
      <Container size={960} px={{ base: 'md', sm: 'xl' }} py={{ base: 'lg', sm: 'xl' }}>
        <Stack gap="lg">
          <Group justify="space-between" align="flex-start" wrap="nowrap" gap="md">
            <Group gap="md" wrap="nowrap" align="flex-start" style={{ minWidth: 0 }}>
              <ThemeIcon size={48} radius="md" variant="light" style={{ flexShrink: 0 }}>
                <Icon icon="mdi:folder-outline" width={28} height={28} />
              </ThemeIcon>
              <Box style={{ minWidth: 0 }}>
                <Text
                  size="xs"
                  c="dimmed"
                  tt="uppercase"
                  fw={700}
                  style={{ letterSpacing: '0.06em' }}
                >
                  Project
                </Text>
                <Title
                  order={1}
                  size="h2"
                  id="bundle-project-heading"
                  ref={headingRef}
                  tabIndex={-1}
                  style={{ outline: 'none', overflowWrap: 'anywhere' }}
                  lh={1.2}
                >
                  {project.name}
                </Title>
                {project.description && (
                  <Text c="dimmed" size="sm" lh={1.45} mt={2}>
                    {project.description}
                  </Text>
                )}
                <Group gap="xs" mt="xs" wrap="wrap">
                  {template && <TemplateChip parsed={template} verbose />}
                  {revision && (
                    <Text size="xs" c="dimmed">
                      template revision v{revision.version}
                    </Text>
                  )}
                  <Badge
                    variant="light"
                    color="gray"
                    radius="sm"
                    tt="none"
                    leftSection={<Icon icon="mdi:package-variant-closed" width={12} />}
                  >
                    Static snapshot{exportedAt ? ` · ${exportedAt}` : ''}
                  </Badge>
                </Group>
              </Box>
            </Group>
            <Button
              variant="default"
              size="xs"
              leftSection={<Icon icon="mdi:arrow-left" width={14} />}
              onClick={onClose}
              visibleFrom="sm"
              style={{ flexShrink: 0 }}
              data-testid="bundle-project-close"
            >
              Back to {tabName}
            </Button>
            <ActionIcon
              variant="default"
              size="lg"
              onClick={onClose}
              hiddenFrom="sm"
              aria-label={`Back to ${tabName}`}
              style={{ flexShrink: 0 }}
            >
              <Icon icon="mdi:close" width={18} />
            </ActionIcon>
          </Group>

          <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="sm" data-testid="bundle-project-stats">
            <Stat
              label="Collections"
              value={formatCount(totals.total)}
              note={`${totals.bundled} in this file`}
            />
            <Stat
              label="Rows in this file"
              value={formatCount(totals.rows)}
              note={totals.bundled === 1 ? 'one table' : `${totals.bundled} tables`}
            />
            <Stat
              label="Workflows"
              value={formatCount(project.workflows.length)}
              note={project.workflows[0]?.name}
            />
            <Stat
              label="Connections"
              value={formatCount(connectionCount)}
              note={connectionCount ? 'links and joins' : 'none declared'}
            />
          </SimpleGrid>

          <Section
            id="collections"
            icon="mdi:database-outline"
            title="Data collections"
            subtitle="What the project holds, and what of it travels with this file."
          >
            {rows.length > 0 ? (
              <CollectionsTable rows={rows} />
            ) : (
              <Text size="sm" c="dimmed">
                The export recorded no data collections.
              </Text>
            )}
          </Section>

          {project.workflows.length > 0 && (
            <Section
              id="workflows"
              icon="mdi:sitemap-outline"
              title="Workflows"
              subtitle="The pipelines whose outputs the collections were read from."
            >
              <WorkflowsList project={project} />
            </Section>
          )}

          {connectionCount > 0 && (
            <Section
              id="links"
              icon="mdi:link-variant"
              title="Links between collections"
              subtitle="A filter on one collection reaches the collections it links to."
            >
              {isGlass ? (
                <ConnectionsMap
                  dataCollections={rows.map((r) => ({ id: r.id, tag: r.tag, type: r.type }))}
                  links={project.links.map(asDcLink)}
                  joins={project.joins as ProjectJoin[]}
                  canMutate={false}
                />
              ) : (
                <LinksTable project={project} tagOf={tagOf} />
              )}
            </Section>
          )}

          {project.run_parameters.length > 0 && (
            <Section
              id="params"
              icon="mdi:tune-variant"
              title="Run parameters"
              subtitle={
                highlights > 0
                  ? `${highlights} key settings among ${project.run_parameters.length} recorded.`
                  : `${project.run_parameters.length} recorded with the run.`
              }
            >
              <RunProvenanceCard
                groups={paramGroups}
                files={project.run_parameter_files}
                withCard={false}
                withHeading={false}
              />
              <Text size="xs" c="dimmed">
                Paths keep their last part only, and values of keys that look like credentials are
                withheld from exports.
              </Text>
            </Section>
          )}

          <Section
            id="export"
            icon="mdi:package-variant-closed"
            title="About this copy"
            subtitle="Where and when this file was exported."
          >
            <ExportFacts manifest={manifest} project={project} />
          </Section>
        </Stack>
      </Container>
    </div>
  );
};

export default ProjectPage;
