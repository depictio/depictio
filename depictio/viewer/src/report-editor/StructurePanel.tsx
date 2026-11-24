import React, { useEffect, useRef, useState } from 'react';
import { Stack, Text } from '@mantine/core';
import { BookOpen, Paperclip } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import type { ReportLayer, ReportOutline, ReportTabPlacement } from 'depictio-react-core';

import { STROKE } from '../chrome/variants/glass/icons';
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

/** The head of one part of the report: the main report, or the appendices. */
const PartHead: React.FC<{ icon: LucideIcon; title: string; hint: string; count: number }> = ({
  icon: I,
  title,
  hint,
  count,
}) => (
  <div className="re-parthead">
    <I size={15} strokeWidth={STROKE} aria-hidden />
    <span className="re-parthead-title">{title}</span>
    <span className="re-parthead-count">{count}</span>
    <span className="re-parthead-hint">{hint}</span>
  </div>
);

/** The report's structure in its two parts: the main report (the main tab
 *  first, then the tabs it reads through) and the appendices, printed after
 *  the closing. A tab changes part with its button or by dragging it into the
 *  other part. */
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
    // A tab dropped among the other part's tabs joins that part.
    onEdit((l) => moveTab(l, tabs, from, Math.max(1, to), tabs[targetIdx].placement));
  };

  // The tabs of each part, with their index in the whole list.
  const indexed = tabs.map((tab, i) => ({ tab, i }));
  const main = indexed.filter(({ tab }) => tab.placement !== 'appendix');
  const appendix = indexed.filter(({ tab }) => tab.placement === 'appendix');
  const firstAppendix = main.length;

  /** Into the other part: last of the main report, or first of the appendices. */
  const switchPart = (i: number) => {
    const tab = tabs[i];
    const target: ReportTabPlacement = tab.placement === 'appendix' ? 'body' : 'appendix';
    const to = target === 'appendix' ? firstAppendix - 1 : firstAppendix;
    onEdit((l) => moveTab(l, tabs, i, Math.max(1, to), target));
  };

  const [overAppendix, setOverAppendix] = useState(false);

  const renderTab = ({ tab, i }: { tab: (typeof tabs)[number]; i: number }) => {
        const outlineTab = outline.tabs.find((t) => t.tab_id === tab.tabId);
        const samePart = (j: number) => j >= 1 && j < tabs.length && tabs[j].placement === tab.placement;
        return (
          <TabBlock
            key={tab.tabId}
            tab={tab}
            icon={outlineTab?.icon}
            color={outlineTab?.color}
            canMoveUp={!tab.isMain && samePart(i - 1)}
            canMoveDown={!tab.isMain && samePart(i + 1)}
            selectedKey={selectedKey}
            thumbs={thumbs}
            fold={fold}
            onEdit={onEdit}
            onSelect={onSelect}
            onMoveTab={(dir) => onEdit((l) => moveTab(l, tabs, i, i + dir))}
            onSwitchPart={() => switchPart(i)}
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
  };

  return (
    <Stack gap="md" ref={rootRef} data-testid="report-structure">
      {tabs.length === 0 && (
        <Text size="sm" c="dimmed">
          This dashboard has no components to put in a report.
        </Text>
      )}
      {tabs.length > 0 && (
        <Stack gap="sm" data-testid="report-part-main">
          <PartHead
            icon={BookOpen}
            title="Main report"
            hint="Between the introduction and the closing"
            count={main.length}
          />
          {main.map(renderTab)}
        </Stack>
      )}
      {tabs.length > 1 && (
        <Stack gap="sm" data-testid="report-part-appendix">
          <PartHead
            icon={Paperclip}
            title="Appendices"
            hint="After the closing"
            count={appendix.length}
          />
          {appendix.map(renderTab)}
          {/* Always a place to drop a tab at the end of the appendices. */}
          <div
            className="re-partdrop"
            data-over={(dragTab && overAppendix) || undefined}
            data-empty={appendix.length === 0 || undefined}
            onDragOver={(e) => {
              if (!dragTab) return;
              e.preventDefault();
              setOverAppendix(true);
            }}
            onDragLeave={() => setOverAppendix(false)}
            onDrop={(e) => {
              if (!dragTab) return;
              e.preventDefault();
              setOverAppendix(false);
              const from = tabs.findIndex((t) => t.tabId === dragTab);
              endTabDrag();
              if (from >= 1) onEdit((l) => moveTab(l, tabs, from, tabs.length - 1, 'appendix'));
            }}
          >
            {appendix.length === 0
              ? 'No appendix yet: drag a tab here, or use its appendix button.'
              : 'Drop a tab here to add it last.'}
          </div>
        </Stack>
      )}
    </Stack>
  );
};

export default StructurePanel;
