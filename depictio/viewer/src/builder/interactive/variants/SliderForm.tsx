/**
 * Slider variant: single-value numeric slider. Min/max from
 * /deltatables/specs precomputed range.
 */
import React, { useEffect, useState } from 'react';
import { Group, NumberInput, Slider, Stack, Text } from '@mantine/core';
import { fetchColumnRange } from 'depictio-react-core';
import { useBuilderStore } from '../../store/useBuilderStore';

const SliderForm: React.FC = () => {
  const dcId = useBuilderStore((s) => s.dcId);
  const config = useBuilderStore((s) => s.config) as {
    column_name?: string;
    default_state?: { default_value?: number; min?: number; max?: number };
    scale?: string;
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
  const value = config.default_state?.default_value ?? min;

  return (
    <Stack gap="xs" mt="xs">
      <Group justify="space-between">
        <Text size="sm" fw={500}>
          Default value
        </Text>
        <NumberInput
          size="xs"
          value={value}
          onChange={(val) =>
            patchConfig({
              default_state: { ...config.default_state, default_value: Number(val) },
            })
          }
          min={min}
          max={max}
          w={120}
        />
      </Group>
      <Slider
        min={min}
        max={max}
        step={(max - min) / 100}
        value={value}
        onChange={(val) =>
          patchConfig({
            default_state: { ...config.default_state, default_value: val },
          })
        }
      />
      <Group grow mt="xs">
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

export default SliderForm;
