import React, { useEffect, useState } from 'react';
import {
  Badge,
  Box,
  Button,
  Group,
  Popover,
  Progress,
  Stack,
  Text,
  Title,
} from '@mantine/core';

import SpotlightBackdrop from './SpotlightBackdrop';
import { useWalkthrough } from './useWalkthrough';
import type { WalkthroughDefinition } from './types';

interface WalkthroughProps {
  definition: WalkthroughDefinition;
  /** Whether the walkthrough is allowed to run (mode/auth gate decided by the host). */
  enabled: boolean;
}

/** Resolves the DOM element for the current step's `data-tour-id`. Retries on
 *  a short cadence because targets may mount asynchronously after a route
 *  change. Returns `null` while waiting. */
function useTargetElement(target: string | null): HTMLElement | null {
  const [el, setEl] = useState<HTMLElement | null>(null);
  useEffect(() => {
    if (!target) {
      setEl(null);
      return;
    }
    let cancelled = false;
    let attempts = 0;
    const tick = () => {
      const found = document.querySelector<HTMLElement>(`[data-tour-id="${target}"]`);
      if (cancelled) return;
      setEl(found);
      attempts += 1;
      // Keep retrying for ~3s — covers slow data fetches that delay mount.
      if (!found && attempts < 30) {
        window.setTimeout(tick, 100);
      }
    };
    tick();
    return () => {
      cancelled = true;
    };
  }, [target]);
  return el;
}

/** Renders the active step of a walkthrough: dim/spotlight backdrop +
 *  Mantine popover anchored to the target (or centered when no target). */
const Walkthrough: React.FC<WalkthroughProps> = ({ definition, enabled }) => {
  const [pathname, setPathname] = useState(window.location.pathname);

  // SPA route changes don't fire `popstate`; the existing apps mostly use
  // hard navigation, but we listen to popstate for back/forward and to a
  // custom event we could emit later if client-side routing is added.
  useEffect(() => {
    const onChange = () => setPathname(window.location.pathname);
    window.addEventListener('popstate', onChange);
    return () => window.removeEventListener('popstate', onChange);
  }, []);

  const { visibleStep, next, back, skip, finish, state } = useWalkthrough(
    definition,
    enabled,
    pathname,
  );

  const step = visibleStep >= 0 ? definition.steps[visibleStep] : null;
  const target = useTargetElement(step?.target ?? null);

  if (!step) return null;
  // Anchored step but target not in DOM yet → keep the dim backdrop so the
  // page goes quiet, but render no popover until the target appears.
  if (step.target && !target) {
    return <SpotlightBackdrop target={null} allowTargetClick={false} />;
  }

  const stepNumber = visibleStep + 1;
  const total = definition.steps.length;
  const isFirst = visibleStep === 0;
  const isLast = visibleStep === total - 1;

  const popoverContent = (
    <Stack gap="xs">
      <Group justify="space-between" wrap="nowrap">
        <Title order={5}>{step.title}</Title>
        <Badge size="sm" variant="light" color="gray">
          {stepNumber} / {total}
        </Badge>
      </Group>
      <Text size="sm">{step.body}</Text>
      <Progress value={(stepNumber / total) * 100} size="xs" />
      <Group justify="space-between" wrap="nowrap">
        <Button variant="subtle" color="gray" size="xs" onClick={skip}>
          Skip tour
        </Button>
        <Group gap="xs" wrap="nowrap">
          {!isFirst && (
            <Button variant="default" size="xs" onClick={back}>
              Back
            </Button>
          )}
          {!isLast ? (
            <Button size="xs" onClick={next}>
              Next
            </Button>
          ) : (
            <Button size="xs" color="teal" onClick={finish}>
              Got it
            </Button>
          )}
        </Group>
      </Group>
    </Stack>
  );

  return (
    <>
      <SpotlightBackdrop
        target={target}
        allowTargetClick={Boolean(step.awaitClick)}
      />
      {target ? (
        <Popover
          opened
          position={step.position ?? 'bottom'}
          withArrow
          shadow="md"
          width={340}
          withinPortal
          zIndex={1100}
        >
          <Popover.Target>
            {/* Invisible proxy positioned over the actual target — keeps the
                popover anchored without mutating the host element. */}
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
          <Popover.Dropdown>{popoverContent}</Popover.Dropdown>
        </Popover>
      ) : (
        // Centered card for welcome/end steps with no anchor target.
        <Box
          style={{
            position: 'fixed',
            top: '50%',
            left: '50%',
            transform: 'translate(-50%, -50%)',
            zIndex: 1100,
            background: 'var(--mantine-color-body)',
            borderRadius: 8,
            padding: '16px 20px',
            boxShadow: '0 8px 32px rgba(0, 0, 0, 0.25)',
            width: 380,
            maxWidth: 'calc(100vw - 32px)',
          }}
        >
          {popoverContent}
        </Box>
      )}
      {/* state.step is exposed for debugging via React DevTools; no UI. */}
      <span data-walkthrough-step={state.step} hidden />
    </>
  );
};

export default Walkthrough;
