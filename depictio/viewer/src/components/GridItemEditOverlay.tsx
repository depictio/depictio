import React, { useState } from 'react';
import { ActionIcon, Group, Menu, ScrollArea, Text, useComputedColorScheme } from '@mantine/core';
import { Icon } from '@iconify/react';
import {
  EDIT_MENU_STYLE,
  Glyph,
  canDuplicate,
  effectiveFit,
  SectionIcon,
  TILE_ACTION_STYLE,
  tabDisplayName,
  useBranding,
} from 'depictio-react-core';
import type { DashboardSummary, FilterSectionSpec } from 'depictio-react-core';
import { resolveTabColor, resolveTabIcon, tabImageSrc } from '../chrome/Sidebar';

/**
 * Edit menu rendered as a chrome action icon (passed via the
 * `extraActions` slot on `ComponentChrome`). Sits inside the same hover
 * cluster as metadata/fullscreen/download/reset — single z-index, single
 * hover state, no overlap with the input widget. Provides a Mantine Menu
 * with Edit / Duplicate / Delete actions:
 *
 *   - Edit:      navigates to the React edit page at
 *                /dashboard-edit/{id}/component/edit/{componentId}
 *   - Duplicate: fires `onDuplicate` — parent clones metadata + layout, POSTs /save
 *   - Copy to tab…: fires `onCopyToTab` — parent adds a copy to the picked
 *                sibling tab's document and saves that tab
 *   - Highlight on…: fires `onHighlightOnTab` — parent adds a highlight of
 *                this figure (a reference, not a copy) to the picked tab
 *   - Delete:    fires `onDelete` — parent is responsible for the actual API call
 *
 * "Move to section" is a second page inside the same dropdown rather than a
 * fourth action: the list is as long as the dashboard has sections, and it
 * would otherwise be the thing that pushes Delete off the bottom of a viewport.
 * "Copy to tab…" and "Highlight on…" open a page of sibling tabs the same way.
 *
 * Hidden via the `editMode` prop so the same renderer tree can be reused for
 * read-only mode.
 */

/** The types that publish a height of their own, the ones `fitLayoutHeights`
 *  has a policy for. Mirrors `FIT_POLICIES` in depictio-react-core's autofit. */
const AUTOFITTABLE_COMPONENT_TYPES = new Set([
  'text',
  'card',
  'table',
  'figure',
  'advanced_viz',
]);

/** Steps for the per-figure font-size multiplier. Wider than the
 *  dashboard-wide preference on purpose: axis labels on a dense figure are
 *  the case that motivates going up to 2×. */
const FONT_SCALE_STEPS = [0.7, 0.85, 1, 1.15, 1.3, 1.5, 1.75, 2];

function nearestStepIndex(scale: number): number {
  let best = FONT_SCALE_STEPS.indexOf(1);
  let bestDist = Infinity;
  FONT_SCALE_STEPS.forEach((step, idx) => {
    const dist = Math.abs(step - scale);
    if (dist < bestDist) {
      best = idx;
      bestDist = dist;
    }
  });
  return best;
}

interface GridItemEditOverlayProps {
  dashboardId: string;
  componentId: string;
  editMode: boolean;
  onDelete: (componentId: string) => void;
  /**
   * Optional duplicate handler. When omitted, the menu item is hidden so the
   * overlay degrades cleanly in callers that haven't wired the action yet.
   */
  onDuplicate?: (componentId: string) => void;
  /**
   * Component type from `stored_metadata`. Duplicate is only meaningful for
   * card/interactive/figure — other types (table/multiqc/text) hide the item.
   */
  componentType?: string;
  /**
   * Sections this component could join — the grid's list for a normal
   * component, the filter panel's for an interactive one. Omitted (with the
   * move actions hidden) by callers that don't manage sections. Full specs
   * rather than names so each entry can carry the section's own icon and
   * colour, which is how a section is recognised everywhere else.
   */
  sections?: FilterSectionSpec[];
  /** The section this component is currently in, if any. */
  currentSection?: string | null;
  /** `null` clears the section. Moving an interactive component moves its whole
   *  group; the caller is responsible for that. */
  onMoveToSection?: (componentId: string, section: string | null) => void;
  /** Size of the group that would move with this component, when > 1. Shown so
   *  the user isn't surprised that three controls moved rather than one. */
  groupSize?: number;
  /** Current per-component font-size multiplier (`font_scale` on the
   *  component's stored_metadata). Defaults to 1. */
  fontScale?: number;
  /** Fires with the new multiplier when the user steps the font-size control.
   *  Only rendered for figure components; omit to hide the control. */
  onFontScale?: (componentId: string, scale: number) => void;
  /** Sibling tabs this component can be copied to, the current one left out.
   *  The caller omits it for a type that cannot be copied (see
   *  `canCopyToTab`); omitted or empty hides "Copy to tab…". */
  copyTargets?: DashboardSummary[];
  onCopyToTab?: (componentId: string, targetDashboardId: string) => void;
  /** Tabs this figure can be highlighted on, the current one left out. The
   *  caller omits it for a component a highlight cannot show (see
   *  `canHighlight`); omitted or empty hides "Highlight on…". */
  highlightTargets?: DashboardSummary[];
  onHighlightOnTab?: (componentId: string, targetDashboardId: string) => void;
  /** Replaces the default "Edit" (a navigation to the builder). The Guide
   *  shows the real menu and says what each item does instead of doing it. */
  onEdit?: (componentId: string) => void;
  /** The component's `fit` (`stored_metadata.fit`). Undefined means the
   *  per-type default. */
  fit?: 'auto' | 'fixed' | null;
  /** Puts a tile back under autofit after a manual resize (or opts a figure
   *  in). Omit to hide the item. */
  onResetFit?: (componentId: string) => void;
}

const GridItemEditOverlay: React.FC<GridItemEditOverlayProps> = ({
  dashboardId,
  componentId,
  editMode,
  onDelete,
  onDuplicate,
  componentType,
  sections,
  currentSection,
  onMoveToSection,
  groupSize = 1,
  fontScale,
  onFontScale,
  copyTargets,
  onCopyToTab,
  highlightTargets,
  onHighlightOnTab,
  onEdit,
  fit,
  onResetFit,
}) => {
  // The dropdown shows one page at a time: the actions, the section list or
  // the tab list. A dashboard can declare any number of sections and tabs, and
  // a flat list would grow the menu until it ran off the viewport — the
  // actions the user reaches for most (Edit, Delete) would be the ones that
  // moved.
  const [page, setPage] = useState<'actions' | 'sections' | 'tabs' | 'highlight'>('actions');
  // Tabs are listed with the icon and colour their sidebar pill wears.
  const brand = useBranding();
  const isDark = useComputedColorScheme('light') === 'dark';

  if (!editMode) return null;

  const handleEdit = () => {
    if (onEdit) {
      onEdit(componentId);
      return;
    }
    window.location.assign(
      `/dashboard-edit/${dashboardId}/component/edit/${componentId}`,
    );
  };

  const handleDuplicate = () => {
    onDuplicate?.(componentId);
  };

  const handleDelete = () => {
    onDelete(componentId);
  };

  const showDuplicate = !!onDuplicate && !!componentType && canDuplicate(componentType);

  // No sections declared yet means nothing to move into — the Sections manager
  // is where that starts, so offering only "No section" here would be a dead
  // end.
  const showMoveToSection = !!onMoveToSection && !!sections?.length;

  const showCopyToTab = !!onCopyToTab && !!copyTargets?.length;
  const showHighlightOn = !!onHighlightOnTab && !!highlightTargets?.length;
  // "Size to content" is offered on the types that can answer with a height of
  // their own, and only when the tile is not already following its content  -
  // after a manual resize, or on a figure, which holds its authored aspect
  // ratio until someone asks for this.
  const showResetFit =
    !!onResetFit &&
    !!componentType &&
    AUTOFITTABLE_COMPONENT_TYPES.has(componentType) &&
    effectiveFit(componentType, fit) !== 'auto';

  // Per-figure font-size multiplier (#854 follow-up). Figures only: their
  // whole Plotly layout font (axis labels, ticks, legend) follows it.
  const showFontScale = !!onFontScale && componentType === 'figure';
  const currentScale = fontScale && fontScale > 0 ? fontScale : 1;
  const scaleIdx = nearestStepIndex(currentScale);
  const canScaleDown = scaleIdx > 0;
  const canScaleUp = scaleIdx < FONT_SCALE_STEPS.length - 1;

  // The tick goes on the right, so the section icons keep the left column and
  // every label starts at the same x — the icon is what identifies a section
  // at a glance, and it should read as the same mark as in the section header.
  const tick = (selected: boolean) =>
    selected ? <Icon icon="mdi:check" width={14} /> : undefined;

  return (
    <Menu
      position="bottom-end"
      withinPortal
      shadow="md"
      width={220}
      // Closing always lands back on the actions, so the menu never reopens
      // halfway through a move the user walked away from.
      onChange={(opened) => {
        if (!opened) setPage('actions');
      }}
    >
      <Menu.Target>
        <ActionIcon
          variant="subtle"
          size="sm"
          aria-label={TILE_ACTION_STYLE.menu.label}
          data-tile-action="menu"
        >
          <Icon icon={TILE_ACTION_STYLE.menu.icon} width={16} />
        </ActionIcon>
      </Menu.Target>
      <Menu.Dropdown>
        {page === 'actions' ? (
          <>
            <Menu.Item
              leftSection={<Icon icon={EDIT_MENU_STYLE.edit.icon} width={14} />}
              onClick={handleEdit}
            >
              {EDIT_MENU_STYLE.edit.label}
            </Menu.Item>
            {showDuplicate && (
              <Menu.Item
                leftSection={<Icon icon={EDIT_MENU_STYLE.duplicate.icon} width={14} />}
                onClick={handleDuplicate}
              >
                {EDIT_MENU_STYLE.duplicate.label}
              </Menu.Item>
            )}
            {showResetFit && (
              <Menu.Item
                leftSection={<Icon icon="tabler:arrow-autofit-height" width={14} />}
                onClick={() => onResetFit!(componentId)}
                data-testid="reset-auto-height"
              >
                Reset to auto height
              </Menu.Item>
            )}
            {showMoveToSection && (
              <Menu.Item
                // Opens the second page instead of firing an action, so the
                // menu has to stay open.
                closeMenuOnClick={false}
                leftSection={<Icon icon={EDIT_MENU_STYLE['move-section'].icon} width={14} />}
                rightSection={<Icon icon="mdi:chevron-right" width={14} />}
                onClick={() => setPage('sections')}
              >
                {EDIT_MENU_STYLE['move-section'].label}
              </Menu.Item>
            )}
            {showCopyToTab && (
              <Menu.Item
                closeMenuOnClick={false}
                leftSection={<Icon icon={EDIT_MENU_STYLE['copy-tab'].icon} width={14} />}
                rightSection={<Icon icon="mdi:chevron-right" width={14} />}
                onClick={() => setPage('tabs')}
              >
                {EDIT_MENU_STYLE['copy-tab'].label}
              </Menu.Item>
            )}
            {showHighlightOn && (
              <Menu.Item
                closeMenuOnClick={false}
                leftSection={<Icon icon={EDIT_MENU_STYLE.highlight.icon} width={14} />}
                rightSection={<Icon icon="mdi:chevron-right" width={14} />}
                onClick={() => setPage('highlight')}
                data-testid="highlight-on-tab"
              >
                {EDIT_MENU_STYLE.highlight.label}
              </Menu.Item>
            )}
            {showFontScale && (
              <>
                <Menu.Divider />
                <Menu.Label>{EDIT_MENU_STYLE['font-size'].label}</Menu.Label>
                {/* Inline control rather than Menu.Items so stepping A− / A+
                    doesn't close the menu between clicks. */}
                <Group gap={6} px="sm" pb={6} wrap="nowrap" data-testid="figure-font-scale">
                  <ActionIcon.Group>
                    <ActionIcon
                      variant="default"
                      size="sm"
                      disabled={!canScaleDown}
                      onClick={() => onFontScale!(componentId, FONT_SCALE_STEPS[scaleIdx - 1])}
                      data-testid="figure-font-scale-decrease"
                      aria-label="Decrease figure font size"
                    >
                      <Icon icon="mdi:format-font-size-decrease" width={14} />
                    </ActionIcon>
                    <ActionIcon
                      variant="default"
                      size="sm"
                      disabled={!canScaleUp}
                      onClick={() => onFontScale!(componentId, FONT_SCALE_STEPS[scaleIdx + 1])}
                      data-testid="figure-font-scale-increase"
                      aria-label="Increase figure font size"
                    >
                      <Icon icon={EDIT_MENU_STYLE['font-size'].icon} width={14} />
                    </ActionIcon>
                  </ActionIcon.Group>
                  <Text size="xs" c={currentScale === 1 ? 'dimmed' : undefined} w={38} ta="center">
                    {Math.round(currentScale * 100)}%
                  </Text>
                  {currentScale !== 1 && (
                    <ActionIcon
                      variant="subtle"
                      size="sm"
                      onClick={() => onFontScale!(componentId, 1)}
                      data-testid="figure-font-scale-reset"
                      aria-label="Reset figure font size"
                    >
                      <Icon icon="mdi:restore" width={14} />
                    </ActionIcon>
                  )}
                </Group>
              </>
            )}
            <Menu.Divider />
            <Menu.Item
              color={EDIT_MENU_STYLE.delete.color}
              leftSection={<Icon icon={EDIT_MENU_STYLE.delete.icon} width={14} />}
              onClick={handleDelete}
            >
              {EDIT_MENU_STYLE.delete.label}
            </Menu.Item>
          </>
        ) : page === 'tabs' || page === 'highlight' ? (
          <>
            <Menu.Item
              closeMenuOnClick={false}
              leftSection={<Icon icon="mdi:chevron-left" width={14} />}
              onClick={() => setPage('actions')}
            >
              Back
            </Menu.Item>
            <Menu.Divider />
            <Menu.Label>{page === 'tabs' ? 'Copy to tab' : 'Highlight on tab'}</Menu.Label>
            {page === 'highlight' && (
              <Text size="xs" c="dimmed" px="sm" pb={6} maw={220}>
                Shows this figure there, restyled; edits made here show there too.
              </Text>
            )}
            <ScrollArea.Autosize mah={240} type="auto">
              {(page === 'tabs' ? copyTargets : highlightTargets)?.map((tab) => {
                const isParent = !tab.parent_dashboard_id;
                // The same icon as the tab's sidebar pill, image icons included.
                const image = tabImageSrc(tab, isParent, isDark);
                return (
                  <Menu.Item
                    key={tab.dashboard_id}
                    leftSection={
                      image ? (
                        <img
                          src={image}
                          alt=""
                          width={14}
                          height={14}
                          style={{ objectFit: 'contain', display: 'block' }}
                        />
                      ) : (
                        <Glyph
                          icon={resolveTabIcon(tab, isParent)}
                          color={resolveTabColor(tab, isParent, brand)}
                          size={14}
                        />
                      )
                    }
                    onClick={() =>
                      page === 'tabs'
                        ? onCopyToTab?.(componentId, tab.dashboard_id)
                        : onHighlightOnTab?.(componentId, tab.dashboard_id)
                    }
                  >
                    {tabDisplayName(tab)}
                  </Menu.Item>
                );
              })}
            </ScrollArea.Autosize>
          </>
        ) : (
          // Second page: the section list, replacing the actions rather than
          // extending them. Mantine 7.17 ships `MenuSub` in the package but
          // does not export it, so a real nested menu isn't available.
          <>
            <Menu.Item
              closeMenuOnClick={false}
              leftSection={<Icon icon="mdi:chevron-left" width={14} />}
              onClick={() => setPage('actions')}
            >
              Back
            </Menu.Item>
            <Menu.Divider />
            <Menu.Label>
              {groupSize > 1
                ? `Move to section (all ${groupSize} in this group)`
                : 'Move to section'}
            </Menu.Label>
            {/* Bounded height rather than an unbounded list: a dashboard with a
                dozen sections would otherwise push the dropdown off screen. */}
            <ScrollArea.Autosize mah={240} type="auto">
              {sections?.map((spec) => (
                <Menu.Item
                  key={spec.name}
                  disabled={spec.name === currentSection}
                  // `fallbackIcon` so a section that never picked one still
                  // holds the column — otherwise its label alone would sit out
                  // of line.
                  leftSection={
                    <SectionIcon spec={spec} size={14} fallbackIcon="mdi:shape-outline" />
                  }
                  rightSection={tick(spec.name === currentSection)}
                  onClick={() => onMoveToSection?.(componentId, spec.name)}
                >
                  {spec.name}
                </Menu.Item>
              ))}
              <Menu.Item
                disabled={!currentSection}
                leftSection={<SectionIcon size={14} fallbackIcon="mdi:circle-off-outline" />}
                rightSection={tick(!currentSection)}
                onClick={() => onMoveToSection?.(componentId, null)}
              >
                No section
              </Menu.Item>
            </ScrollArea.Autosize>
          </>
        )}
      </Menu.Dropdown>
    </Menu>
  );
};

export default GridItemEditOverlay;
