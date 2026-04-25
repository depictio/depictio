import React, { useCallback } from 'react';
import { PanelGroup, Panel, PanelResizeHandle } from 'react-resizable-panels';

/**
 * Thin wrapper over `react-resizable-panels` that provides:
 *   - a left filter panel (default 28%, min 20%, max 45%)
 *   - a right component grid panel
 *   - a 4px draggable divider with hover/drag visual states
 *   - persisted size in localStorage["depictio.editor.leftPanelSize"]
 *
 * Used by the editor to give users a resizable split between filter chrome
 * (left) and the grid of viz components (right). The right panel takes the
 * remainder of available width.
 */
const STORAGE_KEY = 'depictio.editor.leftPanelSize';
const DEFAULT_SIZE = 28;
const MIN_SIZE = 20;
const MAX_SIZE = 45;

interface PanelSplitterProps {
  left: React.ReactNode;
  right: React.ReactNode;
}

function readStoredSize(): number {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_SIZE;
    const parsed = parseFloat(raw);
    if (!Number.isFinite(parsed)) return DEFAULT_SIZE;
    if (parsed < MIN_SIZE || parsed > MAX_SIZE) return DEFAULT_SIZE;
    return parsed;
  } catch {
    return DEFAULT_SIZE;
  }
}

const PanelSplitter: React.FC<PanelSplitterProps> = ({ left, right }) => {
  const initialLeft = readStoredSize();

  const handleLayout = useCallback((sizes: number[]) => {
    if (!Array.isArray(sizes) || sizes.length === 0) return;
    try {
      localStorage.setItem(STORAGE_KEY, String(sizes[0]));
    } catch {
      // ignore storage errors (private mode, quota, etc.)
    }
  }, []);

  return (
    <PanelGroup direction="horizontal" onLayout={handleLayout} style={{ height: '100%' }}>
      <Panel defaultSize={initialLeft} minSize={MIN_SIZE} maxSize={MAX_SIZE}>
        <div style={{ height: '100%', overflow: 'auto' }}>{left}</div>
      </Panel>
      <PanelResizeHandle
        className="depictio-resize-handle"
        style={{
          width: 4,
          background: 'var(--mantine-color-gray-3)',
          cursor: 'col-resize',
          transition: 'background 120ms ease',
        }}
      >
        {/* Empty content; CSS handles hover/drag styles */}
        <div style={{ width: '100%', height: '100%' }} />
      </PanelResizeHandle>
      <Panel>
        <div style={{ height: '100%', overflow: 'auto' }}>{right}</div>
      </Panel>
    </PanelGroup>
  );
};

export default PanelSplitter;
