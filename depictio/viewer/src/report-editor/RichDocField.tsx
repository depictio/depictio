import React, { useRef } from 'react';
import { Box, Text } from '@mantine/core';
import { useEditor } from '@tiptap/react';
import type { JSONContent } from '@tiptap/react';
import type { ReportDoc } from 'depictio-react-core';

import NotesEditorSurface from '../components/notes/NotesEditorSurface';
import { DOC_EXTENSIONS } from './docHtml';
import { isEmptyDoc } from './model';

interface RichDocFieldProps {
  label?: string;
  description?: string;
  /** The stored document. Read once per mount: the page remounts the field
   *  (a new `key`) when the layer is reloaded from the server. */
  value: ReportDoc | null;
  /** Called with the new document, or null once it holds no text. */
  onChange: (doc: ReportDoc | null) => void;
  testId?: string;
}

/**
 * A TipTap field that stores TipTap JSON, for the report's introduction and
 * conclusion. It reuses the notes editor's surface (toolbar and content area)
 * but not its hook: the notes save HTML to the dashboard document, and this
 * one hands JSON to the report layer's own autosave.
 */
const RichDocField: React.FC<RichDocFieldProps> = ({
  label,
  description,
  value,
  onChange,
  testId,
}) => {
  // What the editor last held, to tell a real edit from the update TipTap
  // emits while it normalises the document it was given.
  const lastRef = useRef<string>(JSON.stringify(isEmptyDoc(value) ? null : value));
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  const editor = useEditor({
    extensions: DOC_EXTENSIONS,
    content: isEmptyDoc(value) ? '' : (value as JSONContent),
    editable: true,
    onUpdate: ({ editor: ed }) => {
      const doc = ed.isEmpty ? null : (ed.getJSON() as ReportDoc);
      const serial = JSON.stringify(doc);
      if (serial === lastRef.current) return;
      lastRef.current = serial;
      onChangeRef.current(doc);
    },
  });

  return (
    <Box data-testid={testId}>
      {label && (
        <Text fw={500} size="sm">
          {label}
        </Text>
      )}
      {description && (
        <Text size="xs" c="dimmed" mb={6}>
          {description}
        </Text>
      )}
      <Box style={{ display: 'flex', flexDirection: 'column', height: 240 }}>
        <NotesEditorSurface editor={editor} canEdit />
      </Box>
    </Box>
  );
};

export default RichDocField;
