/** Dev-only harness: mounts the real DashboardTableView / ProjectTableView with
 *  fixture data so the column picker and timezone rendering can be exercised in
 *  a browser without a backend.
 *
 *  Run: `npx vite --config vite.table-harness.config.ts` then open `/`.
 *  Not referenced by the app or its production build.
 */
import React from 'react';
import { createRoot } from 'react-dom/client';
import { MantineProvider, Stack, Title } from '@mantine/core';
import { depictioTheme } from './src/theme';
import '@mantine/core/styles.css';

import DashboardTableView from './src/dashboards/views/DashboardTableView';
import ProjectTableView from './src/projects/views/ProjectTableView';

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

const noop = () => {};

const App = () => (
  <MantineProvider theme={depictioTheme}>
    <Stack p="lg" gap="xl">
      <Title order={3}>Dashboards</Title>
      <DashboardTableView
        groups={dashboards}
        projectNames={new Map([['p1', 'Iris project'], ['p2', 'Penguins project']])}
        currentUserEmail="owner@example.com"
        pinnedIds={new Set()}
        pinDisabled={false}
        density="cozy"
        onView={noop}
        onEdit={noop}
        onDelete={noop}
        onDuplicate={noop}
        onExport={noop}
        onTogglePin={noop}
        onSetDensity={noop}
        onBulkExport={noop}
        onBulkDelete={noop}
      />
      <Title order={3}>Projects</Title>
      <ProjectTableView
        projects={projects}
        currentUserId="u1"
        isAdmin
        pinnedIds={new Set()}
        pinDisabled={false}
        onView={noop}
        onEdit={noop}
        onDelete={noop}
        onTogglePin={noop}
      />
    </Stack>
  </MantineProvider>
);

createRoot(document.getElementById('root')!).render(<App />);
