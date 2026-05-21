import React from 'react';
import { SimpleGrid } from '@mantine/core';

import type { DashboardListEntry } from 'depictio-react-core';
import DashboardCard from '../DashboardCard';
import type { GroupedDashboards } from '../lib/splitDefaultSections';
import { isOwnedByEmail } from '../lib/splitDefaultSections';

export interface DashboardThumbnailViewProps {
  groups: GroupedDashboards[];
  projectNames: Map<string, string>;
  /** Optional per-project `template_origin` lookup (id → raw origin blob).
   *  When the dashboard's project has an entry, DashboardCard renders a
   *  TemplateChip linking to the depictio-docs template page. */
  projectTemplates?: Map<string, unknown>;
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
  projectTemplates,
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
      const projectId = group.parent.project_id
        ? String(group.parent.project_id)
        : null;
      const projectName = projectId ? projectNames.get(projectId) : undefined;
      const projectTemplateOrigin = projectId
        ? projectTemplates?.get(projectId)
        : undefined;
      return (
        <DashboardCard
          key={group.parent.dashboard_id}
          dashboard={group.parent}
          childTabs={group.children}
          isOwner={isOwnedByEmail(group.parent, currentUserEmail)}
          projectName={projectName}
          projectTemplateOrigin={projectTemplateOrigin}
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
