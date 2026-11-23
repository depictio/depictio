import React from 'react';
import { Box, Stack } from '@mantine/core';

import { compactNumber, hexWithAlpha, percent, readableColumn } from './format';
import {
  METRIC,
  MetricCaption,
  MetricStrip,
  TooltipDivider,
  TooltipNote,
  TooltipStat,
} from './tokens';
import type { AttritionPayload } from './types';

/** Most of the strip the stage names may take. The names sit in one grid
 *  column sized to the longest, so every bar starts and ends at the same x,
 *  which is what makes the funnel readable; past this a name wraps. */
const LABEL_MAX = '45%';

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
          label={readableColumn(stage.name)}
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
      <Box
        style={{
          display: 'grid',
          gridTemplateColumns: `minmax(0, 1fr) fit-content(${LABEL_MAX})`,
          columnGap: 6,
          rowGap: 2,
          alignItems: 'center',
        }}
      >
        {stages.map((stage, idx) => (
          <React.Fragment key={stage.name}>
            <Box
              style={{
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
            <Box style={{ minWidth: 0, lineHeight: 1.15 }}>
              <MetricCaption wrap>{readableColumn(stage.name)}</MetricCaption>
            </Box>
          </React.Fragment>
        ))}
      </Box>
      <MetricCaption strong>
        {percent(payload.retained)} retained ·{' '}
        {compactNumber(stages[stages.length - 1]?.value ?? 0)} of{' '}
        {compactNumber(stages[0]?.value ?? 0)}
      </MetricCaption>
    </MetricStrip>
  );
};

export default AttritionMetric;
