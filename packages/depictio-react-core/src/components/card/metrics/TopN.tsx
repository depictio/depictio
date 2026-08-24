import React from 'react';
import { Box, Group, Stack, Tooltip } from '@mantine/core';

import { hexWithAlpha, percent } from './format';
import { METRIC, MetricCaption, MetricStrip, TooltipDivider, TooltipStat } from './tokens';
import type { BreakdownPayload } from './types';

/** Width reserved for the value name, so every bar starts at the same x. */
const LABEL_W = 62;
/** Narrowest bar still visible — a 0.2% category should not vanish entirely. */
const MIN_BAR_PCT = 1.5;

/**
 * ``top_n`` — the most frequent values, as honest proportional bars.
 *
 *   orf1ab  ▰▰▰▰▰▰▰▰▰         598 (45%)
 *   S       ▰▰▰▰▰             332 (25%)
 *   N       ▰▰▰               172 (13%)
 *
 * Bars are scaled to the **total**, not to the leader, so a 45% bar really is
 * 45% of the width — no implicit "the top value fills the row" lie. The
 * cumulative "Top 3 = 83%" headline lives in the card's aggregation line just
 * above, composed by the card renderer, so the strip is only bars.
 *
 * Each row carries its own tooltip rather than sharing the strip's: with three
 * or five rows the interesting question is per-row ("what is this one exactly"),
 * and a single strip-wide tooltip cannot answer it.
 */
const TopNMetric: React.FC<{
  payload: BreakdownPayload;
  color?: string | null;
}> = ({ payload, color }) => {
  if (!payload.top.length) return null;
  const barFill = hexWithAlpha(color, 0.75);
  const tailRows = Math.max(0, payload.unique_values - payload.top.length);
  const tailShare = Math.max(0, 1 - payload.top_share);

  return (
    <MetricStrip gap={METRIC.rowGap} mt={10} ariaLabel={`Top values of ${payload.column}`}>
      {payload.top.map((row, idx) => (
        <Tooltip
          key={row.name}
          label={
            <Stack gap={2}>
              <TooltipStat label={row.name} value={`#${idx + 1}`} strong />
              <TooltipStat label="count" value={row.count.toLocaleString()} />
              <TooltipStat label="share" value={percent(row.percent, 1)} />
              {idx === payload.top.length - 1 && tailRows > 0 ? (
                <>
                  <TooltipDivider />
                  <TooltipStat label="column" value={payload.column} />
                  <TooltipStat
                    label="tail"
                    value={`${tailRows.toLocaleString()} more · ${percent(tailShare)}`}
                  />
                </>
              ) : null}
            </Stack>
          }
          multiline
          w={200}
          withArrow
          position="left"
          openDelay={120}
          styles={{ tooltip: { padding: '6px 8px' } }}
        >
          <Group gap={6} wrap="nowrap" align="center" style={{ cursor: 'help', minWidth: 0 }}>
            <Box style={{ width: LABEL_W, flexShrink: 0 }}>
              <MetricCaption dimmed={false}>{row.name}</MetricCaption>
            </Box>
            <Box
              style={{
                flex: '1 1 auto',
                minWidth: 0,
                height: METRIC.rowMeterHeight,
                background: METRIC.track,
                borderRadius: 2,
                overflow: 'hidden',
              }}
            >
              <Box
                style={{
                  width: `${Math.max(MIN_BAR_PCT, row.percent * 100)}%`,
                  height: '100%',
                  background: barFill,
                  borderRadius: 2,
                }}
              />
            </Box>
            <Box style={{ flexShrink: 0 }}>
              <MetricCaption>
                {row.count.toLocaleString()} ({percent(row.percent)})
              </MetricCaption>
            </Box>
          </Group>
        </Tooltip>
      ))}
    </MetricStrip>
  );
};

export default TopNMetric;
