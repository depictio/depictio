import React, { useState } from 'react';
import { ActionIcon, Menu, ScrollArea } from '@mantine/core';
import { Icon } from '@iconify/react';
import { SectionIcon } from 'depictio-react-core';
import type { FilterSectionSpec } from 'depictio-react-core';

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
 *   - Delete:    fires `onDelete` — parent is responsible for the actual API call
 *
 * "Move to section" is a second page inside the same dropdown rather than a
 * fourth action: the list is as long as the dashboard has sections, and it
 * would otherwise be the thing that pushes Delete off the bottom of a viewport.
 *
 * Hidden via the `editMode` prop so the same renderer tree can be reused for
 * read-only mode.
 */
const DUPLICATABLE_COMPONENT_TYPES = new Set(['card', 'interactive', 'figure']);

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
}) => {
  // The dropdown shows one page at a time: the actions, or the section list.
  // A dashboard can declare any number of sections, and a flat list would grow
  // the menu until it ran off the viewport — the actions the user reaches for
  // most (Edit, Delete) would be the ones that moved.
  const [page, setPage] = useState<'actions' | 'sections'>('actions');

  if (!editMode) return null;

  const handleEdit = () => {
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

  const showDuplicate =
    !!onDuplicate &&
    !!componentType &&
    DUPLICATABLE_COMPONENT_TYPES.has(componentType);

  // No sections declared yet means nothing to move into — the Sections manager
  // is where that starts, so offering only "No section" here would be a dead
  // end.
  const showMoveToSection = !!onMoveToSection && !!sections?.length;

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
        <ActionIcon variant="subtle" size="sm" aria-label="Component actions">
          <Icon icon="tabler:dots-vertical" width={16} />
        </ActionIcon>
      </Menu.Target>
      <Menu.Dropdown>
        {page === 'actions' ? (
          <>
            <Menu.Item
              leftSection={<Icon icon="tabler:edit" width={14} />}
              onClick={handleEdit}
            >
              Edit
            </Menu.Item>
            {showDuplicate && (
              <Menu.Item
                leftSection={<Icon icon="tabler:copy" width={14} />}
                onClick={handleDuplicate}
              >
                Duplicate
              </Menu.Item>
            )}
            {showMoveToSection && (
              <Menu.Item
                // Opens the second page instead of firing an action, so the
                // menu has to stay open.
                closeMenuOnClick={false}
                leftSection={<Icon icon="mdi:format-list-group" width={14} />}
                rightSection={<Icon icon="mdi:chevron-right" width={14} />}
                onClick={() => setPage('sections')}
              >
                Move to section
              </Menu.Item>
            )}
            <Menu.Divider />
            <Menu.Item
              color="red"
              leftSection={<Icon icon="tabler:trash" width={14} />}
              onClick={handleDelete}
            >
              Delete
            </Menu.Item>
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
