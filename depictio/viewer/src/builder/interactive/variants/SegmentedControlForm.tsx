/**
 * SegmentedControl variant: small inline radio-style picker. Same data shape
 * as SelectForm but rendered as a segmented control at view time.
 */
import React, { useEffect, useState } from 'react';
import { SegmentedControl, Stack, Text } from '@mantine/core';
import { fetchUniqueValues } from 'depictio-react-core';
import { useBuilderStore } from '../../store/useBuilderStore';

const SegmentedControlForm: React.FC = () => {
  const dcId = useBuilderStore((s) => s.dcId);
  const config = useBuilderStore((s) => s.config) as {
    column_name?: string;
    default_state?: { default_value?: string };
  };
  const patchConfig = useBuilderStore((s) => s.patchConfig);
  const [options, setOptions] = useState<string[]>([]);

  useEffect(() => {
    if (!dcId || !config.column_name) {
      setOptions([]);
      return;
    }
    fetchUniqueValues(dcId, config.column_name).then(setOptions);
  }, [dcId, config.column_name]);

  return (
    <Stack gap={4} mt="xs">
      <Text size="sm" fw={500}>
        Preview
      </Text>
      {options.length ? (
        <SegmentedControl
          data={options}
          value={
            config.default_state?.default_value ?? options[0] ?? ''
          }
          onChange={(val) =>
            patchConfig({ default_state: { default_value: val } })
          }
        />
      ) : (
        <Text size="xs" c="dimmed">
          No values yet — pick a column with categorical data.
        </Text>
      )}
    </Stack>
  );
};

export default SegmentedControlForm;
