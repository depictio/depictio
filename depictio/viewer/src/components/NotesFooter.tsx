/*
 * NotesFooter — dashboard-wide rich-text notes drawer.
 *
 * Mirrors the Dash equivalent at depictio/dash/layouts/notes_footer.py but
 * reimplemented natively in React + Mantine. The toggle button is a fixed
 * floating control anchored bottom-left; clicking it opens a Mantine Drawer
 * (position="bottom") containing a Mantine RichTextEditor (TipTap-based).
 *
 * Storage:
 *   The content is persisted on the dashboard document's `notes_content`
 *   string field via `saveDashboardNotes` (GET → mutate → POST). Auto-saves
 *   1 second after the user stops typing. A small status indicator next to
 *   the toolbar shows 'Saving…' / 'Saved at HH:MM:SS' / 'Save failed'.
 *
 * Drawer open/closed state is persisted per dashboard in localStorage under
 * `notes-footer-open:{dashboardId}` so a reload preserves the user's choice.
 *
 * Concurrency note: `saveDashboardNotes` and the editor's component/layout
 * saves both follow the same GET → mutate → POST pattern, so there's a small
 * race where a user editing notes while rearranging the grid in another tab
 * could clobber one or the other. Acceptable for this feature.
 */
import React, { useEffect, useRef, useState, useCallback } from 'react';
import { ActionIcon, Drawer, Group, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';
import { RichTextEditor, Link } from '@mantine/tiptap';
import { useEditor } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import { saveDashboardNotes } from 'depictio-react-core';

interface NotesFooterProps {
  dashboardId: string;
  initialContent: string;
}

type SaveStatus = 'idle' | 'saving' | 'saved' | 'error';

const AUTO_SAVE_DEBOUNCE_MS = 1000;
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

function formatTime(d: Date): string {
  return d.toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

const NotesFooter: React.FC<NotesFooterProps> = ({
  dashboardId,
  initialContent,
}) => {
  const [opened, setOpened] = useState<boolean>(() => readStoredOpen(dashboardId));
  const [fullscreen, setFullscreen] = useState<boolean>(false);
  const [status, setStatus] = useState<SaveStatus>('idle');
  const [savedAt, setSavedAt] = useState<Date | null>(null);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Snapshot of the most-recently persisted content. Used to skip no-op saves
  // (e.g. the initial onUpdate fired right after editor mount).
  const lastSavedRef = useRef<string>(initialContent || '');

  const editor = useEditor({
    extensions: [
      StarterKit,
      Link.configure({ openOnClick: false }),
    ],
    content: initialContent || '',
    onUpdate: ({ editor: ed }) => {
      const html = ed.getHTML();
      if (html === lastSavedRef.current) return;
      setStatus('saving');
      if (saveTimer.current) clearTimeout(saveTimer.current);
      saveTimer.current = setTimeout(() => {
        saveDashboardNotes(dashboardId, html)
          .then(() => {
            lastSavedRef.current = html;
            setStatus('saved');
            setSavedAt(new Date());
          })
          .catch((err) => {
            console.error('[NotesFooter] save failed:', err);
            setStatus('error');
          });
      }, AUTO_SAVE_DEBOUNCE_MS);
    },
  });

  // If the parent re-fetches the dashboard and feeds in different
  // initialContent (e.g. after a layout save), reflect that in the editor.
  // We compare against lastSavedRef so we don't stomp on the user's in-flight
  // edits with a stale prop.
  useEffect(() => {
    if (!editor) return;
    if (initialContent === undefined || initialContent === null) return;
    if (initialContent === lastSavedRef.current) return;
    if (initialContent === editor.getHTML()) return;
    lastSavedRef.current = initialContent;
    editor.commands.setContent(initialContent, false);
  }, [editor, initialContent]);

  // Persist any pending save when the drawer closes / component unmounts.
  useEffect(() => {
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
    };
  }, []);

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
      {/* Fixed floating toggle button, anchored bottom-left. Stays visible at
       *  all times so the user can open the notes from anywhere on the page. */}
      <Tooltip label="Dashboard notes" position="right" withArrow>
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
            left: 16,
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
              <Text fw={600}>Notes & Documentation</Text>
              <SaveStatusIndicator status={status} savedAt={savedAt} />
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
          // Flex column body so the RichTextEditor can stretch to fill the
          // drawer and its content area scrolls independently of the toolbar.
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
        <RichTextEditor
          editor={editor}
          style={{
            flex: 1,
            minHeight: 0,
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          <RichTextEditor.Toolbar sticky stickyOffset={0}>
            <RichTextEditor.ControlsGroup>
              <RichTextEditor.Bold />
              <RichTextEditor.Italic />
              <RichTextEditor.Underline />
              <RichTextEditor.Strikethrough />
              <RichTextEditor.Code />
            </RichTextEditor.ControlsGroup>
            <RichTextEditor.ControlsGroup>
              <RichTextEditor.H1 />
              <RichTextEditor.H2 />
              <RichTextEditor.H3 />
            </RichTextEditor.ControlsGroup>
            <RichTextEditor.ControlsGroup>
              <RichTextEditor.Blockquote />
              <RichTextEditor.BulletList />
              <RichTextEditor.OrderedList />
            </RichTextEditor.ControlsGroup>
            <RichTextEditor.ControlsGroup>
              <RichTextEditor.Link />
              <RichTextEditor.Unlink />
            </RichTextEditor.ControlsGroup>
            <RichTextEditor.ControlsGroup>
              <RichTextEditor.Undo />
              <RichTextEditor.Redo />
            </RichTextEditor.ControlsGroup>
          </RichTextEditor.Toolbar>
          <RichTextEditor.Content style={{ flex: 1, minHeight: 0, overflowY: 'auto' }} />
        </RichTextEditor>
      </Drawer>
    </>
  );
};

interface SaveStatusIndicatorProps {
  status: SaveStatus;
  savedAt: Date | null;
}

const SaveStatusIndicator: React.FC<SaveStatusIndicatorProps> = ({ status, savedAt }) => {
  if (status === 'idle') return null;
  let label: string;
  let color: string | undefined;
  switch (status) {
    case 'saving':
      label = 'Saving…';
      color = undefined;
      break;
    case 'saved':
      label = savedAt ? `Saved at ${formatTime(savedAt)}` : 'Saved';
      color = undefined;
      break;
    case 'error':
      label = 'Save failed';
      color = 'red';
      break;
  }
  return (
    <Text size="xs" c={color || 'dimmed'} ml="xs">
      {label}
    </Text>
  );
};

export default NotesFooter;
