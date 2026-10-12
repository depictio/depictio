import React from 'react';
import { SegmentedControl } from '@mantine/core';

import { useColorScheme } from '../../../hooks/useColorScheme';
import { Field } from '../SettingsSections';

/** Light or Dark, kept in this browser. No "Auto": the stored scheme
 *  (`theme-store`) and the boot-time read only know light and dark, so an
 *  "Auto" here would not survive a reload. */
const ThemeField: React.FC = () => {
  const { colorScheme, setColorScheme } = useColorScheme();
  return (
    <Field
      label="Theme"
      description="Light or dark colours for the whole app."
      testId="theme-section"
    >
      <SegmentedControl
        size="xs"
        value={colorScheme}
        onChange={(value) => setColorScheme(value === 'dark' ? 'dark' : 'light')}
        data={[
          { value: 'light', label: 'Light' },
          { value: 'dark', label: 'Dark' },
        ]}
        data-testid="theme-control"
      />
    </Field>
  );
};

export default ThemeField;
