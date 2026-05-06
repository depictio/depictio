import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Accordion,
  Button,
  Center,
  Group,
  Paper,
  SimpleGrid,
  Space,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import type { DashboardListEntry, ProjectListEntry } from 'depictio-react-core';
import DashboardCard from './DashboardCard';

interface DashboardsListProps {
  dashboards: DashboardListEntry[];
  projects: ProjectListEntry[];
  currentUserEmail: string | null;
  onEdit: (d: DashboardListEntry) => void;
  onDelete: (d: DashboardListEntry) => void;
  onDuplicate: (d: DashboardListEntry) => void;
  onExport: (d: DashboardListEntry) => void;
  onCreateClick: () => void;
}

interface GroupedDashboards {
  parent: DashboardListEntry;
  children: DashboardListEntry[];
}

function isOwnedByEmail(d: DashboardListEntry, email: string | null): boolean {
  if (!email) return false;
  const owners = d.permissions?.owners ?? [];
  return owners.some((o) => o?.email === email);
}

/** Example dashboards are identified by hardcoded MongoDB ObjectIds — same
 *  list as Dash (`dashboards_management.py:1484-1488`). These IDs are
 *  stamped at db_init time on the seed dashboards (ampliseq, penguins, iris)
 *  and keep their assignment forever, regardless of ownership or public flag.
 *  Order in this array doubles as display order in the Examples section. */
const EXAMPLE_DASHBOARD_IDS: readonly string[] = [
  '646b0f3c1e4a2d7f8e5b8ca2', // nf-core/ampliseq
  '6824cb3b89d2b72169309738', // Penguins Species Analysis
  '6824cb3b89d2b72169309737', // Iris Species Comparison
];

function isExampleDashboard(d: DashboardListEntry): boolean {
  return EXAMPLE_DASHBOARD_IDS.includes(String(d.dashboard_id));
}

function groupByParent(entries: DashboardListEntry[]): GroupedDashboards[] {
  const parents = entries.filter((d) => !d.parent_dashboard_id);
  const childrenByParent = new Map<string, DashboardListEntry[]>();
  for (const d of entries) {
    if (!d.parent_dashboard_id) continue;
    const list = childrenByParent.get(String(d.parent_dashboard_id)) ?? [];
    list.push(d);
    childrenByParent.set(String(d.parent_dashboard_id), list);
  }
  return parents.map((parent) => ({
    parent,
    children: (childrenByParent.get(parent.dashboard_id) ?? []).sort(
      (a, b) => (a.tab_order ?? 0) - (b.tab_order ?? 0),
    ),
  }));
}

function projectNameLookup(projects: ProjectListEntry[]): Map<string, string> {
  const map = new Map<string, string>();
  for (const p of projects) {
    const id = String(p._id ?? p.id ?? '');
    if (id) map.set(id, p.name);
  }
  return map;
}

/** Section header — matches dashboards_management.py:1652-1755:
 *  icon (specific color hex) + bold "Label (count)" Text size="lg". */
const SectionHeader: React.FC<{ icon: string; color: string; label: string; count: number }> = ({
  icon,
  color,
  label,
  count,
}) => (
  <Group gap="xs">
    <Icon icon={icon} width={18} color={color} />
    <Text size="lg" fw={700}>
      {label} ({count})
    </Text>
  </Group>
);

/** Empty state card — mirrors `dashboards_management.py:create_empty_state_card`
 *  (lines 1423-1474): centered Paper with a 64px icon, bold title, dimmed
 *  subtitle. The 500px max-width and 300px min-height match Dash's spacing. */
const EmptyStateCard: React.FC<{
  icon: string;
  title: string;
  description: string;
}> = ({ icon, title, description }) => (
  <Center mih={300}>
    <Paper
      shadow="sm"
      radius="md"
      p="xl"
      withBorder
      style={{ width: '100%', maxWidth: 500 }}
    >
      <Stack align="center" gap="sm">
        <Icon icon={icon} width={64} height={64} color="#6c757d" />
        <Text ta="center" fw="bold" size="xl">
          {title}
        </Text>
        <Text ta="center" c="gray" size="sm">
          {description}
        </Text>
      </Stack>
    </Paper>
  </Center>
);

const DashboardsList: React.FC<DashboardsListProps> = ({
  dashboards,
  projects,
  currentUserEmail,
  onEdit,
  onDelete,
  onDuplicate,
  onExport,
  onCreateClick,
}) => {
  const projectNames = useMemo(() => projectNameLookup(projects), [projects]);

  const { owned, accessed, public_, examples } = useMemo(() => {
    const grouped = groupByParent(dashboards);
    const ownedList: GroupedDashboards[] = [];
    const accessedList: GroupedDashboards[] = [];
    const publicList: GroupedDashboards[] = [];
    const exampleList: GroupedDashboards[] = [];
    // Categorisation precedence (matches `dashboards_management.py:1476`):
    // Example > Public > Accessed > Owned. The seed dashboards (ampliseq,
    // penguins, iris) are owned by the admin user but should still surface
    // under "Example" for everyone, including the admin themselves.
    for (const g of grouped) {
      if (isExampleDashboard(g.parent)) {
        exampleList.push(g);
        continue;
      }
      const isOwner = isOwnedByEmail(g.parent, currentUserEmail);
      const isPublic = Boolean(g.parent.is_public);
      if (isOwner) ownedList.push(g);
      else if (isPublic) publicList.push(g);
      else accessedList.push(g);
    }
    // Sort examples in the canonical order from EXAMPLE_DASHBOARD_IDS so
    // ampliseq always renders first regardless of insertion order in Mongo.
    exampleList.sort(
      (a, b) =>
        EXAMPLE_DASHBOARD_IDS.indexOf(String(a.parent.dashboard_id)) -
        EXAMPLE_DASHBOARD_IDS.indexOf(String(b.parent.dashboard_id)),
    );
    return {
      owned: ownedList,
      accessed: accessedList,
      public_: publicList,
      examples: exampleList,
    };
  }, [dashboards, currentUserEmail]);

  const handleView = (d: DashboardListEntry) => {
    window.location.assign(`/dashboard-beta/${d.dashboard_id}`);
  };

  const renderGroup = (group: GroupedDashboards) => {
    const projectName = group.parent.project_id
      ? projectNames.get(String(group.parent.project_id))
      : undefined;
    return (
      <DashboardCard
        key={group.parent.dashboard_id}
        dashboard={group.parent}
        childTabs={group.children}
        isOwner={isOwnedByEmail(group.parent, currentUserEmail)}
        projectName={projectName}
        onView={handleView}
        onEdit={onEdit}
        onDelete={onDelete}
        onDuplicate={onDuplicate}
        onExport={onExport}
      />
    );
  };

  // Match dashboards_management.py:1626-1636 — pre-expand only non-empty
  // sections. Hooks live above the early return below to keep React's hook
  // order stable across renders. The ref-guarded effect applies the initial
  // open-set the first time real data arrives (the parent's async fetch
  // resolves after first render, so a useMemo initialiser would lock in the
  // 0/0/0/0 snapshot and never open anything). User toggles after the
  // initial application win.
  const [openSections, setOpenSections] = useState<string[]>([]);
  const initializedRef = useRef(false);
  useEffect(() => {
    if (initializedRef.current) return;
    if (dashboards.length === 0) return;
    initializedRef.current = true;
    setOpenSections(
      [
        owned.length > 0 && 'owned',
        accessed.length > 0 && 'accessed',
        public_.length > 0 && 'public',
        examples.length > 0 && 'example',
      ].filter(Boolean) as string[],
    );
  }, [
    dashboards.length,
    owned.length,
    accessed.length,
    public_.length,
    examples.length,
  ]);

  if (dashboards.length === 0) {
    return (
      <Center mih={400}>
        <Stack align="center" gap="md">
          <Icon
            icon="material-symbols:dashboard-outline"
            width={48}
            color="var(--mantine-color-dimmed)"
          />
          <Title order={4}>No dashboards yet</Title>
          <Text c="dimmed">Create your first dashboard or import an existing one.</Text>
          <Button leftSection={<Icon icon="mdi:plus" width={14} />} onClick={onCreateClick}>
            New dashboard
          </Button>
        </Stack>
      </Center>
    );
  }

  // Custom chevron with a fixed-size wrapper so the rotation transform doesn't
  // shift the bounding box between open/closed states. We override Mantine's
  // default 180° rotation (which would map ▶ → ◀) to a conventional 90° turn
  // so closed shows ▶ and open shows ▼ at the exact same anchor point.
  const fixedChevron = (
    <span
      style={{
        display: 'inline-flex',
        width: 18,
        height: 18,
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <Icon icon="tabler:chevron-right" width={18} />
    </span>
  );

  return (
    <Accordion
      multiple
      value={openSections}
      onChange={setOpenSections}
      variant="default"
      chevronPosition="left"
      chevron={fixedChevron}
      styles={{
        chevron: {
          transition: 'transform 200ms ease',
          // Mantine sets `data-rotate` on the chevron when the item is open.
          // The default rotation is 180° — override to 90° so the chevron
          // rotates ▶ → ▼ around its center, keeping the visual anchor fixed.
          '&[data-rotate]': {
            transform: 'rotate(90deg)',
          },
        },
      }}
    >
      <Accordion.Item value="owned">
        <Accordion.Control>
          <SectionHeader
            icon="mdi:account-check"
            color="#1c7ed6"
            label="Owned Dashboards"
            count={owned.length}
          />
        </Accordion.Control>
        <Accordion.Panel>
          <Space h={10} />
          {owned.length === 0 ? (
            <EmptyStateCard
              icon="mdi:account-check"
              title="No owned dashboards"
              description="Create your first dashboard to get started."
            />
          ) : (
            <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }} spacing="xl" verticalSpacing="xl">
              {owned.map(renderGroup)}
            </SimpleGrid>
          )}
        </Accordion.Panel>
      </Accordion.Item>

      <Accordion.Item value="accessed">
        <Accordion.Control>
          <SectionHeader
            icon="material-symbols:share-outline"
            color="#54ca74"
            label="Accessed Dashboards"
            count={accessed.length}
          />
        </Accordion.Control>
        <Accordion.Panel>
          <Space h={10} />
          {accessed.length === 0 ? (
            <EmptyStateCard
              icon="material-symbols:share-outline"
              title="No accessed dashboards"
              description="Dashboards shared with you will appear here."
            />
          ) : (
            <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }} spacing="xl" verticalSpacing="xl">
              {accessed.map(renderGroup)}
            </SimpleGrid>
          )}
        </Accordion.Panel>
      </Accordion.Item>

      <Accordion.Item value="public">
        <Accordion.Control>
          <SectionHeader
            icon="mdi:earth"
            color="#20c997"
            label="Public Dashboards"
            count={public_.length}
          />
        </Accordion.Control>
        <Accordion.Panel>
          <Space h={10} />
          {public_.length === 0 ? (
            <EmptyStateCard
              icon="mdi:earth"
              title="No public dashboards"
              description="Public dashboards will appear here."
            />
          ) : (
            <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }} spacing="xl" verticalSpacing="xl">
              {public_.map(renderGroup)}
            </SimpleGrid>
          )}
        </Accordion.Panel>
      </Accordion.Item>

      <Accordion.Item value="example">
        <Accordion.Control>
          <SectionHeader
            icon="mdi:school-outline"
            color="#fd7e14"
            label="Example Dashboards"
            count={examples.length}
          />
        </Accordion.Control>
        <Accordion.Panel>
          <Space h={10} />
          {examples.length === 0 ? (
            <EmptyStateCard
              icon="mdi:school-outline"
              title="No example dashboards"
              description="Example and demo dashboards will appear here."
            />
          ) : (
            <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }} spacing="xl" verticalSpacing="xl">
              {examples.map(renderGroup)}
            </SimpleGrid>
          )}
        </Accordion.Panel>
      </Accordion.Item>
    </Accordion>
  );
};

export default DashboardsList;
