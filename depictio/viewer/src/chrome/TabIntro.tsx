import React from 'react';
import { Box, Divider, Group, Text, Title, useMantineColorScheme } from '@mantine/core';
import { Icon } from '@iconify/react';

import { isImagePath, themedIconSrc } from 'depictio-react-core';
import type { DashboardData, DashboardSummary } from 'depictio-react-core';

interface TabIntroProps {
  dashboard: DashboardData | null;
  /** The active tab in the sibling family — supplies the name, icon and colour. */
  activeTab?: DashboardSummary | null;
}

/**
 * The canvas header: what this tab is called, and what it is for.
 *
 * Both halves already existed in the data and neither was ever shown here.
 * The name was only in the app header's breadcrumb — which reads as chrome,
 * not as the title of the page — and the `subtitle` every tab carries was only
 * read on the dashboards listing, so authors had to spend a grid row on a text
 * component to say what a tab holds, and most tabs simply did not say.
 *
 * Rendered above everything the canvas holds, which also settles the ordering
 * of pinned sections: a `pin: top` section belonging to another tab lands
 * below this tab's own title rather than ahead of it.
 *
 * The description is child-tabs-only. On a parent document `subtitle` holds
 * the DASHBOARD's identity line — what the listing card shows under the title
 * — which is a statement about the whole family, not about the tab being read.
 */
const TabIntro: React.FC<TabIntroProps> = ({ dashboard, activeTab }) => {
  const { colorScheme } = useMantineColorScheme();
  const isDark = colorScheme === 'dark';
  // A tab that opens on its own title (a landing page's study name) opts out:
  // "Overview" above it would be the largest and least informative line.
  if (dashboard?.show_tab_header === false) return null;
  const isChildTab = Boolean(activeTab?.parent_dashboard_id ?? dashboard?.parent_dashboard_id);
  // The parent pill carries its own label ("MultiQC"), distinct from the
  // dashboard title the breadcrumb already shows.
  const name = isChildTab
    ? activeTab?.title || (dashboard?.title as string | undefined)
    : activeTab?.main_tab_name || activeTab?.title;
  const subtitle = typeof dashboard?.subtitle === 'string' ? dashboard.subtitle.trim() : '';
  const description = isChildTab ? subtitle : '';
  if (!name && !description) return null;

  const iconRaw = (activeTab?.tab_icon || activeTab?.icon) ?? null;
  const iconColor = (activeTab?.tab_icon_color || activeTab?.icon_color) ?? 'gray';
  // Image-path icons (the workflow logos) render as an <img>; dropping them
  // left the MultiQC tab — whose icon is only ever a logo — with a bare title.
  const iconImageSrc = iconRaw && isImagePath(iconRaw) ? themedIconSrc(iconRaw, isDark) : null;
  const showIcon = Boolean(iconRaw);

  return (
    <Box px={0} pt={4} pb={10}>
      <Group gap={10} align="center" wrap="nowrap">
        {iconImageSrc ? (
          <img
            src={iconImageSrc}
            alt=""
            width={24}
            height={24}
            style={{ flexShrink: 0, objectFit: 'contain' }}
          />
        ) : (
          iconRaw && (
            <Icon
              icon={iconRaw}
              width={24}
              height={24}
              color={`var(--mantine-color-${iconColor}-6)`}
              style={{ flexShrink: 0 }}
            />
          )
        )}
        {name && (
          // The page's own title: the largest heading on the canvas, so a
          // text tile's heading below it reads as part of the page.
          <Title order={2} fw={700} style={{ minWidth: 0, lineHeight: 1.2 }}>
            {name}
          </Title>
        )}
      </Group>
      {description && (
        <Text
          size="sm"
          c="dimmed"
          mt={2}
          /* Aligned under the title rather than the icon — the icon is a
             marker for the title, not a bullet for the paragraph. */
          ml={showIcon ? 34 : 0}
          style={{ lineHeight: 1.4 }}
        >
          {description}
        </Text>
      )}
      <Divider mt={8} />
    </Box>
  );
};

export default TabIntro;
