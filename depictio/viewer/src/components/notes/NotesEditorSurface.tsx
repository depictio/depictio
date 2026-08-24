import React from 'react';
import { Badge, Text } from '@mantine/core';
import { Icon } from '@iconify/react';
import { RichTextEditor } from '@mantine/tiptap';
import type { Editor } from '@tiptap/react';
import type { NotesSaveStatus } from './useNotesEditor';

function formatTime(d: Date): string {
  return d.toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

interface SaveStatusIndicatorProps {
  status: NotesSaveStatus;
  savedAt: Date | null;
  canEdit: boolean;
}

/** Autosave feedback, or the reason there won't be any. */
export const NotesSaveStatusIndicator: React.FC<SaveStatusIndicatorProps> = ({
  status,
  savedAt,
  canEdit,
}) => {
  if (!canEdit) {
    return (
      <Badge variant="light" color="gray" size="xs" leftSection={<Icon icon="mdi:lock" width={10} />}>
        Read-only
      </Badge>
    );
  }
  if (status === 'idle') return null;
  let label: string;
  switch (status) {
    case 'saving':
      label = 'Saving…';
      break;
    case 'saved':
      label = savedAt ? `Saved at ${formatTime(savedAt)}` : 'Saved';
      break;
    case 'error':
      label = 'Save failed';
      break;
  }
  return (
    <Text size="xs" c={status === 'error' ? 'red' : 'dimmed'} ml="xs">
      {label}
    </Text>
  );
};

interface NotesEditorSurfaceProps {
  editor: Editor | null;
  canEdit: boolean;
}

/**
 * The rich-text editor itself, sized to fill whatever flex container it is
 * dropped into — the bottom drawer or the inspector's Notes tab.
 *
 * The toolbar is hidden for read-only viewers: none of its controls would do
 * anything, and hiding it gives the content more room.
 */
const NotesEditorSurface: React.FC<NotesEditorSurfaceProps> = ({ editor, canEdit }) => (
  <RichTextEditor
    editor={editor}
    style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}
  >
    {canEdit && (
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
    )}
    <RichTextEditor.Content style={{ flex: 1, minHeight: 0, overflowY: 'auto' }} />
  </RichTextEditor>
);

export default NotesEditorSurface;
