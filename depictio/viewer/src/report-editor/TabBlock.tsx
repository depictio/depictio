import React, { useEffect, useState } from 'react';
import { ActionIcon, Badge, Box, Collapse, SegmentedControl, Stack, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';
import { ArrowDown, ArrowUp, ChevronRight, GripVertical, Pin } from 'lucide-react';
import type { ReportLayer, ReportTabPlacement } from 'depictio-react-core';

import { STROKE } from '../chrome/variants/glass/icons';
import InspectorSlot from './InspectorSlot';
import { patchTile, relocateTile, setTabPlacement } from './model';
import type { TabView, TileView } from './model';
import SectionBlock from './SectionBlock';
import TileCard from './TileCard';
import type { DropPosition } from './TileCard';
import TileInspector from './TileInspector';
import TileGrid from './tiles/TileGrid';
import { tabIconId, tabTint } from './visuals';

/** Drag handlers of the tab's own header, from the panel that orders tabs. */
export interface TabDragProps {
  dragging: boolean;
  indicator: DropPosition | null;
  onDragStart: (event: React.DragEvent) => void;
  onDragOver: (event: React.DragEvent, position: DropPosition) => void;
  onDrop: (event: React.DragEvent) => void;
  onDragEnd: () => void;
}

interface TabBlockProps {
  tab: TabView;
  icon: string | null | undefined;
  color: string | null | undefined;
  /** Position among the report's tabs: 0 is the main tab, fixed in place. */
  index: number;
  count: number;
  /** `tab_id:component_id` of the selected tile, or null. */
  selectedKey: string | null;
  thumbs: Record<string, string>;
  /** Expand all / Collapse all: a new `n` sets every panel of the tab to `open`. */
  fold: { open: boolean; n: number };
  tabDrag: TabDragProps;
  onEdit: (change: (layer: ReportLayer) => ReportLayer) => void;
  onMoveTab: (direction: -1 | 1) => void;
  onSelect: (tabId: string, componentId: string | null) => void;
}

const TILE_DRAG_TYPE = 'application/x-depictio-tile';

/** The tab's rows in order, cut where the section changes. A row keeps its
 *  index in the tab: dragging and moving work on those. */
interface Run {
  section: string | null;
  rows: { view: TileView; i: number }[];
}

function runsOf(tiles: TileView[]): Run[] {
  const runs: Run[] = [];
  tiles.forEach((view, i) => {
    const last = runs[runs.length - 1];
    if (last && last.section === view.section) last.rows.push({ view, i });
    else runs.push({ section: view.section, rows: [{ view, i }] });
  });
  return runs;
}

/** One tab of the report, drawn like the dashboard's own: its icon in its
 *  colour, its title, and below it the components as small cards. */
const TabBlock: React.FC<TabBlockProps> = ({
  tab,
  icon,
  color,
  index,
  count,
  selectedKey,
  thumbs,
  fold,
  tabDrag,
  onEdit,
  onMoveTab,
  onSelect,
}) => {
  // The main tab starts open, the others closed; every section starts open.
  const [open, setOpen] = useState(index === 0);
  const [sectionOpen, setSectionOpen] = useState<Record<string, boolean>>({});
  const [sectionDefault, setSectionDefault] = useState(true);
  const [dragId, setDragId] = useState<string | null>(null);
  const [over, setOver] = useState<{ id: string; position: DropPosition } | null>(null);
  const inReport = tab.tiles.filter((t) => t.inReport).length;
  const runs = runsOf(tab.tiles);
  const isSectionOpen = (name: string) => sectionOpen[name] ?? sectionDefault;

  useEffect(() => {
    if (!fold.n) return;
    setOpen(fold.open);
    setSectionDefault(fold.open);
    setSectionOpen({});
    // Only a new fold request applies, not a re-render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fold.n]);

  // A tile picked in the preview opens the tab and the section it sits in.
  useEffect(() => {
    const picked = tab.tiles.find((t) => `${t.tabId}:${t.componentId}` === selectedKey);
    if (!picked) return;
    setOpen(true);
    if (picked.section) setSectionOpen((prev) => ({ ...prev, [picked.section as string]: true }));
    // Only a change of selection opens panels.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedKey]);

  const endTileDrag = () => {
    setDragId(null);
    setOver(null);
  };

  const dropOn = (targetIdx: number, position: DropPosition) => {
    const from = tab.tiles.findIndex((t) => t.componentId === dragId);
    endTileDrag();
    if (from < 0) return;
    let to = position === 'after' ? targetIdx + 1 : targetIdx;
    if (from < to) to -= 1;
    onEdit((l) => relocateTile(l, tab, from, to, tab.tiles[targetIdx].section));
  };

  const renderRow = (view: TileView, i: number) => {
    const key = `${view.tabId}:${view.componentId}`;
    const selected = selectedKey === key;
    return (
      <React.Fragment key={view.componentId}>
        <TileCard
          view={view}
          selected={selected}
          thumbnail={thumbs[key]}
          dragging={dragId === view.componentId}
          dropIndicator={over?.id === view.componentId ? over.position : null}
          onSelect={() => onSelect(view.tabId, selected ? null : view.componentId)}
          onToggleInReport={(on) =>
            onEdit((l) =>
              patchTile(
                l,
                view.entry,
                // Out of the report is out of the PDF too.
                on ? { in_report: true, in_pdf: true } : { in_report: false, in_pdf: false },
              ),
            )
          }
          onDragStart={(e) => {
            e.stopPropagation();
            e.dataTransfer.setData(TILE_DRAG_TYPE, key);
            e.dataTransfer.effectAllowed = 'move';
            setDragId(view.componentId);
          }}
          onDragOver={(e, position) => {
            // Only a tile of this tab can land here.
            if (!dragId) return;
            e.preventDefault();
            e.stopPropagation();
            if (over?.id !== view.componentId || over.position !== position) {
              setOver({ id: view.componentId, position });
            }
          }}
          onDrop={(e) => {
            if (!dragId) return;
            e.preventDefault();
            e.stopPropagation();
            dropOn(i, over?.id === view.componentId ? over.position : 'before');
          }}
          onDragEnd={endTileDrag}
        />
        <InspectorSlot open={selected}>
          <TileInspector
            view={view}
            sections={tab.sections}
            canMoveUp={i > 0}
            canMoveDown={i < tab.tiles.length - 1}
            onPatch={(patch) => onEdit((l) => patchTile(l, view.entry, patch))}
            onMove={(dir) =>
              onEdit((l) => relocateTile(l, tab, i, i + dir, tab.tiles[i + dir].section))
            }
          />
        </InspectorSlot>
      </React.Fragment>
    );
  };

  return (
    <Box data-testid="report-outline-tab" data-tab-id={tab.tabId}>
      <div
        className="re-tabhead"
        draggable={!tab.isMain}
        onDragStart={tabDrag.onDragStart}
        onDragOver={(e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          tabDrag.onDragOver(e, e.clientY < rect.top + rect.height / 2 ? 'before' : 'after');
        }}
        onDrop={tabDrag.onDrop}
        onDragEnd={tabDrag.onDragEnd}
        style={{
          opacity: tabDrag.dragging ? 0.4 : 1,
          borderTop:
            tabDrag.indicator === 'before' ? '2px solid var(--mantine-primary-color-filled)' : undefined,
          borderBottom:
            tabDrag.indicator === 'after' ? '2px solid var(--mantine-primary-color-filled)' : undefined,
        }}
      >
        <div className="re-tabhead-main" onClick={() => setOpen((o) => !o)}>
          <span
            className="re-tabhead-grip"
            style={{ cursor: tab.isMain ? 'default' : 'grab' }}
            aria-hidden
          >
            {tab.isMain ? (
              <Pin size={16} strokeWidth={STROKE} />
            ) : (
              <GripVertical size={16} strokeWidth={STROKE} />
            )}
          </span>
          <ActionIcon
            variant="subtle"
            color="gray"
            size="sm"
            onClick={(e) => {
              e.stopPropagation();
              setOpen((o) => !o);
            }}
            aria-label={open ? 'Collapse the tab' : 'Expand the tab'}
          >
            <span className="re-tabhead-chevron" data-open={open || undefined}>
              <ChevronRight size={17} strokeWidth={STROKE} />
            </span>
          </ActionIcon>
          <span
            className="re-chip re-chip--tab"
            style={{ ['--re-tint' as string]: tabTint(color) }}
            aria-hidden
          >
            <Icon icon={tabIconId(icon)} width={18} />
          </span>
          <span className="re-tabhead-title">{tab.title}</span>
          <Badge
            variant="light"
            color="gray"
            size="sm"
            tt="none"
            fw={500}
            style={{ flex: 'none' }}
            data-testid="report-tab-count"
          >
            {inReport} of {tab.tiles.length} in the report
          </Badge>
        </div>
        <div className="re-tabhead-tools">
          <div style={{ display: 'flex' }}>
            <Tooltip label={tab.isMain ? 'The main tab stays first' : 'Move the tab up'} withArrow>
              <ActionIcon
                variant="subtle"
                color="gray"
                size="sm"
                disabled={tab.isMain || index <= 1}
                onClick={() => onMoveTab(-1)}
                aria-label="Move tab up"
              >
                <ArrowUp size={16} strokeWidth={STROKE} />
              </ActionIcon>
            </Tooltip>
            <ActionIcon
              variant="subtle"
              color="gray"
              size="sm"
              disabled={tab.isMain || index >= count - 1}
              onClick={() => onMoveTab(1)}
              aria-label="Move tab down"
            >
              <ArrowDown size={16} strokeWidth={STROKE} />
            </ActionIcon>
          </div>
          <SegmentedControl
            size="xs"
            value={tab.placement}
            disabled={tab.isMain}
            onChange={(v) =>
              onEdit((l) => setTabPlacement(l, tab.tabId, v as ReportTabPlacement, index))
            }
            data={[
              { label: 'Body', value: 'body' },
              { label: 'Appendix', value: 'appendix' },
            ]}
          />
        </div>
      </div>

      <Collapse in={open}>
        <Stack gap={6} pt="xs">
          {tab.tiles.length === 0 && (
            <Text size="sm" c="dimmed" px="xs">
              This tab has no components.
            </Text>
          )}
          {runs.map((run, r) => {
            const cards = run.rows.map(({ view, i }) => renderRow(view, i));
            if (!run.section) return <TileGrid key={`run-${r}`}>{cards}</TileGrid>;
            const name = run.section;
            const included = run.rows.filter((row) => row.view.inReport).length;
            return (
              <SectionBlock
                key={`run-${r}`}
                tabId={tab.tabId}
                title={name}
                total={run.rows.length}
                included={included}
                open={isSectionOpen(name)}
                first={r === 0}
                onToggle={() => setSectionOpen((prev) => ({ ...prev, [name]: !isSectionOpen(name) }))}
                onToggleAll={(on) =>
                  onEdit((l) =>
                    run.rows.reduce(
                      (acc, row) =>
                        patchTile(
                          acc,
                          row.view.entry,
                          on ? { in_report: true, in_pdf: true } : { in_report: false, in_pdf: false },
                        ),
                      l,
                    ),
                  )
                }
              >
                {cards}
              </SectionBlock>
            );
          })}
        </Stack>
      </Collapse>
    </Box>
  );
};

export default TabBlock;
