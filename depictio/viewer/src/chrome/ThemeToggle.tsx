import React from 'react';
import { Switch } from '@mantine/core';
import { Icon } from '@iconify/react';

import { useBrandAccent } from 'depictio-react-core';
import { useColorScheme } from '../hooks/useColorScheme';

/**
 * Theme toggle Switch — visual parity with `depictio/dash/simple_theme.py`'s
 * `create_theme_switch()`. Sun on the off label, moon on the on label.
 */
const ThemeToggle: React.FC = () => {
  const { colorScheme, toggle } = useColorScheme();
  const checked = colorScheme === 'dark';
  // Orange reads as "sun" on an unbranded instance; a brand that names a
  // tertiary gets its accent here instead of a hue from nowhere.
  const color = useBrandAccent('tertiary', 'orange');

  return (
    <Switch
      size="lg"
      color={color}
      checked={checked}
      onChange={() => toggle()}
      onLabel={<Icon icon="ph:moon-fill" width={16} />}
      offLabel={<Icon icon="ph:sun-fill" width={16} />}
      aria-label="Toggle color scheme"
      data-testid="theme-toggle"
    />
  );
};

export default ThemeToggle;
