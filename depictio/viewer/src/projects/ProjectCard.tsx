import React, { useState } from 'react';
import {
  Accordion,
  Anchor,
  Badge,
  Box,
  Button,
  Group,
  Paper,
  Stack,
  Text,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';

import { exportProjectZip } from 'depictio-react-core';
import type { ProjectListEntry } from 'depictio-react-core';

import { parseTemplate, TemplateChip, type ParsedTemplate } from './template';

/** Single-line row that navigates on click. Replaces the previous
 *  collapsible Workflows & Data / Roles and permissions accordion items —
 *  the panels were stub redirect copy, so a flat clickable row is clearer
 *  and saves a click. */
const NavRow: React.FC<{
  icon: string;
  iconColor: string;
  label: string;
  href: string;
}> = ({ icon, iconColor, label, href }) => (
  <Paper
    component="a"
    href={href}
    withBorder
    radius="sm"
    px="md"
    py="sm"
    style={{ display: 'block', textDecoration: 'none', color: 'inherit', cursor: 'pointer' }}
  >
    <Group justify="space-between" wrap="nowrap">
      <Group gap="sm" wrap="nowrap">
        <Icon icon={icon} width={20} color={iconColor} />
        <Text fw={500}>{label}</Text>
      </Group>
      <Icon icon="mdi:chevron-right" width={20} color="var(--mantine-color-gray-5)" />
    </Group>
  </Paper>
);

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

            <NavRow
              icon="mdi:database-outline"
              iconColor="var(--mantine-color-cyan-6)"
              label="Workflows & Data"
              href={`/projects-beta/${projectId}`}
            />

            <NavRow
              icon="mdi:shield-account-outline"
              iconColor="var(--mantine-color-blue-6)"
              label="Roles and permissions"
              href={`/projects-beta/${projectId}/permissions`}
            />

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

export default ProjectCard;
