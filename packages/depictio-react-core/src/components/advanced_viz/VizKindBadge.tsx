import React, { createContext, useContext } from 'react';
import { Badge, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import { useChromeStyle } from '../../chrome';
import type { VizKindLabel } from './vizKindTag';

/** The label of the tile's visualization kind, handed by the dispatch to the
 *  frame. Null for a kind with none (a record card) and with no provider. */
export const AdvancedVizKindContext = createContext<VizKindLabel | null>(null);

/**
 * The visualization's type, after the title of a tile in a linked view section:
 * a small kind icon and one word ("3D", "HMM", "PAE"). It names the view, so
 * it reads as a type label rather than as a status, and it carries no colour:
 * the section's own colour already marks the tile (the rail), the status chips
 * beside it own the accents, and a tinted pill here only competed with both.
 *
 * It is Mantine's neutral `default` variant, drawn on no fill: a hairline in
 * `--mantine-color-default-border` and the text in `--mantine-color-default-color`
 * (black on light, white on dark), so it holds in both colour schemes. The fill
 * is left clear (the variant's own is an opaque white or dark pad) so that on
 * the Paper chrome's glass header the surface shows through, and on Classic's
 * solid card it looks the same as the pad would.
 *
 * The shape is the chrome's: a pill in Paper, the Classic corner otherwise.
 * The case follows the other small badges, which Mantine sets (uppercase, so
 * it keeps in step with the status chips on the same line). Hovering it opens
 * a tooltip with the kind's one-line description, since the tag alone ("SS",
 * "PAE") is cryptic; a kind with no description keeps the tag as a native
 * title instead (never both). On a tight header it gives way faster than the
 * title does (a higher shrink factor), down to the icon and an ellipsis, and
 * the tooltip is then what carries its full text.
 */
export const VizKindBadge: React.FC = () => {
  const label = useContext(AdvancedVizKindContext);
  const style = useChromeStyle();
  if (!label) return null;
  const badge = (
    <Badge
      variant="default"
      bg="transparent"
      size="sm"
      radius={style.radius}
      leftSection={<Icon icon={label.icon} width={11} height={11} />}
      title={label.description ? undefined : label.tag}
      style={{ flex: '0 4 auto', minWidth: 36 }}
      data-testid="viz-kind-badge"
    >
      {label.tag}
    </Badge>
  );
  if (!label.description) return badge;
  return (
    <Tooltip label={label.description} withArrow multiline maw={280} openDelay={300} withinPortal>
      {badge}
    </Tooltip>
  );
};

export default VizKindBadge;
