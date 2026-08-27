import React from 'react';
import { Anchor, Group, Text, useComputedColorScheme } from '@mantine/core';

import { useBrandLogoMode } from './useBrandLogoMode';

/**
 * "Powered by Depictio" badge — themed Depictio logo + label, linking to docs.
 *
 * Shown only when the depictio wordmark is no longer on screen, i.e. when the
 * brand in scope resolves to a logo of its own (`custom`) or to no logo at all
 * (`none`). On a stock deployment the wordmark is already in the app rail and
 * on the login card, so a badge repeating it is noise; once an operator puts
 * their own mark there, the attribution is the only thing left saying what the
 * app is.
 *
 * The rule is decided here rather than at each mount site so every surface
 * inherits it. Inside a dashboard `BrandScope` provides the dashboard theme
 * merged over the instance one, so a dashboard with its own logo counts too.
 */
interface PoweredByProps {
  /** When true, renders the right-border + right-padding seen in the header. */
  withRightBorder?: boolean;
}

const PoweredBy: React.FC<PoweredByProps> = ({ withRightBorder = false }) => {
  const logoMode = useBrandLogoMode();
  const isDark = useComputedColorScheme('light') === 'dark';

  // `'inherit'` is exactly when BrandLogo shows the depictio wordmark.
  if (logoMode === 'inherit') return null;

  const groupStyle: React.CSSProperties = withRightBorder
    ? {
        marginRight: 15,
        paddingRight: 15,
        borderRight: '1px solid var(--mantine-color-default-border)',
      }
    : {};

  return (
    <Anchor
      href="https://depictio.github.io/depictio-docs/"
      target="_blank"
      rel="noopener noreferrer"
      underline="never"
      data-testid="powered-by"
      style={{ color: 'inherit' }}
    >
      <Group gap={5} align="center" wrap="nowrap" style={groupStyle}>
        <Text size="xs" c="dimmed" fw={700}>
          Powered by
        </Text>
        {/* `logo_black.svg` and `logo_white.svg` are byte-identical (a base64-
            embedded PNG inside an SVG wrapper), so swapping `src` does nothing.
            Dark mode inverts the embedded raster with a CSS filter instead,
            preserving brand hues — same trick as `BrandLogo`. */}
        <img
          src="/dashboard/logos/logo_black.svg"
          alt="Depictio"
          style={{
            height: 20,
            width: 'auto',
            display: 'block',
            filter: isDark ? 'invert(1) hue-rotate(180deg)' : undefined,
          }}
        />
      </Group>
    </Anchor>
  );
};

export default PoweredBy;
