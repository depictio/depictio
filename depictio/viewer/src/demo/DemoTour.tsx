import React, { useEffect, useMemo, useState } from 'react';
import {
  Box,
  Button,
  Group,
  Popover,
  Progress,
  Stack,
  Text,
  Title,
} from '@mantine/core';

const TOUR_VERSION = 'v1';
const STORAGE_KEY = 'depictio.tour.seen';

interface DemoTourStep {
  /** Matches a ``data-tour-id`` attribute somewhere in the DOM. */
  target: string;
  title: string;
  body: string;
  /** Mantine ``Popover`` position. Defaults to ``bottom``. */
  position?: 'top' | 'bottom' | 'left' | 'right';
}

const STEPS: DemoTourStep[] = [
  {
    target: 'header-title',
    title: 'Welcome to Depictio',
    body:
      'You\'re viewing the demo mode. Your changes won\'t be saved — feel free to explore.',
    position: 'bottom',
  },
  {
    target: 'sidebar',
    title: 'Navigate dashboards',
    body: 'Switch between tabs in this dashboard family from the sidebar.',
    position: 'right',
  },
  {
    target: 'filter-panel',
    title: 'Apply filters',
    body:
      'Use these interactive controls to filter the dashboard. Cards, charts, tables, and the image grid all narrow together.',
    position: 'right',
  },
  {
    target: 'realtime-indicator',
    title: 'Live updates',
    body:
      'When backend data changes, this pill lights up. Switch to auto-refresh in the menu, or click the notification to refresh manually.',
    position: 'bottom',
  },
];

/** Anchor a popover next to whatever element matches the step's target.
 *  We don't use Mantine's controlled-anchor API directly because the targets
 *  may mount slightly later than the tour itself (e.g. RealtimeIndicator
 *  inside the header). Instead we re-query on each step change.
 */
function useTargetElement(target: string): HTMLElement | null {
  const [el, setEl] = useState<HTMLElement | null>(null);
  useEffect(() => {
    let cancelled = false;
    const tick = () => {
      const found = document.querySelector<HTMLElement>(`[data-tour-id="${target}"]`);
      if (!cancelled) setEl(found);
    };
    tick();
    // Retry once after a short delay for late-mounted targets (notifications,
    // realtime indicator, etc.).
    const timer = setTimeout(tick, 350);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [target]);
  return el;
}

interface DemoTourProps {
  /** Whether the tour should auto-start. The host typically passes
   *  ``isDemoMode === true`` here. */
  active: boolean;
}

/** Shows a guided 4-step tour the first time a user lands on the viewer in
 *  demo mode. ``localStorage['depictio.tour.seen'] === 'v1'`` suppresses the
 *  tour on subsequent visits. Bumping ``TOUR_VERSION`` re-shows it.
 */
const DemoTour: React.FC<DemoTourProps> = ({ active }) => {
  const initiallySeen = useMemo(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) === TOUR_VERSION;
    } catch {
      return false;
    }
  }, []);
  const [step, setStep] = useState(0);
  const [opened, setOpened] = useState(active && !initiallySeen);

  // Re-open if the host toggles ``active`` after boot (e.g. settings drawer
  // exposes a "Restart tour" button later — already covered by setting
  // localStorage.removeItem('depictio.tour.seen')).
  useEffect(() => {
    if (active && !initiallySeen) setOpened(true);
  }, [active, initiallySeen]);

  const current = STEPS[step];
  const target = useTargetElement(current?.target ?? '');

  const finish = () => {
    setOpened(false);
    try {
      localStorage.setItem(STORAGE_KEY, TOUR_VERSION);
    } catch {
      // ignore quota / private mode
    }
  };

  if (!opened || !current) return null;
  if (!target) {
    // Skip past unmatched targets so a missing element never blocks the user.
    if (step < STEPS.length - 1) {
      // Schedule advance on next tick to avoid recursive setState during render.
      Promise.resolve().then(() => setStep((s) => s + 1));
    }
    return null;
  }

  return (
    <Popover
      opened={opened}
      position={current.position ?? 'bottom'}
      withArrow
      shadow="md"
      width={320}
      withinPortal
      // Mantine's Popover supports referencing a host node via a wrapped
      // child OR via the imperative ``positionDependencies`` plus a
      // controlled ``Popover.Target`` slot. We use the latter so we don't
      // have to clone the actual DOM element.
    >
      <Popover.Target>
        <Box
          aria-hidden
          style={{
            position: 'fixed',
            top: target.getBoundingClientRect().top,
            left: target.getBoundingClientRect().left,
            width: target.getBoundingClientRect().width,
            height: target.getBoundingClientRect().height,
            pointerEvents: 'none',
          }}
        />
      </Popover.Target>
      <Popover.Dropdown>
        <Stack gap="xs">
          <Title order={5}>{current.title}</Title>
          <Text size="sm">{current.body}</Text>
          <Progress value={((step + 1) / STEPS.length) * 100} size="xs" />
          <Group justify="space-between" wrap="nowrap">
            <Button variant="subtle" color="gray" size="xs" onClick={finish}>
              Skip tour
            </Button>
            <Group gap="xs" wrap="nowrap">
              {step > 0 && (
                <Button
                  variant="default"
                  size="xs"
                  onClick={() => setStep((s) => Math.max(0, s - 1))}
                >
                  Back
                </Button>
              )}
              {step < STEPS.length - 1 ? (
                <Button size="xs" onClick={() => setStep((s) => s + 1)}>
                  Next
                </Button>
              ) : (
                <Button size="xs" onClick={finish}>
                  Got it
                </Button>
              )}
            </Group>
          </Group>
        </Stack>
      </Popover.Dropdown>
    </Popover>
  );
};

export default DemoTour;
