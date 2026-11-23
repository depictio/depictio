import React, { useEffect, useRef, useState } from 'react';
import { Stack, Text } from '@mantine/core';
import type { ReportLayer, ReportOutline } from 'depictio-react-core';

import { moveTab } from './model';
import type { TabView } from './model';
import TabBlock from './TabBlock';
import type { DropPosition } from './TileCard';

const TAB_DRAG_TYPE = 'application/x-depictio-tab';

interface StructurePanelProps {
  tabs: TabView[];
  outline: ReportOutline;
  selectedKey: string | null;
  /** Bumped when the preview selects a tile: the matching card scrolls into view. */
  revealToken: number;
  thumbs: Record<string, string>;
  fold: { open: boolean; n: number };
  onEdit: (change: (layer: ReportLayer) => ReportLayer) => void;
  onSelect: (tabId: string, componentId: string | null) => void;
}

/** The report's structure, tab by tab, as the dashboard lays it out. */
const StructurePanel: React.FC<StructurePanelProps> = ({
  tabs,
  outline,
  selectedKey,
  revealToken,
  thumbs,
  fold,
  onEdit,
  onSelect,
}) => {
  const rootRef = useRef<HTMLDivElement>(null);
  const [dragTab, setDragTab] = useState<string | null>(null);
  const [overTab, setOverTab] = useState<{ id: string; position: DropPosition } | null>(null);

  useEffect(() => {
    if (!revealToken || !selectedKey) return;
    const card = Array.from(
      rootRef.current?.querySelectorAll<HTMLElement>('[data-tile-key]') ?? [],
    ).find((el) => el.dataset.tileKey === selectedKey);
    card?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    // Only a new reveal request scrolls, not every selection change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [revealToken]);

  const endTabDrag = () => {
    setDragTab(null);
    setOverTab(null);
  };

  const dropTab = (targetIdx: number, position: DropPosition) => {
    const from = tabs.findIndex((t) => t.tabId === dragTab);
    endTabDrag();
    if (from < 1) return;
    let to = position === 'after' ? targetIdx + 1 : targetIdx;
    if (from < to) to -= 1;
    onEdit((l) => moveTab(l, tabs, from, to));
  };

  return (
    <Stack gap="md" ref={rootRef} data-testid="report-structure">
      {tabs.length === 0 && (
        <Text size="sm" c="dimmed">
          This dashboard has no components to put in a report.
        </Text>
      )}
      {tabs.map((tab, i) => {
        const outlineTab = outline.tabs.find((t) => t.tab_id === tab.tabId);
        return (
          <TabBlock
            key={tab.tabId}
            tab={tab}
            icon={outlineTab?.icon}
            color={outlineTab?.color}
            index={i}
            count={tabs.length}
            selectedKey={selectedKey}
            thumbs={thumbs}
            fold={fold}
            onEdit={onEdit}
            onSelect={onSelect}
            onMoveTab={(dir) => onEdit((l) => moveTab(l, tabs, i, i + dir))}
            tabDrag={{
              dragging: dragTab === tab.tabId,
              // Nothing lands before the main tab.
              indicator: overTab?.id === tab.tabId && i > 0 ? overTab.position : null,
              onDragStart: (e) => {
                e.dataTransfer.setData(TAB_DRAG_TYPE, tab.tabId);
                e.dataTransfer.effectAllowed = 'move';
                setDragTab(tab.tabId);
              },
              onDragOver: (e, position) => {
                if (!dragTab || i === 0) return;
                e.preventDefault();
                if (overTab?.id !== tab.tabId || overTab.position !== position) {
                  setOverTab({ id: tab.tabId, position });
                }
              },
              onDrop: (e) => {
                if (!dragTab || i === 0) return;
                e.preventDefault();
                dropTab(i, overTab?.id === tab.tabId ? overTab.position : 'before');
              },
              onDragEnd: endTabDrag,
            }}
          />
        );
      })}
    </Stack>
  );
};

export default StructurePanel;
