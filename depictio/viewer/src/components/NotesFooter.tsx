/*
 * NotesFooter — dashboard-wide rich-text notes drawer.
 *
 * Mirrors the Dash equivalent at depictio/dash/layouts/notes_footer.py but
 * reimplemented natively in React + Mantine. The toggle button is a fixed
 * floating control anchored bottom-right; clicking it opens a Mantine Drawer
 * (position="bottom") containing the shared notes editor.
 *
 * The editor itself — TipTap instance, permission gate and debounced autosave —
 * lives in `notes/useNotesEditor`, shared with the inspector's Notes tab. Only
 * one of the two surfaces is mounted at a time: two live editors on the same
 * dashboard would each run their own save and clobber each other, which is why
 * the app drops this footer when the inspector is enabled.
 *
 * Drawer open/closed state is persisted per dashboard in localStorage under
 * `notes-footer-open:{dashboardId}` so a reload preserves the user's choice.
 */
import React, { useCallback, useState } from 'react';
import { ActionIcon, Drawer, Group, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';
import type { DashboardPermissions } from 'depictio-react-core';
import { useNotesEditor } from './notes/useNotesEditor';
import NotesEditorSurface, { NotesSaveStatusIndicator } from './notes/NotesEditorSurface';

interface NotesFooterProps {
  dashboardId: string;
  initialContent: string;
  /** Dashboard permissions block (owners / editors / viewers). Used to gate
   *  the editor: only owners can author notes; everyone else gets a read-only
   *  view of the same content. Server still authorizes the underlying save
   *  endpoint; this is a UI-level affordance. */
  permissions?: DashboardPermissions;
}

const STORAGE_KEY_PREFIX = 'notes-footer-open:';

function readStoredOpen(dashboardId: string): boolean {
  try {
    return localStorage.getItem(`${STORAGE_KEY_PREFIX}${dashboardId}`) === '1';
  } catch {
    return false;
  }
}

function writeStoredOpen(dashboardId: string, open: boolean): void {
  try {
    localStorage.setItem(`${STORAGE_KEY_PREFIX}${dashboardId}`, open ? '1' : '0');
  } catch {
    // ignore quota / private mode
  }
}

const NotesFooter: React.FC<NotesFooterProps> = ({
  dashboardId,
  initialContent,
  permissions,
}) => {
  const [opened, setOpened] = useState<boolean>(() => readStoredOpen(dashboardId));
  const [fullscreen, setFullscreen] = useState<boolean>(false);
  const { editor, canEdit, status, savedAt } = useNotesEditor(
    dashboardId,
    initialContent,
    permissions,
  );

  const handleToggle = useCallback(() => {
    setOpened((prev) => {
      const next = !prev;
      writeStoredOpen(dashboardId, next);
      return next;
    });
  }, [dashboardId]);

  const handleClose = useCallback(() => {
    setOpened(false);
    setFullscreen(false);
    writeStoredOpen(dashboardId, false);
  }, [dashboardId]);

  return (
    <>
      {/* Fixed floating toggle button, anchored bottom-right. Stays visible at
       *  all times so the user can open the notes from anywhere on the page. */}
      <Tooltip label="Dashboard notes" position="left" withArrow>
        <ActionIcon
          aria-label="Toggle dashboard notes"
          onClick={handleToggle}
          variant="filled"
          color="gray"
          size="lg"
          radius="xl"
          style={{
            position: 'fixed',
            bottom: 16,
            right: 16,
            zIndex: 200,
            boxShadow: '0 2px 8px rgba(0, 0, 0, 0.15)',
          }}
        >
          <Icon icon="material-symbols:edit-note" width={22} />
        </ActionIcon>
      </Tooltip>

      <Drawer
        opened={opened}
        onClose={handleClose}
        position="bottom"
        size={fullscreen ? '100%' : 420}
        padding="md"
        withCloseButton={false}
        title={
          <Group justify="space-between" align="center" wrap="nowrap" w="100%">
            <Group gap="xs" align="center">
              <Icon icon="material-symbols:edit-note" width={20} />
              <Text fw={600}>Notes &amp; Documentation</Text>
              <NotesSaveStatusIndicator status={status} savedAt={savedAt} canEdit={canEdit} />
            </Group>
            <Group gap={4} wrap="nowrap">
              <Tooltip
                label={fullscreen ? 'Restore size' : 'Fullscreen'}
                position="left"
                withArrow
              >
                <ActionIcon
                  variant="subtle"
                  color="gray"
                  size="sm"
                  onClick={() => setFullscreen((f) => !f)}
                  aria-label={fullscreen ? 'Restore notes drawer' : 'Expand notes to fullscreen'}
                >
                  <Icon
                    icon={
                      fullscreen
                        ? 'material-symbols:close-fullscreen'
                        : 'material-symbols:open-in-full'
                    }
                    width={18}
                  />
                </ActionIcon>
              </Tooltip>
              <Tooltip label="Close notes" position="left" withArrow>
                <ActionIcon
                  variant="subtle"
                  color="gray"
                  size="sm"
                  onClick={handleClose}
                  aria-label="Close notes"
                >
                  <Icon icon="material-symbols:close" width={18} />
                </ActionIcon>
              </Tooltip>
            </Group>
          </Group>
        }
        styles={{
          title: { width: '100%' },
          // Flex column body so the editor can stretch to fill the drawer and
          // its content area scrolls independently of the toolbar.
          body: {
            paddingTop: 8,
            display: 'flex',
            flexDirection: 'column',
            flex: 1,
            minHeight: 0,
          },
          content: {
            display: 'flex',
            flexDirection: 'column',
          },
        }}
      >
        <NotesEditorSurface editor={editor} canEdit={canEdit} />
      </Drawer>
    </>
  );
};

export default NotesFooter;
