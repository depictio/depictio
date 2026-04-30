/**
 * DateRangePicker variant: temporal range filter.
 */
import React from 'react';
import { Stack, Text } from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import { useBuilderStore } from '../../store/useBuilderStore';

const DatePickerForm: React.FC = () => {
  const config = useBuilderStore((s) => s.config) as {
    default_state?: { default_range?: [string | null, string | null] };
  };
  const patchConfig = useBuilderStore((s) => s.patchConfig);

  const [start, end] = config.default_state?.default_range ?? [null, null];
  const startDate = start ? new Date(start) : null;
  const endDate = end ? new Date(end) : null;

  return (
    <Stack gap="xs" mt="xs">
      <Text size="sm" fw={500}>
        Default date range
      </Text>
      <DatePickerInput
        type="range"
        value={[startDate, endDate]}
        onChange={(val) => {
          const [s, e] = val;
          patchConfig({
            default_state: {
              default_range: [
                s ? s.toISOString() : null,
                e ? e.toISOString() : null,
              ],
            },
          });
        }}
        placeholder="Pick start and end dates"
        clearable
      />
    </Stack>
  );
};

export default DatePickerForm;
