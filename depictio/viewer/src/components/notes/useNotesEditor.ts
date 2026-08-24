import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from '@mantine/tiptap';
import { useEditor } from '@tiptap/react';
import type { Editor } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import { saveDashboardNotes } from 'depictio-react-core';
import type { DashboardPermissions, DashboardPermissionsUser } from 'depictio-react-core';
import { useCurrentUser } from '../../hooks/useCurrentUser';

/**
 * The dashboard-notes editor, minus the surface it is shown on.
 *
 * Two surfaces render it: the bottom drawer (`NotesFooter`) and the inspector's
 * Notes tab. Only one of them is ever mounted — two live editors on the same
 * dashboard would each run their own debounced save and clobber each other.
 *
 * Content is persisted on the dashboard document's `notes_content` field via
 * `saveDashboardNotes` (GET → mutate → POST), one second after the user stops
 * typing.
 */
export type NotesSaveStatus = 'idle' | 'saving' | 'saved' | 'error';

const AUTO_SAVE_DEBOUNCE_MS = 1000;

export interface NotesEditorState {
  editor: Editor | null;
  /** Only dashboard owners may author; everyone else sees the same content
   *  read-only. The server authorizes the save endpoint regardless. */
  canEdit: boolean;
  status: NotesSaveStatus;
  savedAt: Date | null;
}

export function useNotesEditor(
  dashboardId: string,
  initialContent: string,
  permissions?: DashboardPermissions,
): NotesEditorState {
  const [status, setStatus] = useState<NotesSaveStatus>('idle');
  const [savedAt, setSavedAt] = useState<Date | null>(null);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Snapshot of the most-recently persisted content, so a no-op update (the
  // one TipTap fires right after mount) doesn't schedule a save.
  const lastSavedRef = useRef<string>(initialContent || '');

  // Loading state defaults to read-only — flipping editable later (see effect
  // below) is safer than a brief write window before auth resolves.
  const { user, loading: userLoading } = useCurrentUser();
  const canEdit = useMemo<boolean>(() => {
    if (userLoading || !user) return false;
    const owners = permissions?.owners ?? [];
    return owners.some((o: DashboardPermissionsUser) => {
      if (user.id && (o._id === user.id || o.id === user.id)) return true;
      if (user.email && o.email && o.email === user.email) return true;
      return false;
    });
  }, [permissions, user, userLoading]);

  // Read through a ref inside `onUpdate`: TipTap captures the callback once at
  // construction, so closing over `canEdit` directly would freeze it at its
  // pre-auth value and permanently block saves.
  const canEditRef = useRef(canEdit);
  canEditRef.current = canEdit;

  const scheduleSave = useCallback(
    (html: string) => {
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
            console.error('[notes] save failed:', err);
            setStatus('error');
          });
      }, AUTO_SAVE_DEBOUNCE_MS);
    },
    [dashboardId],
  );

  const editor = useEditor({
    extensions: [StarterKit, Link.configure({ openOnClick: false })],
    content: initialContent || '',
    editable: canEdit,
    onUpdate: ({ editor: ed }) => {
      if (!canEditRef.current) return;
      const html = ed.getHTML();
      if (html === lastSavedRef.current) return;
      scheduleSave(html);
    },
  });

  // TipTap caches `editable` from its initial options. When auth resolves and
  // the user turns out to own the dashboard, flip the live editor's state so
  // they can actually type. Same the other way round, for safety.
  useEffect(() => {
    if (!editor) return;
    if (editor.isEditable !== canEdit) editor.setEditable(canEdit);
  }, [editor, canEdit]);

  // When the parent re-fetches the dashboard and feeds in different content
  // (e.g. after a layout save), reflect it — but compare against lastSavedRef
  // first so a stale prop can't stomp on the user's in-flight edits.
  useEffect(() => {
    if (!editor) return;
    if (initialContent === undefined || initialContent === null) return;
    if (initialContent === lastSavedRef.current) return;
    if (initialContent === editor.getHTML()) return;
    lastSavedRef.current = initialContent;
    editor.commands.setContent(initialContent, false);
  }, [editor, initialContent]);

  useEffect(
    () => () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
    },
    [],
  );

  return { editor, canEdit, status, savedAt };
}

export default useNotesEditor;
