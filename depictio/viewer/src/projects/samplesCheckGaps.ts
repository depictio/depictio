/**
 * What the shared-samples check left unread (#1400). It reads the first few
 * reports of a MultiQC collection, none of a run whose report cannot be
 * read: finding no shared sample then covers the reports read only.
 */
import type { SamplesCheckGap } from 'depictio-react-core';

export function samplesCheckGapText(gaps: SamplesCheckGap[]): string {
  return gaps
    .map((gap) =>
      gap.checked === 0
        ? `${gap.data_collection_tag} of ${gap.run}: no report could be read`
        : `${gap.data_collection_tag} of ${gap.run}: ${gap.checked} of ${gap.reports} reports read`,
    )
    .join(' · ');
}
