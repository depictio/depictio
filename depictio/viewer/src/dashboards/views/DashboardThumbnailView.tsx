import React from 'react';
import { SimpleGrid, type SimpleGridProps } from '@mantine/core';

import type { DashboardListEntry } from 'depictio-react-core';
import DashboardCard from '../DashboardCard';
import type { CardBadge, CardsPerRow } from '../hooks/useDashboardViewPrefs';
import { DEFAULT_CARDS_PER_ROW } from '../hooks/useDashboardViewPrefs';
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

/** Responsive column counts for an explicit cards-per-row.
 *
 *  An explicit count is what the widest screens get, and narrower breakpoints
 *  are capped at it: asking for 2 never squeezes more onto a laptop, and
 *  asking for 6 still collapses to one card on a phone. The columns are fixed
 *  whatever the section holds, so a lone dashboard keeps the width it would
 *  have in a full row instead of stretching across it. */
function gridCols(cardsPerRow: Exclude<CardsPerRow, 'auto'>): SimpleGridProps['cols'] {
  return {
    base: 1,
    sm: Math.min(2, cardsPerRow),
    md: Math.min(3, cardsPerRow),
    lg: cardsPerRow,
  };
}

/** `auto`: as many columns of a readable width as fit. The empty tracks stay,
 *  so one dashboard (or two) sits at the same card width as in a full row. */
const AUTO_GRID_STYLE: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fill, minmax(min(100%, 300px), 1fr))',
  gap: 'var(--mantine-spacing-xl)',
};

const DashboardThumbnailView: React.FC<DashboardThumbnailViewProps> = ({
  groups,
  projectNames,
  projectTemplates,
  cardsPerRow = DEFAULT_CARDS_PER_ROW,
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
}) => {
  const cards = groups.map((group) => {
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
  });
  return cardsPerRow === 'auto' ? (
    <div style={AUTO_GRID_STYLE}>{cards}</div>
  ) : (
    <SimpleGrid cols={gridCols(cardsPerRow)} spacing="xl" verticalSpacing="xl">
      {cards}
    </SimpleGrid>
  );
};

export default DashboardThumbnailView;
