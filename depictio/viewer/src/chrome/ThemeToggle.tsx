import React from 'react';
import { Switch } from '@mantine/core';
import { Icon } from '@iconify/react';

import { useColorScheme } from '../hooks/useColorScheme';

interface ThemeToggleProps {
  /** Smaller switch for the sidebar footer row, where it shares a 250px rail
   *  with the wordmark and three status glyphs. */
  compact?: boolean;
}

/**
 * Theme toggle Switch — visual parity with `depictio/dash/simple_theme.py`'s
 * `create_theme_switch()`. Sun on the off label, moon on the on label.
 */
const ThemeToggle: React.FC<ThemeToggleProps> = ({ compact = false }) => {
  const { colorScheme, toggle } = useColorScheme();
  const checked = colorScheme === 'dark';

  return (
    <Switch
      size={compact ? 'md' : 'lg'}
      color="orange"
      checked={checked}
      onChange={() => toggle()}
      onLabel={<Icon icon="ph:moon-fill" width={compact ? 13 : 16} />}
      offLabel={<Icon icon="ph:sun-fill" width={compact ? 13 : 16} />}
      aria-label="Toggle color scheme"
      data-testid="theme-toggle"
    />
  );
};

export default ThemeToggle;
