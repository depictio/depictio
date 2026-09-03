import React, { useEffect, useMemo, useState } from 'react';
import {
  Accordion,
  Anchor,
  Badge,
  Code,
  CopyButton,
  Divider,
  Group,
  Modal,
  ScrollArea,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
  Tooltip,
  ActionIcon,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import type { DashboardData } from 'depictio-react-core';
import { fetchProject } from 'depictio-react-core';
import { AI_COLOR, AI_ICON } from 'depictio-react-ai';
import { parseTemplateOrigin, TemplateChip } from '../projects/template';
import RunProvenanceCard from '../projects/detail/RunProvenanceCard';
import { formatDateTime } from '../lib/datetime';
import {
  isUnsetProvenanceValue,
  matchesProvenanceQuery,
  type ProvenanceEntryLike,
} from '../lib/provenance';

interface DashboardInfoBodyProps {
  dashboard: DashboardData | null;
  /** False while the host surface is hidden, which skips the project fetch. */
  active?: boolean;
}

/** "yyyy-mm-dd HH:MM" in the viewer's local timezone — same format the
 *  dashboards list uses. */
function formatTimestamp(raw: string): string {
  return formatDateTime(raw, raw);
}

/** Pull the first owner's email from a permissions blob, regardless of
 *  exact shape (server uses ``permissions.owners[].email``). */
function pickOwnerEmail(dashboard: DashboardData | null): string | null {
  const perms = dashboard?.permissions as { owners?: Array<{ email?: string }> } | undefined;
  return perms?.owners?.[0]?.email ?? null;
}

/**
 * Read-only metadata about the current dashboard: the same fields the
 * dashboards list shows (project, owner, visibility, modified date) plus the
 * dashboard / project IDs.
 *
 * Surface-agnostic. `SettingsDrawer` renders it in a right-hand drawer; the
 * inspector's Info tab renders it docked whenever no component is selected.
 */
const DashboardInfoBody: React.FC<DashboardInfoBodyProps> = ({ dashboard, active = true }) => {
  const [projectName, setProjectName] = useState<string | null>(null);
  // Raw template_origin blob from the dashboard's owning project (when
  // instantiated from a template), so we can render a TemplateChip.
  const [projectTemplateOrigin, setProjectTemplateOrigin] = useState<unknown>(null);

  const dashboardId =
    (dashboard?.dashboard_id as string | undefined) ||
    (dashboard?._id as string | undefined) ||
    null;
  const projectId = (dashboard?.project_id as string | undefined) || null;
  const title = (typeof dashboard?.title === 'string' && dashboard.title) || null;
  const subtitle = (typeof dashboard?.subtitle === 'string' && dashboard.subtitle) || null;
  const ownerEmail = pickOwnerEmail(dashboard);
  const isPublic = Boolean(dashboard?.is_public);
  const lastSavedRaw =
    (typeof dashboard?.last_saved_ts === 'string' && dashboard.last_saved_ts) || null;
  const lastSaved = lastSavedRaw ? formatTimestamp(lastSavedRaw) : null;
  const realtimeEnabled = Boolean(
    (dashboard?.project_realtime as { enabled?: boolean } | undefined)?.enabled,
  );
  const isMainTab =
    typeof dashboard?.is_main_tab === 'boolean' ? (dashboard.is_main_tab as boolean) : null;
  const parentDashboardId = (dashboard?.parent_dashboard_id as string | undefined) || null;
  // Only an unreviewed draft is worth a row; a promoted dashboard reads like
  // any other.
  const aiDraft = dashboard?.ai_generation?.status === 'draft' ? dashboard.ai_generation : null;

  // Resolve project_id → project.name + template_origin asynchronously.
  // Skip enrichment to keep the request small (we only need name +
  // template_origin, which the lite payload already carries).
  useEffect(() => {
    if (!projectId || !active) {
      setProjectName(null);
      setProjectTemplateOrigin(null);
      return;
    }
    let cancelled = false;
    fetchProject(projectId, { skipEnrichment: true })
      .then(({ project }) => {
        if (cancelled) return;
        setProjectName(project.name ?? null);
        setProjectTemplateOrigin((project as { template_origin?: unknown }).template_origin ?? null);
      })
      .catch(() => {
        if (cancelled) return;
        setProjectName(null);
        setProjectTemplateOrigin(null);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, active]);

  const parsedTemplate = parseTemplateOrigin(projectTemplateOrigin);

  // The run-provenance keys the template flagged as highlights — the primer /
  // truncation / filtering settings a reader needs to interpret the dashboard.
  // The complete listing lives in the ingestion report; this is the digest.
  const runProvenance: ProvenanceEntryLike[] = (() => {
    const origin = projectTemplateOrigin as {
      run_provenance?: Array<{
        source?: string;
        key?: string;
        value?: string;
        group?: string;
        highlight?: boolean;
      }>;
    } | null;
    if (!origin || !Array.isArray(origin.run_provenance)) return [];
    return origin.run_provenance
      .filter((e) => e && e.key)
      .map((e) => ({
        source: String(e.source ?? ''),
        key: String(e.key),
        value: String(e.value ?? ''),
        group: String(e.group ?? 'Other'),
        highlight: Boolean(e.highlight),
      }));
  })();

  const runProvenanceFiles: string[] = (() => {
    const origin = projectTemplateOrigin as { run_provenance_files?: unknown } | null;
    const files = origin?.run_provenance_files;
    return Array.isArray(files) ? files.map(String) : [];
  })();

  return (
    <Stack gap="md">
      {title && (
        <Stack gap={2}>
          <Text size="lg" fw={600}>
            {title}
          </Text>
          {subtitle && (
            <Text size="sm" c="dimmed">
              {subtitle}
            </Text>
          )}
        </Stack>
      )}

      <Divider />

      <Stack gap="sm">
        <MetaRow
          icon="mdi:jira"
          color="teal"
          label="Project"
          value={
            projectName && projectId ? (
              <Tooltip label={`Open project: ${projectName}`} withArrow withinPortal>
                <Anchor
                  href={`/projects/${projectId}`}
                  size="sm"
                  fw={500}
                  style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}
                >
                  {projectName}
                  <Icon icon="mdi:open-in-new" width={12} />
                </Anchor>
              </Tooltip>
            ) : projectName ? (
              <Text size="sm" fw={500}>
                {projectName}
              </Text>
            ) : (
              <Text size="sm" c="dimmed">
                {projectId ? 'Loading…' : '—'}
              </Text>
            )
          }
        />
        {parsedTemplate && (
          <MetaRow
            icon="mdi:source-branch"
            color="green"
            label="Template"
            value={<TemplateChip parsed={parsedTemplate} verbose />}
          />
        )}
        {projectId && (
          <MetaRow
            icon="mdi:clipboard-check-outline"
            color="indigo"
            label="Ingestion"
            value={
              <Anchor href={`/projects/${projectId}#ingestion`} size="sm" fw={500}>
                View ingestion report
              </Anchor>
            }
          />
        )}
        {runProvenance.length > 0 && (
          <MetaRow
            icon="mdi:tune-variant"
            color="orange"
            label="Run parameters"
            value={
              <RunParameters
                entries={runProvenance}
                files={runProvenanceFiles}
                projectId={projectId}
              />
            }
          />
        )}
        {ownerEmail && (
          <MetaRow
            icon="mdi:account-circle-outline"
            color="blue"
            label="Owner"
            value={<Text size="sm">{ownerEmail}</Text>}
          />
        )}
        <MetaRow
          icon={isPublic ? 'mdi:earth' : 'mdi:lock'}
          color={isPublic ? 'teal' : 'violet'}
          label="Visibility"
          value={
            <Badge color={isPublic ? 'teal' : 'violet'} variant="light" size="md">
              {isPublic ? 'Public' : 'Private'}
            </Badge>
          }
        />
        {aiDraft && (
          <MetaRow
            icon={AI_ICON}
            color={AI_COLOR}
            label="AI draft"
            value={
              <Group gap="xs" wrap="nowrap">
                <Badge color={AI_COLOR} variant="light" size="md">
                  Not yet promoted
                </Badge>
                <Text size="xs" c="dimmed" lineClamp={1}>
                  {aiDraft.model}
                </Text>
              </Group>
            }
          />
        )}
        {lastSaved && (
          <MetaRow
            icon="mdi:clock-outline"
            color="gray"
            label="Last modified"
            value={<Text size="sm">{lastSaved}</Text>}
          />
        )}
        {realtimeEnabled && (
          <MetaRow
            icon="mdi:flash"
            color="orange"
            label="Realtime"
            value={
              <Badge color="orange" variant="light" size="md">
                Enabled
              </Badge>
            }
          />
        )}
        {isMainTab === false && parentDashboardId && (
          <MetaRow
            icon="mdi:tab"
            color="grape"
            label="Parent tab"
            value={<Code>{parentDashboardId}</Code>}
          />
        )}
      </Stack>

      <Divider label="Identifiers" labelPosition="left" my="xs" />

      <Stack gap="xs">
        {dashboardId && <CopyableId label="Dashboard ID" value={dashboardId} />}
        {projectId && <CopyableId label="Project ID" value={projectId} />}
      </Stack>
    </Stack>
  );
};

interface MetaRowProps {
  icon: string;
  /** Mantine palette name (e.g. `teal`), not a CSS value — the row builds the
   *  var itself so call sites stay on the theme rather than hand-writing it. */
  color: string;
  label: string;
  value: React.ReactNode;
}

const MetaRow: React.FC<MetaRowProps> = ({ icon, color, label, value }) => (
  <Group gap="sm" wrap="nowrap" align="center">
    <Icon icon={icon} width={20} color={`var(--mantine-color-${color}-6)`} />
    <Stack gap={0} style={{ flex: 1, minWidth: 0 }}>
      <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
        {label}
      </Text>
      {value}
    </Stack>
  </Group>
);

const CopyableId: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <Group gap="xs" wrap="nowrap" align="center">
    <Stack gap={0} style={{ flex: 1, minWidth: 0 }}>
      <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
        {label}
      </Text>
      <Code style={{ overflowWrap: 'anywhere' }}>{value}</Code>
    </Stack>
    <CopyButton value={value} timeout={1500}>
      {({ copied, copy }) => (
        <Tooltip label={copied ? 'Copied' : 'Copy'} withArrow withinPortal>
          <ActionIcon variant="subtle" color={copied ? 'teal' : 'gray'} size="sm" onClick={copy}>
            <Icon icon={copied ? 'mdi:check' : 'mdi:content-copy'} width={14} />
          </ActionIcon>
        </Tooltip>
      )}
    </CopyButton>
  </Group>
);

/**
 * The pipeline's own settings, from a 400px drawer.
 *
 * Two levels, because the two readings want different room. The template's
 * `provenance.highlight` keys stay inline — the handful of settings needed to
 * read the dashboard at all (primers, truncation, filtering thresholds), short
 * enough for a key/value table at panel width. Everything else opens in a
 * modal running the SAME component as the ingestion report, rather than a
 * cramped copy of it: a 235-row grouped table needs the width, and one
 * implementation means one behaviour to learn.
 *
 * Highlighting therefore decides the ORDER of discovery, not what exists —
 * which is what keeps the mechanism honest for a pipeline whose template
 * names no highlight at all.
 */
const RunParameters: React.FC<{
  entries: ProvenanceEntryLike[];
  files: string[];
  projectId: string | null;
}> = ({ entries, files, projectId }) => {
  const [modalOpen, setModalOpen] = useState(false);
  const highlights = useMemo(() => entries.filter((e) => e.highlight), [entries]);

  // Re-group the flat entry list the way the report's endpoint already does —
  // consecutive runs of the same group, in collection order.
  const groups = useMemo(() => {
    const out: Array<{ group: string; entries: ProvenanceEntryLike[] }> = [];
    for (const e of entries) {
      const name = e.group || 'Other';
      const last = out[out.length - 1];
      if (last && last.group === name) last.entries.push(e);
      else out.push({ group: name, entries: [e] });
    }
    return out;
  }, [entries]);

  return (
    <>
      <Accordion
        variant="default"
        chevronPosition="left"
        styles={{
          item: { border: 'none' },
          control: { padding: 0 },
          content: { padding: 0 },
          label: { padding: 0 },
        }}
      >
        <Accordion.Item value="run-params">
          <Accordion.Control>
            <Text size="sm" fw={500}>
              {highlights.length > 0
                ? `${highlights.length} key settings`
                : `${entries.length} parameters`}
            </Text>
          </Accordion.Control>
          <Accordion.Panel>
            {highlights.length > 0 && (
              <Table verticalSpacing={2} withRowBorders={false}>
                <Table.Tbody>
                  {highlights.map((e) => (
                    <Table.Tr key={e.key}>
                      <Table.Td px={0} w={150}>
                        <Text size="xs" fw={500} style={{ overflowWrap: 'anywhere' }}>
                          {e.key}
                        </Text>
                      </Table.Td>
                      <Table.Td px={0}>
                        <Code fz={11} style={{ overflowWrap: 'anywhere' }}>
                          {e.value}
                        </Code>
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            )}
            <Group gap="sm" mt={6} wrap="nowrap">
              <Anchor
                component="button"
                type="button"
                size="xs"
                fw={500}
                onClick={() => setModalOpen(true)}
              >
                All {entries.length} parameters →
              </Anchor>
              {projectId && (
                <Anchor href={`/projects/${projectId}#ingestion`} size="xs" fw={500}>
                  Ingestion report →
                </Anchor>
              )}
            </Group>
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>

      <Modal
        opened={modalOpen}
        onClose={() => setModalOpen(false)}
        title="Run parameters"
        size="xl"
        // Above the Settings drawer that opened it.
        zIndex={400}
        scrollAreaComponent={ScrollArea.Autosize}
      >
        <RunProvenanceCard groups={groups} files={files} withCard={false} />
      </Modal>
    </>
  );
};

export default DashboardInfoBody;
