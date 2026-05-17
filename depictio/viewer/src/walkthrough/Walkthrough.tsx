import React, { useEffect, useState } from 'react';
import {
  Badge,
  Box,
  Button,
  Group,
  Image,
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

/** Resolves the DOM element for the current step's `data-tour-id`. Uses a
 *  MutationObserver so the popover can appear whenever the target eventually
 *  mounts — important for steps that live behind a sub-stepper (e.g. the
 *  component-builder wizard, where the save button is on tab 3 of 3 and the
 *  user has to step through tabs 1 and 2 first). Returns `null` until found.
 */
function useTargetElement(target: string | null): HTMLElement | null {
  const [el, setEl] = useState<HTMLElement | null>(null);
  useEffect(() => {
    if (!target) {
      setEl(null);
      return;
    }
    const selector = `[data-tour-id="${target}"]`;
    const lookup = () =>
      document.querySelector<HTMLElement>(selector);
    setEl(lookup());
    const observer = new MutationObserver(() => {
      const found = lookup();
      setEl((prev) => (prev === found ? prev : found));
    });
    observer.observe(document.body, { childList: true, subtree: true });
    return () => observer.disconnect();
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

  // When the step expects the user to actually click the target (awaitClick),
  // catch that click and advance the step counter. Without this, the
  // spotlight backdrop keeps dimming the page after the click — covering any
  // modal that opens, or staying on top of the new route until auto-advance
  // catches up on the next mount.
  useEffect(() => {
    if (!target || !step?.awaitClick) return;
    const onClick = () => next();
    target.addEventListener('click', onClick, { once: true });
    return () => target.removeEventListener('click', onClick);
  }, [target, step?.awaitClick, next]);

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

  // Next button can either advance in-place (default) or fire a navigation.
  // When navigating we still call `next()` so the step counter advances —
  // auto-advance in `useWalkthrough` then resolves to the actual next visible
  // step on the destination page (handles the case where `navigateTo` lands
  // somewhere matched by a later step than step+1).
  const handleNext = () => {
    if (step.navigateTo) {
      next();
      window.location.href = step.navigateTo;
    } else {
      next();
    }
  };

  const heroImage = step.image && !step.target ? step.image : null;

  const popoverContent = (
    <Stack gap="sm">
      {heroImage && (
        <Group justify="center">
          <Image
            src={heroImage.src}
            alt={heroImage.alt}
            h={heroImage.height ?? 56}
            w="auto"
            fit="contain"
          />
        </Group>
      )}
      <Group justify="space-between" wrap="nowrap">
        <Title order={4}>{step.title}</Title>
        <Badge size="sm" variant="light" color="gray">
          {stepNumber} / {total}
        </Badge>
      </Group>
      <Text size="md">{step.body}</Text>
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
            <Button size="xs" onClick={handleNext}>
              {step.navigateTo ? "Let's go" : 'Next'}
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
