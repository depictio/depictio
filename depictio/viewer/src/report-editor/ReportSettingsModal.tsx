import React from 'react';
import { Divider, Group, Modal, SimpleGrid, Stack, Switch, Text } from '@mantine/core';
import {
  Captions,
  Columns2,
  Contrast,
  Files,
  LayoutTemplate,
  FileText,
  Palette,
  PanelRight,
  PanelTop,
  RectangleHorizontal,
  RectangleVertical,
  Settings2,
  StretchHorizontal,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import type { ReportLayer, ReportSettings } from 'depictio-react-core';

import { STROKE } from '../chrome/variants/glass/icons';
import { IconSegmented } from './controls';
import type { SegmentOption } from './controls';

/** What a layer without settings exports (the model's own defaults,
 *  `ReportSettings`): a report read top to bottom. */
export const DEFAULT_SETTINGS: ReportSettings = {
  paper: 'a4',
  landscape: false,
  table_page_break: true,
  tile_width: 'full',
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

const STYLES: SegmentOption<'colour' | 'mono'>[] = [
  { value: 'colour', label: 'Colour', icon: Palette },
  { value: 'mono', label: 'Mono', icon: Contrast },
];
const PAPERS: SegmentOption<ReportSettings['paper']>[] = [
  { value: 'a4', label: 'A4', icon: FileText },
  { value: 'letter', label: 'Letter', icon: FileText },
];
const PAGES: SegmentOption<'portrait' | 'landscape'>[] = [
  { value: 'portrait', label: 'Portrait', icon: RectangleVertical },
  { value: 'landscape', label: 'Landscape', icon: RectangleHorizontal },
];
const WIDTHS: SegmentOption<ReportSettings['tile_width']>[] = [
  { value: 'full', label: 'Full width', icon: StretchHorizontal },
  { value: 'row', label: 'Dashboard rows', icon: Columns2 },
];
const VIZ_CONTROLS: SegmentOption<ReportSettings['viz_controls']>[] = [
  { value: 'popover', label: 'Behind an icon', icon: Settings2 },
  { value: 'rail', label: 'Beside the plot', icon: PanelRight },
  { value: 'header', label: 'Under the title', icon: PanelTop },
];

interface ReportSettingsModalProps {
  opened: boolean;
  onClose: () => void;
  layer: ReportLayer;
  onEdit: (change: (layer: ReportLayer) => ReportLayer) => void;
}

/** A group of settings: its icon and name, the line saying what it covers. */
const SettingsGroup: React.FC<{
  icon: LucideIcon;
  title: string;
  hint: string;
  children: React.ReactNode;
}> = ({ icon: I, title, hint, children }) => (
  <Stack gap="sm">
    <Group gap={8} wrap="nowrap" align="flex-start">
      <span className="re-settings-icon" aria-hidden>
        <I size={16} strokeWidth={STROKE} />
      </span>
      <div>
        <Text fw={600} size="sm">
          {title}
        </Text>
        <Text size="xs" c="dimmed">
          {hint}
        </Text>
      </div>
    </Group>
    {children}
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
      size="sm"
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
        <SettingsGroup icon={FileText} title="PDF" hint="How the Exact PDF prints.">
          <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="sm">
            <IconSegmented
              label="Colour"
              options={STYLES}
              value={layer.style ?? 'colour'}
              onChange={(v) => onEdit((l) => ({ ...l, style: v }))}
              data-testid="report-setting-style"
            />
            <IconSegmented
              label="Paper"
              options={PAPERS}
              value={s.paper}
              onChange={(v) => set({ paper: v })}
              data-testid="report-setting-paper"
            />
            <IconSegmented
              label="Pages"
              options={PAGES}
              value={s.landscape ? 'landscape' : 'portrait'}
              onChange={(v) => set({ landscape: v === 'landscape' })}
              data-testid="report-setting-landscape"
            />
          </SimpleGrid>
          {toggle(
            'table_page_break',
            'Large tables on a new page',
            'A table of a dozen rows or more starts a page, so it is not cut after its first lines. A tile’s own page settings still apply.',
          )}
        </SettingsGroup>

        <Divider />
        <SettingsGroup icon={LayoutTemplate} title="Layout" hint="The defaults every tile starts from.">
          <IconSegmented
            label="Tile width"
            options={WIDTHS}
            value={s.tile_width}
            onChange={(v) => set({ tile_width: v })}
            data-testid="report-setting-tile_width"
            hint="A tile’s own width, set in its settings, wins. Cards keep their strip."
          />
          <IconSegmented
            label="Advanced visualisation controls"
            options={VIZ_CONTROLS}
            value={s.viz_controls}
            onChange={(v) => set({ viz_controls: v })}
            data-testid="report-setting-viz_controls"
            hint="Applies to every visualisation in the report, whatever the dashboard shows."
          />
        </SettingsGroup>

        <Divider />
        <SettingsGroup icon={Files} title="Document" hint="The parts around the results.">
          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
            {toggle('toc', 'Table of contents', 'The side contents, and the contents page of the PDF')}
            {toggle('export_details', 'Export details', 'Who exported it, when, from where')}
            {toggle('how_to_run', 'How to run', 'The commands that run the document again')}
            {toggle('methods', 'Methods and citations', 'The tools and references, last')}
            {toggle('code', 'Code button', 'The button that shows the document’s code')}
          </SimpleGrid>
        </SettingsGroup>

        <Divider />
        <SettingsGroup icon={Captions} title="Captions" hint="What sits under each figure and table.">
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
