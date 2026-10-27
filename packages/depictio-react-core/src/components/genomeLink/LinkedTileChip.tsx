/**
 * The tag a genome view and its genome browser each show for the other, in
 * their header: the role (the view drives, the browser follows), the other
 * tile's title and the region they share, in the link's colour, with the
 * dashed swatch the browser's window wears on the view. Hovering or focusing
 * it rings the other tile, a click brings it into view; the tooltip says in
 * words what the link does, and the same sentence is the tag's accessible
 * description.
 */
import { useEffect, useId } from 'react';
import { Badge, Tooltip, VisuallyHidden, useMantineColorScheme, useMantineTheme } from '@mantine/core';

import { LINK_COLOR, flashTile, ringTile, tileTitle } from './linkedTile';

export interface LinkedTileChipProps {
  /** Index of the other tile. */
  otherIndex: string;
  /** Title to show when the other tile is not on the page (another tab). */
  fallbackTitle: string;
  /** What this tile does to the other: it drives it, or follows it. */
  role: 'drives' | 'follows';
  /** The shared region, as the reader reads it (`chr6:26.0-26.3 Mb`). */
  region?: string | null;
  /** What the link does, in a sentence: tooltip and screen-reader text. */
  explanation: string;
  'data-testid'?: string;
}

/** The dashed band of the browser's window, as the view draws it. */
export function LinkSwatch({ color }: { color: string }) {
  return (
    <svg width={16} height={10} aria-hidden style={{ flex: 'none', display: 'block' }}>
      <rect x={1} y={1} width={14} height={8} fill={color} fillOpacity={0.18} />
      {[1, 15].map((x) => (
        <line key={x} x1={x} x2={x} y1={0} y2={10} stroke={color} strokeWidth={1.5} strokeDasharray="3 2" />
      ))}
    </svg>
  );
}

/** The link colour's shade for the scheme, as the view's band uses it. */
export function useLinkColor(): string {
  const theme = useMantineTheme();
  const { colorScheme } = useMantineColorScheme();
  return theme.colors[LINK_COLOR][colorScheme === 'dark' ? 4 : 6];
}

export default function LinkedTileChip({
  otherIndex,
  fallbackTitle,
  role,
  region,
  explanation,
  'data-testid': testId,
}: LinkedTileChipProps) {
  const descId = useId();
  const color = useLinkColor();
  const title = tileTitle(otherIndex) ?? fallbackTitle;
  // A chip that unmounts mid-hover must not leave the other tile ringed.
  useEffect(() => () => ringTile(otherIndex, false), [otherIndex]);
  const ring = (on: boolean) => () => ringTile(otherIndex, on);
  return (
    <>
      <Tooltip label={explanation} multiline maw={320} withArrow openDelay={250}>
        <Badge
          component="button"
          type="button"
          size="sm"
          variant="light"
          color={LINK_COLOR}
          radius="sm"
          tt="none"
          fw={500}
          leftSection={<LinkSwatch color={color} />}
          onMouseEnter={ring(true)}
          onMouseLeave={ring(false)}
          onFocus={ring(true)}
          onBlur={ring(false)}
          onClick={() => flashTile(otherIndex)}
          aria-describedby={descId}
          data-testid={testId}
          data-link-role={role}
          style={{ cursor: 'pointer', maxWidth: '100%', flex: 'none' }}
        >
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>
            <span style={{ fontWeight: 700 }}>{role === 'drives' ? 'Drives' : 'Follows'}</span>{' '}
            {role === 'drives' ? '→' : '←'} {title}
            {region ? ` · ${region}` : ''}
          </span>
        </Badge>
      </Tooltip>
      <VisuallyHidden id={descId}>{explanation}</VisuallyHidden>
    </>
  );
}
