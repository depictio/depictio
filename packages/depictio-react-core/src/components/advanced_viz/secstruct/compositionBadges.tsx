import React from 'react';
import { Badge } from '@mantine/core';

import {
  compositionOf,
  compositionSummary,
  formatPercent,
  stateLabel,
  type SsAgreement,
  type SsModel,
} from './ssModel';

// `tt: none` keeps a source's name as the table spells it (Badges capitalise by default).
const BADGE_PROPS = { size: 'xs', radius: 'sm', variant: 'default', tt: 'none' } as const;

/**
 * The tile's header badges: the percentage of helix, strand and coil residues
 * (one badge each for a single source, one summary badge per source when
 * several are compared) and, with `agreement`, how well the others agree with
 * the main source. Empty when there is nothing to say.
 */
export function compositionBadges(
  model: SsModel,
  agreement: SsAgreement | null,
  show: { composition: boolean; agreement: boolean },
): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  if (show.composition) {
    if (model.sources.length === 1) {
      const c = compositionOf(model, 0);
      if (c.total > 0) {
        (['helix', 'strand', 'turn', 'coil'] as const).forEach((state) => {
          if (state === 'turn' && c.counts.turn === 0) return;
          out.push(
            <Badge key={`composition-${state}`} {...BADGE_PROPS}>
              {stateLabel(state)} {formatPercent(c.fractions[state])}
            </Badge>,
          );
        });
      }
    } else {
      model.sources.forEach((source, k) => {
        const c = compositionOf(model, k);
        if (c.total === 0) return;
        out.push(
          <Badge
            key={`composition-${source.name}`}
            {...BADGE_PROPS}
            title={`${source.name}: ${c.total} residues with a state`}
          >
            {source.name} · {compositionSummary(c)}
          </Badge>,
        );
      });
    }
  }
  if (show.agreement && agreement && agreement.fraction != null) {
    const main = model.sources[0].name;
    const detail = agreement.perSource
      .filter((p) => p.fraction != null)
      .map((p) => `${p.name} vs ${main}: ${formatPercent(p.fraction as number)} of ${p.compared} residues`)
      .join('\n');
    out.push(
      <Badge key="agreement" {...BADGE_PROPS} title={detail}>
        Agreement {formatPercent(agreement.fraction)}
      </Badge>,
    );
  }
  return out;
}
