import React, { useEffect, useState } from 'react';
import { Box, Button, CloseButton, Group, Popover, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import DepictioRose from '../components/rose/DepictioRose';

interface LandingHintProps {
  /** What this dashboard is: its subtitle, else its title. */
  description: string | null;
  onOpenGuide: () => void;
  onDismiss: () => void;
}

interface Anchor {
  rect: DOMRect;
  /** Below the bar's Depictio credit or mark, else beside the Guide. */
  position: 'bottom-end' | 'bottom-start' | 'right';
}

/** The element a `data-tour-id` names, on the screen it is drawn on: the same
 *  id can sit in the desktop rail and the phone's list, and only one has a box. */
function visible(id: string): HTMLElement | undefined {
  return Array.from(document.querySelectorAll<HTMLElement>(`[data-tour-id="${id}"]`)).find(
    (e) => e.getClientRects().length > 0,
  );
}

/** Where the hint points. Depictio's own credit leads: the hint is Depictio
 *  introducing itself, and the credit sits over the free top-right of the
 *  canvas, where the callout covers nothing. Then the mark, then the Guide. */
function useAnchor(): Anchor | null {
  const [anchor, setAnchor] = useState<Anchor | null>(null);
  useEffect(() => {
    const measure = () => {
      const credit = visible('powered-by');
      const mark = credit ? undefined : visible('home-mark');
      const guide = credit || mark ? undefined : visible('guide');
      const el = credit ?? mark ?? guide;
      const next: Anchor | null = el
        ? {
            rect: el.getBoundingClientRect(),
            position: credit ? 'bottom-end' : mark ? 'bottom-start' : 'right',
          }
        : null;
      setAnchor((prev) => {
        if (!prev || !next) return prev === next ? prev : next;
        const a = prev.rect;
        const b = next.rect;
        return prev.position === next.position &&
          a.top === b.top && a.left === b.left && a.width === b.width && a.height === b.height
          ? prev
          : next;
      });
    };
    measure();
    // The sidebar folds, the window resizes, the bar mounts late: all move it.
    const mo = new MutationObserver(measure);
    mo.observe(document.body, { childList: true, subtree: true });
    window.addEventListener('resize', measure);
    return () => {
      mo.disconnect();
      window.removeEventListener('resize', measure);
    };
  }, []);
  return anchor;
}

/**
 * A guest's first look at a public dashboard: one callout under the Depictio
 * mark, its petals moving, saying what Depictio is, what this dashboard is and
 * where to learn the rest. It dims nothing and blocks nothing; the page stays
 * usable beneath it. Nowhere to anchor (a phone, a custom-branded bar without a
 * sidebar) means no hint.
 */
const LandingHint: React.FC<LandingHintProps> = ({ description, onOpenGuide, onDismiss }) => {
  const anchor = useAnchor();
  if (!anchor) return null;
  const { rect, position } = anchor;
  return (
    <Popover
      opened
      position={position}
      withArrow
      arrowSize={12}
      arrowOffset={28}
      offset={14}
      radius="md"
      shadow="lg"
      width={340}
      withinPortal
      zIndex={400}
      transitionProps={{ transition: 'pop', duration: 200 }}
    >
      <Popover.Target>
        {/* Invisible proxy over the real element: anchors without touching it. */}
        <Box
          aria-hidden
          style={{
            position: 'fixed',
            top: rect.top,
            left: rect.left,
            width: rect.width,
            height: rect.height,
            pointerEvents: 'none',
          }}
        />
      </Popover.Target>
      <Popover.Dropdown
        role="region"
        aria-label="About Depictio"
        data-testid="landing-hint"
        p="md"
        style={{ border: '1.5px solid var(--mantine-primary-color-filled)' }}
      >
        <Group align="flex-start" wrap="nowrap" gap="sm">
          <Box style={{ flexShrink: 0, lineHeight: 0 }}>
            <DepictioRose mode="petals" size={34} label="" />
          </Box>
          <Stack gap={6} style={{ minWidth: 0 }}>
            <Group justify="space-between" align="flex-start" wrap="nowrap" gap="xs">
              <Text size="md" fw={650} lh={1.3}>
                Depictio turns a pipeline&apos;s results into interactive dashboards.
              </Text>
              <CloseButton size="sm" aria-label="Dismiss" onClick={onDismiss} data-testid="landing-hint-dismiss" />
            </Group>
            {description && (
              <Text size="sm" c="dimmed" lh={1.4}>
                {description}
              </Text>
            )}
            <Button
              variant="light"
              size="xs"
              mt={4}
              style={{ alignSelf: 'flex-start' }}
              rightSection={<Icon icon="mdi:arrow-right" width={14} />}
              onClick={onOpenGuide}
              data-testid="landing-hint-guide"
            >
              See how this dashboard works
            </Button>
          </Stack>
        </Group>
      </Popover.Dropdown>
    </Popover>
  );
};

export default LandingHint;
