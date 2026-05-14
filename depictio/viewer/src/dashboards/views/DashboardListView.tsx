import React from 'react';
import { SimpleGrid } from '@mantine/core';

import type { DashboardListEntry } from 'depictio-react-core';
import type { GroupedDashboards } from '../lib/splitDefaultSections';
import { isOwnedByEmail } from '../lib/splitDefaultSections';
import type { CategoryInfo } from '../DashboardsList';
import DashboardCompactCard from './DashboardCompactCard';

export interface DashboardListViewProps {
  groups: GroupedDashboards[];
  projectNames: Map<string, string>;
  currentUserEmail: string | null;
  pinnedIds: Set<string>;
  pinDisabled: boolean;
  /** When provided, each card renders a Category badge derived from this map.
   *  The orchestrator uses this in flat (single-section) mode so the section
   *  the dashboard would have lived in is still surfaced inline. */
  categoryById?: Map<string, CategoryInfo>;
  onView: (d: DashboardListEntry) => void;
  onEdit: (d: DashboardListEntry) => void;
  onDelete: (d: DashboardListEntry) => void;
  onDuplicate: (d: DashboardListEntry) => void;
  onExport: (d: DashboardListEntry) => void;
  onTogglePin: (id: string) => void;
}

const DashboardListView: React.FC<DashboardListViewProps> = ({
  groups,
  projectNames,
  currentUserEmail,
  pinnedIds,
  pinDisabled,
  categoryById,
  onView,
  onEdit,
  onDelete,
  onDuplicate,
  onExport,
  onTogglePin,
}) => (
  <SimpleGrid
    cols={{ base: 1, sm: 2, md: 3, lg: 4, xl: 5 }}
    spacing="xs"
    verticalSpacing="xs"
  >
    {groups.map((group) => {
      const projectName = group.parent.project_id
        ? projectNames.get(String(group.parent.project_id))
        : undefined;
      const id = String(group.parent.dashboard_id);
      return (
        <DashboardCompactCard
          key={id}
          dashboard={group.parent}
          childCount={group.children.length}
          isOwner={isOwnedByEmail(group.parent, currentUserEmail)}
          projectName={projectName}
          pinned={pinnedIds.has(id)}
          pinDisabled={pinDisabled}
          category={categoryById?.get(id)}
          onView={onView}
          onEdit={onEdit}
          onDelete={onDelete}
          onDuplicate={onDuplicate}
          onExport={onExport}
          onTogglePin={() => onTogglePin(id)}
        />
      );
    })}
  </SimpleGrid>
);

export default DashboardListView;
