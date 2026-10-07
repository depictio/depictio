import React, { useLayoutEffect, useRef, useState } from 'react';
import { ActionIcon, Button, Divider, Group, Popover, Stack, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import { useAnnotationLayer } from '../../annotations/AnnotationLayerContext';
import type { AnnotationLayerControl, InlineAnnotationEdit } from '../../annotations/AnnotationLayerContext';
import { ANNOTATE_UI_ATTR } from '../../annotations/escape';
import { anchorOffset } from '../../annotations/inlineEdit';
import type { Annotation } from '../../annotations/types';
import { Z_LAYERS } from '../../zLayers';
import { AnnotationEditor } from './AnnotationEditor';

export interface InlineAnnotationEditorProps {
  /** The component this editor belongs to; it renders only while one of its annotations is edited. */
  componentIndex: string;
}

/**
 * Edits a saved annotation where it was clicked: a popover anchored at the
 * click, holding the annotation editor plus shortcuts to the thread's
 * discussion and to deleting it. Render inside the component's positioned
 * container (next to the annotate toolbar).
 */
const InlineAnnotationEditor: React.FC<InlineAnnotationEditorProps> = ({ componentIndex }) => {
  const layer = useAnnotationLayer();
  const editing = layer?.editing?.componentIndex === componentIndex ? layer.editing : null;
  const annotation = editing ? layer!.editingAnnotation : null;
  if (!layer || !editing || !annotation) return null;
  // A new click (another annotation, or the same one elsewhere) starts over.
  const key = `${editing.threadId}:${editing.anchor?.x ?? ''}:${editing.anchor?.y ?? ''}`;
  return <EditorPopover key={key} layer={layer} editing={editing} annotation={annotation} />;
};

interface EditorPopoverProps {
  layer: AnnotationLayerControl;
  editing: InlineAnnotationEdit;
  annotation: Annotation;
}

const EditorPopover: React.FC<EditorPopoverProps> = ({ layer, editing, annotation }) => {
  const frameRef = useRef<HTMLDivElement | null>(null);
  const [offset, setOffset] = useState<{ left: number; top: number } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  // The click is in viewport coords; the target sits in this frame (which
  // covers the component's positioned container).
  useLayoutEffect(() => {
    const frame = frameRef.current;
    if (!frame) return;
    const r = frame.getBoundingClientRect();
    setOffset(anchorOffset(editing.anchor, { left: r.left, top: r.top, width: r.width, height: r.height }));
  }, [editing.anchor]);

  // Rendered in the fullscreen element when there is one: a portal to <body>
  // would be invisible behind a fullscreen card.
  const portalTarget =
    typeof document !== 'undefined' && document.fullscreenElement
      ? (document.fullscreenElement as HTMLElement)
      : undefined;
  const stop = (e: React.SyntheticEvent) => e.stopPropagation();
  const { threadId } = editing;
  const onDraftChange = (patch: Parameters<AnnotationLayerControl['setEditDraft']>[1]) =>
    layer.setEditDraft(threadId, patch);

  const remove = async () => {
    if (!layer.deleteEdited || deleting) return;
    setDeleting(true);
    try {
      await layer.deleteEdited();
    } catch {
      // The app reports the failure; the editor stays open.
      setDeleting(false);
    }
  };

  return (
    <div ref={frameRef} style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}>
      <Popover
        opened={offset != null}
        onClose={layer.closeEditor}
        position="bottom"
        width={300}
        shadow="md"
        withArrow
        trapFocus
        zIndex={Z_LAYERS.tooltip}
        portalProps={portalTarget ? { target: portalTarget } : undefined}
      >
        <Popover.Target>
          <div
            aria-hidden
            style={{ position: 'absolute', left: offset?.left ?? 0, top: offset?.top ?? 0, width: 1, height: 1 }}
          />
        </Popover.Target>
        <Popover.Dropdown
          onMouseDown={stop}
          onPointerDown={stop}
          data-testid="inline-annotation-editor"
          {...{ [ANNOTATE_UI_ATTR]: '' }}
        >
          <Stack gap="xs">
            <AnnotationEditor
              annotation={annotation}
              onSave={layer.saveEdit}
              onCancel={layer.closeEditor}
              onDraftChange={onDraftChange}
            />
            {(layer.openDiscussion || layer.deleteEdited) && (
              <>
                <Divider />
                {confirmDelete ? (
                  <Group gap={6} justify="space-between" wrap="nowrap">
                    <Text size="xs" c="red">
                      Delete this annotation and its thread?
                    </Text>
                    <Group gap={6} wrap="nowrap">
                      <Button
                        size="compact-xs"
                        variant="subtle"
                        color="gray"
                        onClick={() => setConfirmDelete(false)}
                        disabled={deleting}
                      >
                        Cancel
                      </Button>
                      <Button
                        size="compact-xs"
                        color="red"
                        loading={deleting}
                        onClick={() => void remove()}
                        data-testid="inline-annotation-delete-confirm"
                      >
                        Delete
                      </Button>
                    </Group>
                  </Group>
                ) : (
                  <Group gap={6} justify="space-between" wrap="nowrap">
                    {layer.openDiscussion ? (
                      <Button
                        size="compact-xs"
                        variant="subtle"
                        leftSection={<Icon icon="mdi:comment-text-outline" width={14} />}
                        onClick={layer.openDiscussion}
                        data-testid="inline-annotation-discussion"
                      >
                        Open discussion
                      </Button>
                    ) : (
                      <span />
                    )}
                    {layer.deleteEdited && (
                      <Tooltip label="Delete annotation" withArrow openDelay={300} zIndex={Z_LAYERS.tooltip}>
                        <ActionIcon
                          size="sm"
                          variant="subtle"
                          color="red"
                          onClick={() => setConfirmDelete(true)}
                          aria-label="Delete annotation"
                          data-testid="inline-annotation-delete"
                        >
                          <Icon icon="mdi:trash-can-outline" width={14} />
                        </ActionIcon>
                      </Tooltip>
                    )}
                  </Group>
                )}
              </>
            )}
          </Stack>
        </Popover.Dropdown>
      </Popover>
    </div>
  );
};

export default InlineAnnotationEditor;
