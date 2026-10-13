import React from 'react';
import { Stack } from '@mantine/core';

import { formatNumber, hexWithAlpha, percent } from './format';
import { Meter, MetricCaption, MetricStrip, TooltipDivider, TooltipStat } from './tokens';

/** Below this share the fill switches to amber: the bar's job is to say "not
 *  finished yet", and a full-length accent-coloured bar at 40% does not. */
const COMPLETE_SHARE = 0.9;
const PARTIAL_SHARE = 0.5;
const INCOMPLETE_FILL = 'rgba(250,176,5,0.75)';

export function coverageStatus(share: number): 'complete' | 'partial' | 'sparse' {
  if (share >= COMPLETE_SHARE) return 'complete';
  if (share >= PARTIAL_SHARE) return 'partial';
  return 'sparse';
}

/**
 * ``coverage`` — a fill bar of ``value / max``.
 *
 *   ▰▰▰▰▰▰▰▰▰▰ 100% of 44
 *
 * The numerator is the card's hero value, the denominator the YAML-declared
 * ``coverage_max`` — "44 of the 44 samples in the cohort", "9 of 11 ORFs". No
 * server compute at all, which is why it is also the cheapest way to show a
 * filter's effect: the hero value moves with the filters and the bar follows.
 */
const CoverageMetric: React.FC<{
  value: number;
  max: number;
  color?: string | null;
  /** The card's `format`: the value and the maximum are both in its unit. */
  format?: string;
}> = ({ value, max, color, format }) => {
  const num = (v: number) => (format ? formatNumber(v, format) : v.toLocaleString());
  const share = Math.max(0, Math.min(1, value / max));
  const status = coverageStatus(share);
  const fill = status === 'complete' ? hexWithAlpha(color, 0.8) : INCOMPLETE_FILL;
  const remaining = Math.max(0, max - value);

  const tooltip = (
    <Stack gap={2}>
      <TooltipStat label="covered" value={num(value)} />
      <TooltipStat label="maximum" value={num(max)} />
      <TooltipStat label="remaining" value={num(remaining)} />
      <TooltipDivider />
      <TooltipStat label="coverage" value={percent(share, share === 1 ? 0 : 1)} strong />
      <TooltipStat label="status" value={status} />
    </Stack>
  );

  return (
    <MetricStrip tooltip={tooltip} ariaLabel="Coverage">
      <Meter segments={[{ key: 'covered', share, color: fill }]} />
      {/* Kept on a headline card too: every strip in a row of key figures
          is a bar over one line, so the cards' contents stand the same
          height and their titles line up. */}
      <MetricCaption strong>
        {percent(share)} of {num(max)}
      </MetricCaption>
    </MetricStrip>
  );
};

export default CoverageMetric;
