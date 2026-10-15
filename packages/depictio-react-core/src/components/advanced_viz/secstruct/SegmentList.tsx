import React from 'react';
import {
  Button,
  ColorSwatch,
  Group,
  ScrollArea,
  Text,
  useMantineColorScheme,
  useMantineTheme,
} from '@mantine/core';

import { panelColours } from '../protein/panelTheme';
import { rgbCss } from '../protein/residueColours';
import { SS_GLYPH_FILLS } from '../protein/ssGlyphs';
import type { ResidueRange } from '../protein/types';
import { segmentLabel, type SsSegment } from './ssModel';
import type { SsStateColours } from './stateColours';

/** Most segments the list renders; a proteome-scale table would otherwise mount thousands. */
const MAX_LISTED = 400;
/** Height of the list before it scrolls. */
export const SEGMENT_LIST_MAX_PX = 76;

interface Props {
  segments: readonly SsSegment[];
  /** The range picked in the dashboard, to mark the segment that matches it. */
  selectedRange?: ResidueRange | null;
  /** Click on a segment: its residue range. Omit for a list that only reads. */
  onPick?: (range: ResidueRange) => void;
  /** Colours the dashboard pins for a class; the others keep the glyph fills. */
  stateColours?: SsStateColours;
}

/**
 * The segments of the main source as a compact scrolling list, one entry per
 * segment ("Helix 12–30 (19 aa, mean P 0.86)"). A click picks the segment's
 * residues, as a brush over them would.
 */
const SegmentList: React.FC<Props> = ({ segments, selectedRange, onPick, stateColours }) => {
  const theme = useMantineTheme();
  const { colorScheme } = useMantineColorScheme();
  // The glyph fill of a class; coil has none and takes the panel's neutral grey.
  const coil = stateColours?.coil ?? rgbCss(panelColours(theme, colorScheme === 'dark').neutral);
  if (segments.length === 0) {
    return (
      <Text size="xs" c="dimmed" px={4} data-testid="secondary-structure-segments-empty">
        No helix or strand segment in this protein
      </Text>
    );
  }
  const shown = segments.slice(0, MAX_LISTED);
  return (
    <ScrollArea.Autosize
      mah={SEGMENT_LIST_MAX_PX}
      type="auto"
      scrollbarSize={6}
      offsetScrollbars
      className="depictio-secondary-structure-segments"
    >
      <Group gap={2} wrap="wrap" px={2}>
        {shown.map((seg) => {
          const selected =
            selectedRange != null &&
            selectedRange.start === seg.start &&
            (selectedRange.end ?? selectedRange.start) === seg.end;
          return (
            <Button
              key={`${seg.start}-${seg.end}`}
              size="compact-xs"
              variant={selected ? 'light' : 'subtle'}
              color="gray"
              fw={selected ? 600 : 400}
              leftSection={<ColorSwatch color={seg.state === 'coil' ? coil : (stateColours?.[seg.state] ?? SS_GLYPH_FILLS[seg.state])} size={8} withShadow={false} />}
              onClick={onPick ? () => onPick({ start: seg.start, end: seg.end }) : undefined}
              style={onPick ? undefined : { cursor: 'default', pointerEvents: 'none' }}
              aria-label={segmentLabel(seg)}
            >
              {segmentLabel(seg)}
            </Button>
          );
        })}
        {segments.length > shown.length ? (
          <Text size="xs" c="dimmed" px={6}>
            and {segments.length - shown.length} more
          </Text>
        ) : null}
      </Group>
    </ScrollArea.Autosize>
  );
};

export default SegmentList;
