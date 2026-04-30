/**
 * Card builder form. Mirrors design_card() in
 * depictio/dash/modules/card_component/design_ui.py — title, column,
 * aggregation, colors, icon, font size, with a live preview on the right.
 */
import React, { useEffect, useMemo } from 'react';
import {
  ColorInput,
  Select,
  Stack,
  TextInput,
  Title,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { useBuilderStore } from '../store/useBuilderStore';
import ColumnSelect from '../shared/ColumnSelect';
import DesignShell from '../shared/DesignShell';
import CardPreview from './CardPreview';
import { cardMethodsForType } from '../aggFunctions';
import { autoCardTitle } from './cardTitle';

const FONT_SIZES = [
  { value: 'xs', label: 'XS' },
  { value: 'sm', label: 'S' },
  { value: 'md', label: 'M' },
  { value: 'lg', label: 'L' },
  { value: 'xl', label: 'XL' },
];

const BACKGROUND_SWATCHES = [
  '#2e2e2e',
  '#868e96',
  '#fa5252',
  '#e64980',
  '#be4bdb',
  '#7950f2',
  '#4c6ef5',
  '#228be6',
  '#15aabf',
  '#12b886',
  '#40c057',
  '#82c91e',
  '#fab005',
  '#fd7e14',
  '',
];

const TITLE_COLOR_SWATCHES = [
  '#000000',
  '#fa5252',
  '#e64980',
  '#be4bdb',
  '#7950f2',
  '#4c6ef5',
  '#228be6',
  '#15aabf',
  '#12b886',
  '#40c057',
  '#fab005',
];

const ICON_OPTIONS: { value: string; label: string }[] = [
  { value: 'mdi:chart-line', label: 'Chart line' },
  { value: 'mdi:chart-bar', label: 'Chart bar' },
  { value: 'mdi:chart-pie', label: 'Chart pie' },
  { value: 'mdi:counter', label: 'Counter' },
  { value: 'mdi:sigma', label: 'Sigma (sum)' },
  { value: 'mdi:calculator', label: 'Calculator' },
  { value: 'mdi:database', label: 'Database' },
  { value: 'mdi:table', label: 'Table' },
  { value: 'mdi:account-multiple', label: 'People' },
  { value: 'mdi:dna', label: 'DNA' },
  { value: 'mdi:flask', label: 'Flask' },
  { value: 'mdi:microscope', label: 'Microscope' },
  { value: 'mdi:test-tube', label: 'Test tube' },
  { value: 'mdi:percent', label: 'Percent' },
  { value: 'mdi:check-circle', label: 'Check circle' },
];

const CardBuilder: React.FC = () => {
  const config = useBuilderStore((s) => s.config) as {
    title?: string;
    column_name?: string;
    column_type?: string;
    aggregation?: string;
    background_color?: string;
    title_color?: string;
    icon_name?: string;
    title_font_size?: string;
  };
  const patchConfig = useBuilderStore((s) => s.patchConfig);

  // Apply sane defaults once after mount when creating fresh.
  useEffect(() => {
    patchConfig({
      title: config.title ?? '',
      aggregation: config.aggregation ?? 'count',
      icon_name: config.icon_name ?? 'mdi:chart-line',
      title_font_size: config.title_font_size ?? 'md',
      background_color: config.background_color ?? '',
      title_color: config.title_color ?? '',
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Aggregation options follow the column's type, mirroring
  // depictio/api/v1/utils.py:agg_functions[type]['card_methods'].
  const aggOptions = useMemo(
    () => cardMethodsForType(config.column_type),
    [config.column_type],
  );

  // If the current aggregation isn't valid for the new column type, reset to
  // the first allowed one (or null if the type has no card methods).
  useEffect(() => {
    if (!config.column_type) return;
    if (!config.aggregation) return;
    if (!aggOptions.some((o) => o.value === config.aggregation)) {
      patchConfig({ aggregation: aggOptions[0]?.value ?? null });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config.column_type, aggOptions]);

  const form = (
    <Stack gap="md">
      <TextInput
        label="Card title"
        placeholder={
          autoCardTitle(
            config.aggregation,
            config.column_name,
            config.column_type,
          ) || 'Total samples'
        }
        description="Leave empty to auto-fill with “<Aggregation> on <column>”."
        value={config.title ?? ''}
        onChange={(e) => patchConfig({ title: e.currentTarget.value })}
        leftSection={<Icon icon="mdi:format-title" width={14} />}
      />

      <ColumnSelect
        label="Select your column"
        value={config.column_name}
        onChange={(name, type) =>
          patchConfig({ column_name: name, column_type: type })
        }
        required
      />

      <Select
        label="Select your aggregation method"
        placeholder={
          !config.column_type
            ? 'Pick a column first'
            : aggOptions.length === 0
              ? 'No aggregations for this column type'
              : 'Pick aggregation'
        }
        data={aggOptions}
        value={config.aggregation ?? null}
        onChange={(val) => patchConfig({ aggregation: val })}
        disabled={!config.column_type || aggOptions.length === 0}
        required
      />

      <Title order={6} fw={700} mt="sm">
        Card Styling
      </Title>

      <ColorInput
        label="Background Color"
        value={config.background_color ?? ''}
        onChange={(val) => patchConfig({ background_color: val })}
        format="hex"
        swatchesPerRow={7}
        swatches={BACKGROUND_SWATCHES}
        placeholder="(default)"
      />

      <ColorInput
        label="Title Color"
        value={config.title_color ?? ''}
        onChange={(val) => patchConfig({ title_color: val })}
        format="hex"
        swatchesPerRow={7}
        swatches={TITLE_COLOR_SWATCHES}
        placeholder="(default)"
      />

      <Select
        label="Icon"
        placeholder="Pick an icon"
        data={ICON_OPTIONS}
        value={config.icon_name ?? null}
        onChange={(val) => patchConfig({ icon_name: val })}
        searchable
        leftSection={
          <Icon icon={config.icon_name || 'mdi:help-circle'} width={14} />
        }
      />

      <Select
        label="Title Font Size"
        data={FONT_SIZES}
        value={config.title_font_size ?? 'md'}
        onChange={(val) => patchConfig({ title_font_size: val })}
      />
    </Stack>
  );

  return <DesignShell formSlot={form} previewSlot={<CardPreview />} />;
};

export default CardBuilder;
