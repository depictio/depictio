/**
 * Switch / Checkbox variant: boolean toggle.
 */
import React from 'react';
import { Stack, Switch, Text } from '@mantine/core';
import { useBuilderStore } from '../../store/useBuilderStore';

const CheckboxSwitchForm: React.FC = () => {
  const config = useBuilderStore((s) => s.config) as {
    default_state?: { default_value?: boolean };
  };
  const patchConfig = useBuilderStore((s) => s.patchConfig);

  return (
    <Stack gap="xs" mt="xs">
      <Text size="sm" fw={500}>
        Default state
      </Text>
      <Switch
        label="Default checked"
        checked={Boolean(config.default_state?.default_value)}
        onChange={(e) =>
          patchConfig({
            default_state: { default_value: e.currentTarget.checked },
          })
        }
      />
    </Stack>
  );
};

export default CheckboxSwitchForm;
