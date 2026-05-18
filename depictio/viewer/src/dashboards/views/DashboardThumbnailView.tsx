import React from 'react';
import { SimpleGrid } from '@mantine/core';

import type { DashboardListEntry } from 'depictio-react-core';
import DashboardCard from '../DashboardCard';
import type { GroupedDashboards } from '../lib/splitDefaultSections';
import { isOwnedByEmail } from '../lib/splitDefaultSections';

export interface DashboardThumbnailViewProps {
  groups: GroupedDashboards[];
  projectNames: Map<string, string>;
  currentUserEmail: string | null;
  pinnedIds: Set<string>;
  pinDisabled: boolean;
  onView: (d: DashboardListEntry) => void;
  onEdit: (d: DashboardListEntry) => void;
  onDelete: (d: DashboardListEntry) => void;
  onDuplicate: (d: DashboardListEntry) => void;
  onExport: (d: DashboardListEntry) => void;
  onTogglePin: (id: string) => void;
}

const DashboardThumbnailView: React.FC<DashboardThumbnailViewProps> = ({
  groups,
  projectNames,
  currentUserEmail,
  pinnedIds,
  pinDisabled,
  onView,
  onEdit,
  onDelete,
  onDuplicate,
  onExport,
  onTogglePin,
}) => (
  <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }} spacing="xl" verticalSpacing="xl">
    {groups.map((group) => {
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
          pinned={pinnedIds.has(String(group.parent.dashboard_id))}
          pinDisabled={pinDisabled}
          onTogglePin={() => onTogglePin(String(group.parent.dashboard_id))}
          onView={onView}
          onEdit={onEdit}
          onDelete={onDelete}
          onDuplicate={onDuplicate}
          onExport={onExport}
        />
      );
    })}
  </SimpleGrid>
);

export default DashboardThumbnailView;
