import React from 'react';
import { Divider, Modal, SegmentedControl, SimpleGrid, Stack, Switch, Text } from '@mantine/core';
import type { ReportLayer, ReportSettings } from 'depictio-react-core';

/** The report as it was before these settings existed: what a layer without
 *  them exports (the model's own defaults, `ReportSettings`). */
export const DEFAULT_SETTINGS: ReportSettings = {
  paper: 'a4',
  landscape: false,
  tile_width: 'row',
  viz_controls: 'popover',
  toc: true,
  export_details: true,
  how_to_run: true,
  methods: true,
  code: true,
  numbering: true,
  provenance: true,
};

export function settingsOf(layer: ReportLayer | null | undefined): ReportSettings {
  return { ...DEFAULT_SETTINGS, ...(layer?.settings ?? {}) };
}

interface ReportSettingsModalProps {
  opened: boolean;
  onClose: () => void;
  layer: ReportLayer;
  onEdit: (change: (layer: ReportLayer) => ReportLayer) => void;
}

const SettingsGroup: React.FC<{ title: string; hint: string; children: React.ReactNode }> = ({
  title,
  hint,
  children,
}) => (
  <Stack gap="xs">
    <div>
      <Text fw={600} size="sm">
        {title}
      </Text>
      <Text size="xs" c="dimmed">
        {hint}
      </Text>
    </div>
    {children}
  </Stack>
);

const Choice: React.FC<{
  label: string;
  value: string;
  data: { value: string; label: string }[];
  onChange: (value: string) => void;
  testId: string;
}> = ({ label, value, data, onChange, testId }) => (
  <Stack gap={4}>
    <Text size="xs" fw={500}>
      {label}
    </Text>
    <SegmentedControl size="xs" fullWidth data={data} value={value} onChange={onChange} data-testid={testId} />
  </Stack>
);

/** The report's own options, for the whole document: the PDF's page, the
 *  default layout, the parts around the results, and what a caption says.
 *  Changes are saved with the layer like any edit; the preview renders again,
 *  since they change the document rather than one tile. */
const ReportSettingsModal: React.FC<ReportSettingsModalProps> = ({ opened, onClose, layer, onEdit }) => {
  const s = settingsOf(layer);
  const set = (patch: Partial<ReportSettings>) =>
    onEdit((l) => ({ ...l, settings: { ...settingsOf(l), ...patch } }));
  const toggle = (key: keyof ReportSettings, label: string, description: string) => (
    <Switch
      key={key}
      label={label}
      description={description}
      checked={Boolean(s[key])}
      onChange={(e) => set({ [key]: e.currentTarget.checked } as Partial<ReportSettings>)}
      data-testid={`report-setting-${key}`}
    />
  );

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={<Text fw={600}>Report settings</Text>}
      size="lg"
      data-testid="report-settings"
    >
      <Stack gap="lg">
        <SettingsGroup title="PDF" hint="How the Exact PDF prints.">
          <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="sm">
            <Choice
              label="Colour"
              value={layer.style ?? 'colour'}
              data={[
                { value: 'colour', label: 'Colour' },
                { value: 'mono', label: 'Mono' },
              ]}
              onChange={(v) => onEdit((l) => ({ ...l, style: v as ReportLayer['style'] }))}
              testId="report-setting-style"
            />
            <Choice
              label="Paper"
              value={s.paper}
              data={[
                { value: 'a4', label: 'A4' },
                { value: 'letter', label: 'Letter' },
              ]}
              onChange={(v) => set({ paper: v as ReportSettings['paper'] })}
              testId="report-setting-paper"
            />
            <Choice
              label="Pages"
              value={s.landscape ? 'landscape' : 'portrait'}
              data={[
                { value: 'portrait', label: 'Portrait' },
                { value: 'landscape', label: 'Landscape' },
              ]}
              onChange={(v) => set({ landscape: v === 'landscape' })}
              testId="report-setting-landscape"
            />
          </SimpleGrid>
          <Text size="xs" c="dimmed">
            A tile&apos;s own PDF orientation still turns its page.
          </Text>
        </SettingsGroup>

        <Divider />
        <SettingsGroup title="Layout" hint="The defaults every tile starts from.">
          <Choice
            label="Tile width"
            value={s.tile_width}
            data={[
              { value: 'row', label: 'As in the dashboard' },
              { value: 'full', label: 'Every tile full width' },
            ]}
            onChange={(v) => set({ tile_width: v as ReportSettings['tile_width'] })}
            testId="report-setting-tile_width"
          />
          <Choice
            label="Advanced visualisation controls"
            value={s.viz_controls}
            data={[
              { value: 'popover', label: 'Behind the settings icon' },
              { value: 'rail', label: 'Beside the plot' },
              { value: 'header', label: 'Under the title' },
            ]}
            onChange={(v) => set({ viz_controls: v as ReportSettings['viz_controls'] })}
            testId="report-setting-viz_controls"
          />
          <Text size="xs" c="dimmed">
            A visualisation whose controls were placed in the dashboard keeps that placement.
          </Text>
        </SettingsGroup>

        <Divider />
        <SettingsGroup title="Document" hint="The parts around the results.">
          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
            {toggle('toc', 'Table of contents', 'The side contents, and the contents page of the PDF')}
            {toggle('export_details', 'Export details', 'Who exported it, when, from where')}
            {toggle('how_to_run', 'How to run', 'The commands that run the document again')}
            {toggle('methods', 'Methods and citations', 'The tools and references, last')}
            {toggle('code', 'Code button', 'The button that shows the document’s code')}
          </SimpleGrid>
        </SettingsGroup>

        <Divider />
        <SettingsGroup title="Captions" hint="What sits under each figure and table.">
          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
            {toggle('numbering', 'Numbers', '“Figure 3”, “Table 1” before each caption')}
            {toggle('provenance', 'Data line', 'The collection, its rows and its date')}
          </SimpleGrid>
        </SettingsGroup>
      </Stack>
    </Modal>
  );
};

export default ReportSettingsModal;
