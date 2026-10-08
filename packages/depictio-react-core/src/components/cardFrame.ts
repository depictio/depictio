import type React from 'react';

/**
 * The frame of a metric card (`DepictioCard.css`), for the other tiles a
 * landing page sets beside it: finding cards, tab tiles, a fact strip. One
 * border, radius and shadow, so a page of mixed tiles reads as one system.
 */
export const CARD_BORDER =
  '1.5px solid light-dark(var(--mantine-color-gray-2), var(--mantine-color-dark-5))';
export const CARD_RADIUS = 12;

export const CARD_FRAME: React.CSSProperties = {
  border: CARD_BORDER,
  borderRadius: CARD_RADIUS,
  background: 'var(--mantine-color-body)',
  boxShadow: 'var(--mantine-shadow-sm)',
};

/** Hairline between cells inside a frame. */
export const CARD_RULE = 'light-dark(var(--mantine-color-gray-2), var(--mantine-color-dark-5))';

/** A card's icon at rest: faint, in its colour, as on a headline metric card. */
export const RESTING_ICON_OPACITY = 0.32;
