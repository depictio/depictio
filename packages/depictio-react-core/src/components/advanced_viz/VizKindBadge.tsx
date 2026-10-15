import React, { createContext, useContext } from 'react';
import { Badge, useMantineTheme } from '@mantine/core';
import { Icon } from '@iconify/react';

import { useChromeStyle } from '../../chrome';
import { SectionColorContext } from '../SectionIcon';
import type { VizKindLabel } from './vizKindTag';

/** The label of the tile's visualization kind, handed by the dispatch to the
 *  frame. Null for a kind with none (a record card) and with no provider. */
export const AdvancedVizKindContext = createContext<VizKindLabel | null>(null);

/**
 * The visualization's type, after the title of a tile in a workbench section:
 * a small kind icon and one word ("3D", "HMM", "PAE"). It names the view, so
 * it reads as a type label rather than as a status: the accent is the
 * section's own colour (the tile sits in a section of that colour, and the
 * same rail marks it), the brand's primary outside one, always in Mantine's
 * light variant so it holds in both colour schemes and both chromes.
 *
 * The shape is the chrome's: a pill in Paper, the Classic corner otherwise.
 * The case follows the other small badges, which Mantine sets. On a tight
 * header it gives way faster than the title does (a higher shrink factor), down
 * to the icon and an ellipsis, and carries its full text as a title for then.
 */
export const VizKindBadge: React.FC = () => {
  const label = useContext(AdvancedVizKindContext);
  const style = useChromeStyle();
  const theme = useMantineTheme();
  const section = useContext(SectionColorContext);
  if (!label) return null;
  // The section's colour is a palette name; anything else (a literal CSS
  // colour a spec may carry) is not one Mantine's light variant can derive
  // from, so the badge keeps the primary then.
  const color = section && theme.colors[section] ? section : undefined;
  return (
    <Badge
      variant="light"
      color={color}
      size="sm"
      radius={style.radius}
      leftSection={<Icon icon={label.icon} width={11} height={11} />}
      title={label.tag}
      style={{ flex: '0 4 auto', minWidth: 36 }}
      data-testid="viz-kind-badge"
    >
      {label.tag}
    </Badge>
  );
};

export default VizKindBadge;
