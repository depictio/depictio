import React from 'react';
import { Center } from '@mantine/core';

/**
 * Dashed-border click-to-upload target. Mirrors the Dash dcc.Upload styling
 * at depictio/dash/layouts/layouts_toolbox.py:374-386. Used by the dashboard
 * import flow and the new DC-creation modals.
 *
 * For drag-and-drop with folder traversal, pair this with a
 * `useFolderDropzone` hook that owns the drop handler — this component
 * only renders the dashed box.
 */
export const UnstyledDropZone = React.forwardRef<
  HTMLButtonElement,
  React.ButtonHTMLAttributes<HTMLButtonElement> & {
    children: React.ReactNode;
    /** Visual state when a drag is currently over the zone. */
    active?: boolean;
  }
>(({ children, active, style, ...rest }, ref) => (
  <button
    type="button"
    ref={ref}
    {...rest}
    style={{
      width: '100%',
      borderWidth: 2,
      borderStyle: 'dashed',
      borderRadius: 8,
      borderColor: active
        ? 'var(--mantine-color-blue-filled)'
        : 'var(--mantine-color-default-border)',
      padding: '40px 20px',
      cursor: 'pointer',
      background: active ? 'var(--mantine-color-blue-light)' : 'transparent',
      color: 'inherit',
      transition: 'border-color 120ms, background-color 120ms',
      ...style,
    }}
  >
    <Center>{children}</Center>
  </button>
));
UnstyledDropZone.displayName = 'UnstyledDropZone';

export default UnstyledDropZone;
