import React from 'react';
import { Box, Group, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import type { DashboardData, DashboardSummary } from 'depictio-react-core';

interface TabIntroProps {
  dashboard: DashboardData | null;
  /** The active tab in the sibling family — supplies the icon and its colour. */
  activeTab?: DashboardSummary | null;
}

/** True for path-like icon values (PNG/SVG file URLs) rather than Iconify names. */
function isImagePath(s: string | null | undefined): boolean {
  if (!s) return false;
  return /^(\/|https?:\/\/|data:)/.test(s) || /\.(png|svg|jpe?g|webp)$/i.test(s);
}

/**
 * The tab's own one-line description, at the top of the canvas.
 *
 * Every dashboard and tab already carries a `subtitle` — the YAML sets one per
 * tab, and the create/edit modals ask for one — but until now it was only ever
 * read on the dashboards listing. Inside the dashboard the tab was identified
 * by its name alone, so a reader landing on "Ordination & Clustering" got no
 * statement of what the tab is for unless the author had spent a grid row on a
 * text component saying so.
 *
 * Rendered above everything the canvas holds, which also fixes the ordering of
 * pinned sections: a `pin: top` section belonging to another tab lands *below*
 * the description of the tab being read, rather than ahead of it.
 *
 * Deliberately not a title: the header breadcrumb already names the tab, and
 * repeating it here would put the same words on screen three times over on
 * tabs whose first component is a heading.
 */
const TabIntro: React.FC<TabIntroProps> = ({ dashboard, activeTab }) => {
  const subtitle = typeof dashboard?.subtitle === 'string' ? dashboard.subtitle.trim() : '';
  if (!subtitle) return null;

  const iconRaw = (activeTab?.tab_icon || activeTab?.icon) ?? null;
  const iconColor = (activeTab?.tab_icon_color || activeTab?.icon_color) ?? 'gray';

  return (
    <Box px={6} pt={2} pb={6}>
      <Group gap={8} align="center" wrap="nowrap">
        {iconRaw && !isImagePath(iconRaw) && (
          <Icon
            icon={iconRaw}
            width={15}
            height={15}
            color={`var(--mantine-color-${iconColor}-6)`}
            style={{ flexShrink: 0 }}
          />
        )}
        <Text size="sm" c="dimmed" style={{ lineHeight: 1.35 }}>
          {subtitle}
        </Text>
      </Group>
    </Box>
  );
};

export default TabIntro;
