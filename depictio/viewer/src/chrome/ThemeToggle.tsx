import React from 'react';
import { Switch } from '@mantine/core';
import { Icon } from '@iconify/react';

import { useColorScheme } from '../hooks/useColorScheme';

/**
 * Theme toggle Switch — visual parity with `depictio/dash/simple_theme.py`'s
 * `create_theme_switch()`. Sun on the off label, moon on the on label.
 */
const ThemeToggle: React.FC = () => {
  const { colorScheme, toggle } = useColorScheme();
  const checked = colorScheme === 'dark';

  return (
    <Switch
      size="lg"
      color="orange"
      checked={checked}
      onChange={() => toggle()}
      onLabel={<Icon icon="ph:moon-fill" width={16} />}
      offLabel={<Icon icon="ph:sun-fill" width={16} />}
      aria-label="Toggle color scheme"
    />
  );
};

export default ThemeToggle;
