import React, { useEffect, useRef, useState } from 'react';
import { Group } from '@mantine/core';

import { StoredMetadata } from '../../api';
import MetadataPopover from './MetadataPopover';
import FullscreenButton from './FullscreenButton';
import DownloadButton from './DownloadButton';
import ResetButton from './ResetButton';
import './chrome.css';

export type ChromeAction = 'metadata' | 'fullscreen' | 'download' | 'reset';

export interface ComponentChromeProps {
  metadata: StoredMetadata;
  componentType: string;
  /** Title prop is ignored — renderers display their own titles. Kept for API parity. */
  title?: string;
  onResetFilter?: () => void;
  children: React.ReactNode;
  agGridApiRef?: React.RefObject<{ exportDataAsCsv: () => void } | null>;
  /** Element to fullscreen — defaults to the chrome wrapper itself. */
  fullscreenRef?: React.RefObject<HTMLDivElement | null>;
}

/** View-accessible action visibility per component type. Mirrors the
 *  view-accessible subset of `_create_component_buttons` in
 *  `depictio/dash/layouts/edit.py:236-428`. */
export function actionsFor(componentType: string): ChromeAction[] {
  switch (componentType) {
    case 'figure':
    case 'map':
    case 'multiqc':
      return ['metadata', 'fullscreen', 'download'];
    case 'table':
      return ['metadata', 'fullscreen', 'download'];
    case 'interactive':
      return ['metadata', 'reset'];
    case 'card':
    case 'image':
    case 'jbrowse':
      return ['metadata'];
    default:
      return ['metadata'];
  }
}

/**
 * Per-component action chrome. Renders the wrapped component as-is and adds a
 * floating, hover-revealed action-icon row at top-right. The chrome itself is
 * background-less so the renderer's own Paper/styling shows through.
 *
 * Fullscreen: the chrome wrapper itself is the fullscreen target. The Plotly
 * div is found via querySelector inside the wrapper — no prop drilling into
 * each renderer needed.
 */
const ComponentChrome: React.FC<ComponentChromeProps> = ({
  metadata,
  componentType,
  onResetFilter,
  children,
  agGridApiRef,
  fullscreenRef: externalFullscreenRef,
}) => {
  const localFullscreenRef = useRef<HTMLDivElement | null>(null);
  const fullscreenRef = externalFullscreenRef ?? localFullscreenRef;

  const [isFullscreenActive, setIsFullscreenActive] = useState(false);
  useEffect(() => {
    const onChange = () => {
      setIsFullscreenActive(document.fullscreenElement === fullscreenRef.current);
    };
    document.addEventListener('fullscreenchange', onChange);
    return () => document.removeEventListener('fullscreenchange', onChange);
  }, [fullscreenRef]);

  const actions = actionsFor(componentType);

  const renderAction = (action: ChromeAction) => {
    switch (action) {
      case 'metadata':
        return <MetadataPopover key="metadata" metadata={metadata} />;
      case 'fullscreen':
        return <FullscreenButton key="fullscreen" fullscreenRef={fullscreenRef} />;
      case 'download':
        return (
          <DownloadButton
            key="download"
            componentType={componentType}
            metadata={metadata}
            agGridApiRef={agGridApiRef}
            fullscreenRef={fullscreenRef}
          />
        );
      case 'reset':
        return <ResetButton key="reset" onResetFilter={onResetFilter} />;
    }
  };

  return (
    <div
      ref={fullscreenRef as React.RefObject<HTMLDivElement>}
      className={
        'depictio-component-chrome' +
        (isFullscreenActive ? ' fullscreen-active' : '')
      }
    >
      <Group gap={4} className="depictio-component-actions" wrap="nowrap">
        {actions.map(renderAction)}
      </Group>
      {children}
    </div>
  );
};

export default ComponentChrome;
