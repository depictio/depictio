import React, { Suspense, lazy, useState } from 'react';
import { Button, Group, SegmentedControl, Select, Text, Tooltip, UnstyledButton } from '@mantine/core';
import { Icon } from '@iconify/react';

import type { InteractiveFilter, JBrowseCall } from '../../api';
import type { NamedLocusSource } from './locusSources';
import { navigatorCaption, regionCountLabel, regionNoun } from './navigatorSteps';
import type { CallNavigator as CallNavigatorState } from './useCallNavigator';

// The picker brings AG Grid with it; it is fetched when the badge is first
// opened, not with every genome tile.
const RegionPicker = lazy(() => import('./RegionPicker'));

/** A segmented switch up to this many sources, a compact select past it. */
const MAX_SEGMENT_SOURCES = 3;
/** The switch needs room: a narrower tile gets the select. */
const SEGMENT_MIN_WIDTH = 720;

interface CallNavigatorProps {
  navigator: CallNavigatorState;
  sources: NamedLocusSource[];
  /** Header of the picker's score column (the primary `sort_by`). */
  scoreLabel?: string | null;
  /** A tight header (a linked view, a floating panel): short labels, no caption. */
  compact?: boolean;
  tileWidth: number;
  dashboardId: string;
  index: string;
  filters: InteractiveFilter[];
  versionBody: Record<string, unknown>;
  /** The reader picked a region: move the view there. */
  onNavigate: (call: JBrowseCall) => void;
  onPrev: () => void;
  onNext: () => void;
}

/**
 * "Previous peak" / "Next peak" over the regions of `locus_from` (the nearest
 * one left or right of the view, as IGV's Ctrl+B / Ctrl+F), the region in
 * view between them, the count that opens the list, and (with several
 * sources) which source they step through, one at a time. It moves the view
 * only, never the dashboard filters.
 */
const CallNavigator: React.FC<CallNavigatorProps> = ({
  navigator,
  sources,
  scoreLabel,
  compact,
  tileWidth,
  dashboardId,
  index,
  filters,
  versionBody,
  onNavigate,
  onPrev,
  onNext,
}) => {
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerEverOpened, setPickerEverOpened] = useState(false);
  const { total, current, busy, enabledSources, setEnabledSources } = navigator;
  const multi = sources.length > 1;
  if (total <= 0 && !multi) return null;

  const caption = navigatorCaption(current);
  const noun = regionNoun(enabledSources);
  const openPicker = () => {
    setPickerEverOpened(true);
    setPickerOpen((open) => !open);
  };
  const badge = (
    <UnstyledButton
      onClick={openPicker}
      aria-label="Open the region list"
      aria-haspopup="dialog"
      data-testid="jbrowse-region-count"
      title="Open the list"
      style={{ flex: '0 0 auto' }}
    >
      <Text
        size="xs"
        c="dimmed"
        style={{ whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums', cursor: 'pointer' }}
      >
        {regionCountLabel(total, noun)}
      </Text>
    </UnstyledButton>
  );

  return (
    <Group
      gap={2}
      wrap="nowrap"
      data-testid="jbrowse-call-navigator"
      style={{ flex: '0 1 auto', minWidth: 0 }}
    >
      <Tooltip label={`The nearest ${noun} left of the view`} openDelay={400} withinPortal>
        <Button
          size="compact-xs"
          variant="subtle"
          leftSection={<Icon icon="tabler:chevron-left" width={14} height={14} />}
          aria-label={`Previous ${noun}`}
          disabled={total <= 0 || busy}
          onClick={onPrev}
          data-testid="jbrowse-call-prev"
        >
          {compact ? 'Prev' : `Previous ${noun}`}
        </Button>
      </Tooltip>
      {!compact && caption && (
        <Text size="xs" fw={500} truncate maw={220} mx={4} data-testid="jbrowse-call-caption">
          {caption}
        </Text>
      )}
      <Tooltip label={`The nearest ${noun} right of the view`} openDelay={400} withinPortal>
        <Button
          size="compact-xs"
          variant="subtle"
          rightSection={<Icon icon="tabler:chevron-right" width={14} height={14} />}
          aria-label={`Next ${noun}`}
          disabled={total <= 0 || busy}
          onClick={onNext}
          data-testid="jbrowse-call-next"
        >
          {compact ? 'Next' : `Next ${noun}`}
        </Button>
      </Tooltip>
      {pickerEverOpened ? (
        <Suspense fallback={badge}>
          <RegionPicker
            opened={pickerOpen}
            onClose={() => setPickerOpen(false)}
            width={tileWidth}
            sources={sources}
            enabledSources={enabledSources}
            scoreLabel={scoreLabel}
            dashboardId={dashboardId}
            index={index}
            filters={filters}
            versionBody={versionBody}
            onSelect={(call) => {
              navigator.select(call);
              onNavigate(call);
            }}
          >
            {badge}
          </RegionPicker>
        </Suspense>
      ) : (
        badge
      )}
      {multi && (
        <SourceSwitch
          sources={sources}
          enabled={enabledSources}
          onChange={setEnabledSources}
          tileWidth={compact ? 0 : tileWidth}
          compact={compact}
        />
      )}
    </Group>
  );
};

const SourceSwitch: React.FC<{
  sources: NamedLocusSource[];
  enabled: string[];
  onChange: (names: string[]) => void;
  tileWidth: number;
  compact?: boolean;
}> = ({ sources, enabled, onChange, tileWidth, compact }) => {
  // One source at a time: "previous / next" over a mix of two kinds of region
  // (a library's peaks and the consensus intervals) reads as neither.
  const value = enabled.find((n) => sources.some((s) => s.name === n)) ?? sources[0]?.name ?? '';
  const change = (name: string | null) => {
    if (name) onChange([name]);
  };
  const names = sources.map((s) => s.name);
  return (
    <Group gap={6} wrap="nowrap" ml={8} data-testid="jbrowse-source-chips" style={{ minWidth: 0 }}>
      {compact ? null : (
        <Text size="xs" c="dimmed" style={{ whiteSpace: 'nowrap' }}>
          Step through
        </Text>
      )}
      {sources.length > MAX_SEGMENT_SOURCES || tileWidth < SEGMENT_MIN_WIDTH ? (
        <Select
          size="xs"
          w={compact ? 120 : 140}
          aria-label="Step through"
          data={names}
          value={value}
          onChange={change}
          allowDeselect={false}
          comboboxProps={{ withinPortal: true }}
        />
      ) : (
        <SegmentedControl size="xs" aria-label="Step through" data={names} value={value} onChange={change} />
      )}
    </Group>
  );
};

export default CallNavigator;
