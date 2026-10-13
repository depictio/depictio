/** Dev-only harness: mounts the real DashboardTableView / ProjectTableView,
 *  each with the Table display menu the listing toolbars carry, on fixture data
 *  so the column choice and timezone rendering can be exercised in a browser
 *  without a backend.
 *
 *  Run: `npx vite --config vite.table-harness.config.ts` then open `/`.
 *  Not referenced by the app or its production build.
 */
import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Group, MantineProvider, Stack, Title } from '@mantine/core';
import { depictioTheme } from './src/theme';
import '@mantine/core/styles.css';

import TableDisplayMenu, { type TableDensity } from './src/components/TableDisplayMenu';
import DashboardTableView, {
  useDashboardTableColumns,
} from './src/dashboards/views/DashboardTableView';
import ProjectTableView, { useProjectTableColumns } from './src/projects/views/ProjectTableView';

const owner = { _id: 'u1', email: 'owner@example.com' };

// 09:00 UTC — a CEST viewer must render this as 11:00 (issue #932).
const dashboards = [
  {
    parent: {
      dashboard_id: '646b0f3c1e4a2d7f8e5b8ca2',
      title: 'Iris demo',
      subtitle: 'Sepal exploration',
      project_id: 'p1',
      is_public: true,
      version: 3,
      workflow_system: 'nf-core',
      creation_time: '2024-01-01 09:00:00',
      last_saved_ts: '2026-08-04 09:00:00',
      stored_metadata: [{}, {}, {}],
      permissions: { owners: [owner] },
    },
    children: [{}],
  },
  {
    parent: {
      dashboard_id: '646b0f3c1e4a2d7f8e5b8cb3',
      title: 'Penguins',
      project_id: 'p2',
      is_public: false,
      version: 1,
      creation_time: '2025-12-31 23:30:00',
      last_saved_ts: '',
      permissions: { owners: [owner] },
    },
    children: [],
  },
] as never;

const projects = [
  {
    _id: 'p1',
    name: 'Iris project',
    project_type: 'advanced',
    is_public: true,
    registration_time: '2024-01-01 09:00:00',
    last_modified: '2026-08-04 09:00:00',
    yaml_config_path: '/data/iris/config.yaml',
    workflows: [{ data_collections: [{}, {}] }],
    joins: [{}],
    permissions: { owners: [owner], editors: [], viewers: [] },
  },
  {
    _id: 'p2',
    name: 'Penguins project',
    project_type: 'basic',
    is_public: false,
    registration_time: '2025-12-31 23:30:00',
    permissions: { owners: [owner], editors: [], viewers: [] },
  },
] as never;

// One dashboard opened recently, one never opened: exercises both branches of
// the Last viewed column (a time cell and the "Never" placeholder).
const recents = [{ id: '646b0f3c1e4a2d7f8e5b8ca2', ts: Date.now() - 3 * 3600_000 }];

const noop = () => {};

const Dashboards = () => {
  const columns = useDashboardTableColumns(false);
  const [density, setDensity] = useState<TableDensity>('cozy');
  return (
    <Stack gap="xs">
      <Group justify="space-between">
        <Title order={3}>Dashboards</Title>
        <TableDisplayMenu
          section="dashboards"
          density={density}
          defaultDensity="cozy"
          onDensityChange={setDensity}
          columns={columns}
        />
      </Group>
      <DashboardTableView
        groups={dashboards}
        projectNames={new Map([['p1', 'Iris project'], ['p2', 'Penguins project']])}
        currentUserEmail="owner@example.com"
        pinnedIds={new Set()}
        pinDisabled={false}
        density={density}
        columns={columns}
        recents={recents}
        onView={noop}
        onEdit={noop}
        onDelete={noop}
        onDuplicate={noop}
        onExport={noop}
        onTogglePin={noop}
        onBulkExport={noop}
        onBulkDelete={noop}
      />
    </Stack>
  );
};

const Projects = () => {
  const columns = useProjectTableColumns();
  const [density, setDensity] = useState<TableDensity>('cozy');
  return (
    <Stack gap="xs">
      <Group justify="space-between">
        <Title order={3}>Projects</Title>
        <TableDisplayMenu
          section="projects"
          density={density}
          defaultDensity="cozy"
          onDensityChange={setDensity}
          columns={columns}
        />
      </Group>
      <ProjectTableView
        projects={projects}
        currentUserId="u1"
        isAdmin
        pinnedIds={new Set()}
        pinDisabled={false}
        density={density}
        columns={columns}
        onView={noop}
        onEdit={noop}
        onDelete={noop}
        onTogglePin={noop}
      />
    </Stack>
  );
};

const App = () => (
  <MantineProvider theme={depictioTheme}>
    <Stack p="lg" gap="xl">
      <Dashboards />
      <Projects />
    </Stack>
  </MantineProvider>
);

createRoot(document.getElementById('root')!).render(<App />);
