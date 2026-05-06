import React from 'react';
import {
  Accordion,
  Box,
  Button,
  Center,
  Paper,
  Stack,
  Text,
  Title,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import type { ProjectListEntry } from 'depictio-react-core';

import ProjectCard from './ProjectCard';

interface ProjectsListProps {
  projects: ProjectListEntry[];
  currentUserId: string | null;
  isAdmin: boolean;
  /** True in public/demo mode — keeps the empty-state Create Project button
   *  visible but disabled, with a tooltip explaining why. */
  createDisabled: boolean;
  onCreateClick: () => void;
  onEdit: (project: ProjectListEntry) => void;
  onDelete: (project: ProjectListEntry) => void;
}

/** Mirrors the Dash projects list layout: a column-header row above an
 *  accordion of project rows. Columns are: Project Type | Visibility |
 *  Permission | (template badge) | Project Name. Each column has a fixed
 *  width so the badges line up vertically across rows. */
const COLUMN_HEADERS: Array<{ key: string; label: string; width: number }> = [
  { key: 'type', label: 'Project Type', width: 100 },
  { key: 'visibility', label: 'Visibility', width: 80 },
  { key: 'permission', label: 'Permission', width: 80 },
  { key: 'name', label: 'Project Name', width: 0 }, // 0 = flex
];

const ProjectsList: React.FC<ProjectsListProps> = ({
  projects,
  currentUserId,
  isAdmin,
  createDisabled,
  onCreateClick,
  onEdit,
  onDelete,
}) => {
  if (projects.length === 0) {
    return (
      <Center mih={400}>
        <Paper p="xl" radius="md" withBorder maw={500} miw={300}>
          <Stack align="center" gap="md">
            <Icon
              icon="material-symbols:folder-off-outline"
              width={64}
              height={64}
              color="var(--mantine-color-gray-5)"
            />
            <Title order={3} c="dimmed">
              No projects available
            </Title>
            <Text c="dimmed" ta="center">
              {createDisabled
                ? 'Project creation is disabled on this public/demo instance.'
                : 'Create your first project to start organizing data collections and dashboards.'}
            </Text>
            <Tooltip
              label="Project creation is disabled in public/demo mode"
              disabled={!createDisabled}
              withArrow
            >
              <Button
                color="teal"
                variant="filled"
                onClick={onCreateClick}
                disabled={createDisabled}
                leftSection={<Icon icon="mdi:plus" width={18} />}
                style={{ fontFamily: 'Virgil' }}
              >
                Create Project
              </Button>
            </Tooltip>
          </Stack>
        </Paper>
      </Center>
    );
  }

  return (
    <Stack gap="xs">
      {/* Column header row — sits above the accordion. Padding mirrors the
       *  Accordion.Control inner padding so each header aligns with the
       *  matching cell below. */}
      <Box px="md" py={2}>
        <ColumnHeaderRow />
      </Box>
      <Accordion
        multiple
        variant="default"
        chevronPosition="right"
        styles={{
          item: {
            borderTop: '1px solid var(--mantine-color-default-border)',
            background: 'var(--mantine-color-body)',
            marginBottom: 0,
            borderRadius: 0,
          },
          control: {
            paddingTop: 0,
            paddingBottom: 0,
            paddingLeft: 16,
            paddingRight: 16,
            minHeight: 40,
          },
          panel: {
            paddingLeft: 16,
            paddingRight: 16,
          },
        }}
      >
        {projects.map((p) => (
          <ProjectCard
            key={(p._id ?? p.id) as string}
            project={p}
            currentUserId={currentUserId}
            isAdmin={isAdmin}
            onEdit={onEdit}
            onDelete={onDelete}
          />
        ))}
      </Accordion>
    </Stack>
  );
};

const ColumnHeaderRow: React.FC = () => (
  <Box
    style={{
      display: 'flex',
      alignItems: 'center',
      gap: 12,
    }}
  >
    {COLUMN_HEADERS.map((col) => {
      const isFlex = col.width === 0;
      return (
        <Text
          key={col.key}
          size="xs"
          fw={600}
          c="dimmed"
          tt="capitalize"
          // Center the fixed-width badge columns so the badges below them
          // line up under their label. The flexible name column stays
          // left-aligned to read as a continuation of the project title.
          ta={isFlex ? 'left' : 'center'}
          style={{
            width: isFlex ? undefined : col.width,
            flex: isFlex ? 1 : undefined,
          }}
        >
          {col.label}
        </Text>
      );
    })}
  </Box>
);

export default ProjectsList;
