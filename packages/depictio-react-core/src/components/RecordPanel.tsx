import React, { createContext, useContext } from 'react';
import { ActionIcon, Stack, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import { RECORD_PANEL_RAIL_PX } from './recordPanelLayout';
import type { RecordSidePanel } from './recordPanelLayout';

/** A folded panel as its source's cell sees it. */
export interface FoldedRecordPanel {
  panel: RecordSidePanel;
  title: string;
}

/**
 * The fold state of the dashboard's record side panels, read by the cells.
 *
 * A context rather than props on purpose: DashboardGrid memoises its cells so
 * a panel toggle does not re-render every figure on the dashboard, and only
 * the consumers below re-render when a panel folds or unfolds.
 */
export interface RecordPanelState {
  panel: (cardId: string) => RecordSidePanel | undefined;
  expanded: (cardId: string) => boolean;
  toggle: (cardId: string) => void;
  /** The folded card whose rail sits on this source's edge, if any. */
  foldedFor: (sourceId: string) => FoldedRecordPanel | undefined;
}

const NO_PANELS: RecordPanelState = {
  panel: () => undefined,
  expanded: () => true,
  toggle: () => {},
  foldedFor: () => undefined,
};

export const RecordPanelContext = createContext<RecordPanelState>(NO_PANELS);

/** Chevron pointing the way the card grows (unfold) or shrinks (fold). */
function chevron(side: RecordSidePanel['side'], unfold: boolean): string {
  const towardsSource = side === 'right' ? 'left' : 'right';
  const away = side === 'right' ? 'right' : 'left';
  return `mdi:chevron-double-${unfold ? towardsSource : away}`;
}

/** Gap between the rail and the source's own content. */
const RAIL_GAP_PX = 4;

/**
 * The grid cell of a component that drives a record side panel. While the
 * card is folded the cell spans the pair's whole width and draws the card's
 * rail on the edge the card sat on, with its own content inset by the rail.
 *
 * The children keep the same position in the tree folded or not, so a fold
 * resizes the source's renderer rather than remounting it.
 */
export const RecordPanelSource: React.FC<{ sourceId: string; children: React.ReactNode }> = ({
  sourceId,
  children,
}) => {
  const state = useContext(RecordPanelContext);
  const folded = state.foldedFor(sourceId);
  const side = folded?.panel.side;
  const inset = RECORD_PANEL_RAIL_PX + RAIL_GAP_PX;
  const label = folded?.title || 'Record';
  return (
    <div
      style={{
        position: 'relative',
        display: 'flex',
        flexDirection: 'column',
        flex: 1,
        minHeight: 0,
        paddingLeft: side === 'left' ? inset : 0,
        paddingRight: side === 'right' ? inset : 0,
      }}
    >
      {folded ? (
        <Stack
          align="center"
          gap={6}
          py={6}
          style={{
            position: 'absolute',
            top: 0,
            bottom: 0,
            [folded.panel.side]: 0,
            width: RECORD_PANEL_RAIL_PX,
            border: '1px solid var(--mantine-color-default-border)',
            borderRadius: 'var(--mantine-radius-md)',
            background: 'var(--mantine-color-body)',
            cursor: 'pointer',
            overflow: 'hidden',
          }}
          onClick={() => state.toggle(folded.panel.cardId)}
          data-record-panel-rail
        >
          <Tooltip
            label={`Show ${label}`}
            position={folded.panel.side === 'right' ? 'left' : 'right'}
          >
            <ActionIcon variant="subtle" color="gray" size="xs" aria-label={`Show ${label}`}>
              <Icon icon={chevron(folded.panel.side, true)} width={14} />
            </ActionIcon>
          </Tooltip>
          <Icon icon="mdi:card-text-outline" width={16} color="var(--mantine-color-dimmed)" />
          <Text
            size="xs"
            fw={500}
            c="dimmed"
            style={{
              writingMode: 'vertical-rl',
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              minHeight: 0,
            }}
          >
            {label}
          </Text>
        </Stack>
      ) : null}
      {children}
    </div>
  );
};

/** The fold control in an unfolded side panel's header. Renders nothing for a
 *  card that is not laid out as a side panel. */
export const RecordPanelToggle: React.FC<{ cardId: string }> = ({ cardId }) => {
  const state = useContext(RecordPanelContext);
  const panel = state.panel(cardId);
  if (!panel || !state.expanded(cardId)) return null;
  return (
    <Tooltip label="Fold into the side rail">
      <ActionIcon
        variant="subtle"
        color="gray"
        size="sm"
        aria-label="Fold into the side rail"
        onClick={() => state.toggle(cardId)}
      >
        <Icon icon={chevron(panel.side, false)} width={16} />
      </ActionIcon>
    </Tooltip>
  );
};
