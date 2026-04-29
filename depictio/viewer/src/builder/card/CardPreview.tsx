/**
 * Live preview for the Card builder. Uses the same `DepictioCard` renderer
 * the dashboard grid uses, so what the user sees here is exactly what gets
 * rendered after save. Sized to a small fixed footprint mirroring a
 * one-column grid cell from the dashboard (≈ 280px × 140px).
 */
import React from 'react';
import { Center } from '@mantine/core';
import { DepictioCard } from 'depictio-components';
import { useBuilderStore } from '../store/useBuilderStore';
import PreviewPanel from '../shared/PreviewPanel';
import { autoCardTitle } from './cardTitle';

const CardPreview: React.FC = () => {
  const config = useBuilderStore((s) => s.config) as {
    title?: string;
    column_name?: string;
    column_type?: string;
    aggregation?: string;
    background_color?: string;
    title_color?: string;
    icon_name?: string;
    title_font_size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl';
  };
  const cols = useBuilderStore((s) => s.cols);

  if (!config.column_name || !config.aggregation) {
    return (
      <PreviewPanel
        empty
        emptyMessage="Pick a column and aggregation to preview..."
        minHeight={200}
      />
    );
  }

  const col = cols.find((c) => c.name === config.column_name);
  const rawValue = col?.specs?.[config.aggregation as string];
  const value = formatValue(rawValue);

  const effectiveTitle =
    (config.title && config.title.trim()) ||
    autoCardTitle(
      config.aggregation,
      config.column_name,
      config.column_type,
    );

  return (
    <PreviewPanel minHeight={200}>
      <Center style={{ width: '100%', padding: '0.5rem' }}>
        <div style={{ width: 280, maxWidth: '100%' }}>
          <DepictioCard
            title={effectiveTitle}
            value={value}
            icon_name={config.icon_name || 'mdi:chart-line'}
            background_color={config.background_color}
            title_color={config.title_color}
            title_font_size={config.title_font_size ?? 'md'}
            value_font_size="xl"
          />
        </div>
      </Center>
    </PreviewPanel>
  );
};

function formatValue(v: unknown): string {
  if (v == null) return '—';
  if (typeof v === 'number') {
    if (!Number.isFinite(v)) return '—';
    if (Number.isInteger(v)) return v.toLocaleString('en-US');
    return v.toLocaleString('en-US', { maximumFractionDigits: 2 });
  }
  if (typeof v === 'boolean') return v ? 'true' : 'false';
  return String(v);
}

export default CardPreview;
