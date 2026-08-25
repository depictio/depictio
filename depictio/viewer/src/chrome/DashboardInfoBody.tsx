import React, { useEffect, useState } from 'react';
import {
  Anchor,
  Badge,
  Code,
  CopyButton,
  Divider,
  Group,
  Stack,
  Text,
  Tooltip,
  ActionIcon,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import type { DashboardData } from 'depictio-react-core';
import { fetchProject } from 'depictio-react-core';
import { parseTemplateOrigin, TemplateChip } from '../projects/template';
import { formatDateTime } from '../lib/datetime';

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

export default DashboardInfoBody;
