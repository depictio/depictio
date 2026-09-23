import React from 'react';
import { SimpleGrid, type SimpleGridProps } from '@mantine/core';

import type { DashboardListEntry } from 'depictio-react-core';
import DashboardCard from '../DashboardCard';
import type { CardBadge, CardsPerRow } from '../hooks/useDashboardViewPrefs';
import type { GroupedDashboards } from '../lib/splitDefaultSections';
import { isOwnedByEmail } from '../lib/splitDefaultSections';

export interface DashboardThumbnailViewProps {
  groups: GroupedDashboards[];
  projectNames: Map<string, string>;
  /** Optional per-project `template_origin` lookup (id → raw origin blob).
   *  When the dashboard's project has an entry, DashboardCard renders a
   *  TemplateChip linking to the depictio-docs template page. */
  projectTemplates?: Map<string, unknown>;
  /** Grid width cap from the toolbar's "Card display" menu. */
  cardsPerRow?: CardsPerRow;
  /** Badges each card shows; every badge when omitted. */
  visibleBadges?: ReadonlySet<CardBadge>;
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

/** Responsive column counts for the grid.
 *
 *  `auto` keeps the long-standing 1 / 2 / 4 layout, except that it never asks
 *  for more columns than the section has cards: a section holding two
 *  dashboards used to render them as quarter-width cards with two empty cells
 *  beside them, which is also what made those thumbnails needlessly small.
 *
 *  An explicit count is what the widest screens get, and narrower breakpoints
 *  are capped at it: asking for 2 never squeezes more onto a laptop, and
 *  asking for 6 still collapses to one card on a phone. It is a deliberate
 *  choice, so a short section keeps it rather than growing its cards. */
function gridCols(cardsPerRow: CardsPerRow, count: number): SimpleGridProps['cols'] {
  if (cardsPerRow === 'auto') {
    // `Math.max(1, ...)`: an empty section would otherwise ask for 0 columns.
    return { base: 1, sm: Math.max(1, Math.min(2, count)), lg: Math.max(1, Math.min(4, count)) };
  }
  return {
    base: 1,
    sm: Math.min(2, cardsPerRow),
    md: Math.min(3, cardsPerRow),
    lg: cardsPerRow,
  };
}

const DashboardThumbnailView: React.FC<DashboardThumbnailViewProps> = ({
  groups,
  projectNames,
  projectTemplates,
  cardsPerRow = 'auto',
  visibleBadges,
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
  <SimpleGrid cols={gridCols(cardsPerRow, groups.length)} spacing="xl" verticalSpacing="xl">
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
          visibleBadges={visibleBadges}
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
