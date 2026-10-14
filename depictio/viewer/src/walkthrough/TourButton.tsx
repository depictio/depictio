import React from 'react';
import { ActionIcon, Tooltip } from '@mantine/core';
import { Compass } from 'lucide-react';

import { GlassKey, useGlassPages } from '../chrome/variants/glass/pages';
import { useTourLauncher } from './availability';

/**
 * Starts the guided tour from the page header. It sits on the pages where the
 * tours begin (Projects for the builder tour, Dashboards for the explorer
 * tour), left of the page's primary action, in both chromes: a Glass key in
 * Glass, a light icon button in Classic.
 *
 * Where the walkthrough host is suppressed (dev mode, the kill switch,
 * `?no-walkthrough=1`) the button is disabled with the reason, not hidden: a
 * button that does nothing would mislead, and a gap would not say why. While
 * the deployment's answer loads it is disabled too, so the header does not shift.
 */
const TourButton: React.FC = () => {
  const glass = useGlassPages();
  const tour = useTourLauncher();

  if (glass) {
    if (tour.available) {
      return <GlassKey label={tour.label} icon={Compass} onClick={tour.start} data-testid="tour-button" />;
    }
    return (
      // A disabled button swallows pointer events; the span carries the tooltip.
      <Tooltip label={tour.reason} withArrow openDelay={250} disabled={tour.reason === null}>
        <span>
          <GlassKey
            label={tour.label}
            icon={Compass}
            disabled
            data-testid="tour-button"
          />
        </span>
      </Tooltip>
    );
  }
  return (
    <Tooltip
      label={tour.reason ?? tour.label}
      withArrow
      openDelay={250}
      disabled={!tour.available && tour.reason === null}
    >
      {/* A disabled button swallows pointer events; the span carries the tooltip. */}
      <span>
        <ActionIcon
          variant="light"
          color="gray"
          size="lg"
          aria-label={tour.label}
          disabled={!tour.available}
          onClick={tour.start}
          data-testid="tour-button"
        >
          <Compass size={20} strokeWidth={1.8} aria-hidden />
        </ActionIcon>
      </span>
    </Tooltip>
  );
};

export default TourButton;
