import React from 'react';
import { Box, Group, Stack } from '@mantine/core';

import { compactNumber, hexWithAlpha, percent } from './format';
import {
  METRIC,
  MetricCaption,
  MetricStrip,
  TooltipDivider,
  TooltipNote,
  TooltipStat,
} from './tokens';
import type { AttritionPayload } from './types';

/** Width reserved for the stage name beside each bar. Fixed so the bars all
 *  start and end at the same x, which is what makes the funnel readable. */
const LABEL_W = 62;

/**
 * ``attrition`` — retention across an ordered sequence of stages.
 *
 *   ▰▰▰▰▰▰▰▰▰▰  raw       12.4M
 *   ▰▰▰▰▰▰▰▰▱▱  trimmed   11.1M
 *   ▰▰▰▰▱▱▱▱▱▱  mapped     5.6M
 *   45% retained
 *
 * The most-read figure of any nf-core report. Bars are shares of the *first*
 * stage, so the funnel shape is the cumulative survival; the tooltip adds the
 * step-to-step drop, which is what identifies the single stage that did the
 * damage — a 50% cumulative loss reads very differently when it happened in one
 * step versus gradually.
 *
 * A stage larger than its predecessor is drawn as-is (clamped only for the bar
 * width): it means the columns were listed in the wrong order, and hiding that
 * would leave the user with a chart they cannot explain.
 */
const AttritionMetric: React.FC<{
  payload: AttritionPayload;
  color?: string | null;
}> = ({ payload, color }) => {
  const stages = payload.stages || [];
  if (stages.length < 2) return null;

  const tooltip = (
    <Stack gap={2}>
      <TooltipStat label="reduction" value={payload.aggregation} />
      <TooltipDivider />
      {stages.map((stage) => (
        <TooltipStat
          key={stage.name}
          label={stage.name}
          value={`${compactNumber(stage.value)} (${percent(stage.share)})${
            stage.step_share !== null && stage.step_share < 1
              ? ` −${percent(1 - stage.step_share)}`
              : ''
          }`}
        />
      ))}
      <TooltipDivider />
      <TooltipNote>
        Percentages are shares of the first stage; −x% is the drop from the previous
        stage.
      </TooltipNote>
    </Stack>
  );

  return (
    <MetricStrip tooltip={tooltip} gap={2} ariaLabel="Stage retention">
      {stages.map((stage, idx) => (
        <Group key={stage.name} gap={5} wrap="nowrap" style={{ minWidth: 0 }}>
          <Box
            style={{
              flex: 1,
              minWidth: 0,
              height: METRIC.rowMeterHeight,
              borderRadius: 3,
              overflow: 'hidden',
              background: METRIC.track,
            }}
          >
            <Box
              style={{
                width: `${Math.max(0, Math.min(100, stage.share * 100))}%`,
                height: '100%',
                background: hexWithAlpha(color, Math.max(0.35, 0.85 - idx * 0.12)),
                transition: 'width 200ms ease-out',
              }}
            />
          </Box>
          <Box style={{ width: LABEL_W, flexShrink: 0 }}>
            <MetricCaption>{stage.name}</MetricCaption>
          </Box>
        </Group>
      ))}
      <MetricCaption strong>
        {percent(payload.retained)} retained ·{' '}
        {compactNumber(stages[stages.length - 1]?.value ?? 0)} of{' '}
        {compactNumber(stages[0]?.value ?? 0)}
      </MetricCaption>
    </MetricStrip>
  );
};

export default AttritionMetric;
