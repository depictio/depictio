/**
 * RangeSlider variant: two-handle numeric range filter.
 */
import React, { useEffect, useState } from 'react';
import { Group, NumberInput, RangeSlider, Stack, Text } from '@mantine/core';
import { fetchColumnRange } from 'depictio-react-core';
import { useBuilderStore } from '../../store/useBuilderStore';

const RangeSliderForm: React.FC = () => {
  const dcId = useBuilderStore((s) => s.dcId);
  const config = useBuilderStore((s) => s.config) as {
    column_name?: string;
    default_state?: { default_range?: [number, number] };
    marks_number?: number;
  };
  const patchConfig = useBuilderStore((s) => s.patchConfig);
  const [range, setRange] = useState<{ min: number | null; max: number | null }>({
    min: null,
    max: null,
  });

  useEffect(() => {
    if (!dcId || !config.column_name) return;
    fetchColumnRange(dcId, config.column_name).then(setRange);
  }, [dcId, config.column_name]);

  const min = range.min ?? 0;
  const max = range.max ?? 100;
  const value: [number, number] = config.default_state?.default_range ?? [min, max];

  return (
    <Stack gap="xs" mt="xs">
      <Text size="sm" fw={500}>
        Default range
      </Text>
      <RangeSlider
        min={min}
        max={max}
        step={(max - min) / 100}
        value={value}
        onChange={(val) =>
          patchConfig({
            default_state: { ...config.default_state, default_range: val },
          })
        }
      />
      <Group grow>
        <NumberInput
          label="Min"
          value={value[0]}
          onChange={(val) =>
            patchConfig({
              default_state: {
                ...config.default_state,
                default_range: [Number(val), value[1]],
              },
            })
          }
          min={min}
          max={max}
        />
        <NumberInput
          label="Max"
          value={value[1]}
          onChange={(val) =>
            patchConfig({
              default_state: {
                ...config.default_state,
                default_range: [value[0], Number(val)],
              },
            })
          }
          min={min}
          max={max}
        />
        <NumberInput
          label="Marks"
          value={config.marks_number ?? 5}
          onChange={(val) => patchConfig({ marks_number: Number(val) })}
          min={2}
          max={20}
        />
      </Group>
    </Stack>
  );
};

export default RangeSliderForm;
