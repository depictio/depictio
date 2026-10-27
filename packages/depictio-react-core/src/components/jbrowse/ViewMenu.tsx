import React, { useEffect, useState } from 'react';
import { Button, Text, TextInput } from '@mantine/core';
import { AdvancedVizSettingsPopover } from '../advanced_viz/AdvancedVizExtras';
import {
  VizControlGroup,
  VizFullRow,
  VizInlineField,
  VizNumberInput,
  VizSegmented,
  VizSelect,
  VizSwitch,
} from '../advanced_viz/controls/VizControls';
import {
  GROUP_LABELS,
  entriesFor,
  type DisplayGroup,
  type DisplaySettingEntry,
} from './displaySettings';
import type { DisplaySettingsApi } from './useDisplaySettings';

/** The section of the settings popover a toggle is listed under. */
export type ViewMenuGroup = 'View' | 'Loading' | 'Interaction';

export interface ViewMenuItem {
  key: string;
  label: string;
  /** One line under the label, for a toggle whose effect is not obvious. */
  description?: string;
  group: ViewMenuGroup;
  checked: boolean;
  onChange: () => void;
}

interface ViewMenuProps {
  items: ViewMenuItem[];
  /** The display settings (`useDisplaySettings`): sections under the toggles. */
  displaySettings?: DisplaySettingsApi;
  disabled?: boolean;
}

const GROUP_ORDER: ViewMenuGroup[] = ['View', 'Loading', 'Interaction'];

/** The display sections after the toggles (the view's own join the View one). */
const DISPLAY_GROUP_ORDER: DisplayGroup[] = ['alignments', 'coverage', 'features', 'variants'];

/** A text box that applies on blur or Enter, not on every keystroke. */
const CommitTextInput: React.FC<{
  label: string;
  value: string;
  disabled?: boolean;
  testId: string;
  onCommit: (value: string) => void;
}> = ({ label, value, disabled, testId, onCommit }) => {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const commit = () => {
    if (draft !== value) onCommit(draft);
  };
  return (
    <VizInlineField label={label}>
      <TextInput
        size="xs"
        aria-label={label}
        value={draft}
        disabled={disabled}
        data-testid={testId}
        onChange={(e) => setDraft(e.currentTarget.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit();
        }}
      />
    </VizInlineField>
  );
};

const SettingControl: React.FC<{
  entry: DisplaySettingEntry;
  api: DisplaySettingsApi;
  disabled?: boolean;
}> = ({ entry, api, disabled }) => {
  const { key, label, control, options } = entry;
  const value = api.value(key);
  const testId = `jbrowse-display-${key}`;
  switch (control) {
    case 'switch':
      return (
        <VizSwitch
          label={label}
          checked={value === true}
          disabled={disabled}
          onChange={(e) => api.set(key, e.currentTarget.checked)}
          data-testid={testId}
        />
      );
    case 'segmented':
      return (
        <VizSegmented
          label={label}
          data={options ?? []}
          value={typeof value === 'string' ? value : ''}
          disabled={disabled}
          onChange={(v) => api.set(key, v)}
          data-testid={testId}
        />
      );
    case 'select':
      return (
        <VizSelect
          label={label}
          data={options ?? []}
          value={typeof value === 'string' ? value : null}
          disabled={disabled}
          allowDeselect={false}
          onChange={(v) => {
            if (v) api.set(key, v);
          }}
          data-testid={testId}
        />
      );
    case 'number':
      return (
        <VizNumberInput
          label={label}
          min={entry.min}
          max={entry.max}
          allowDecimal={false}
          value={typeof value === 'number' ? value : ''}
          disabled={disabled}
          onChange={(n) => {
            if (typeof n === 'number') api.set(key, n);
          }}
          data-testid={testId}
        />
      );
    case 'text':
      return (
        <CommitTextInput
          label={label}
          value={typeof value === 'string' ? value : ''}
          disabled={disabled}
          testId={testId}
          onCommit={(v) => api.set(key, v)}
        />
      );
    default:
      return null;
  }
};

/** The light line under a group's title: the open tracks its settings act on. */
function GroupTracks({ names }: { names: string[] }) {
  if (!names.length) return null;
  const shown = names.slice(0, 3).join(', ');
  const more = names.length > 3 ? ` +${names.length - 3}` : '';
  return (
    <VizFullRow>
      <Text size="xs" c="dimmed" lineClamp={1} title={names.join(', ')}>
        Applies to {shown}
        {more}
      </Text>
    </VizFullRow>
  );
}

/** The controls of one display group; the tag box only follows the tag scheme. */
function settingRows(
  group: DisplayGroup,
  api: DisplaySettingsApi,
  disabled?: boolean,
): React.ReactNode[] {
  return entriesFor(group)
    .filter((entry) => entry.key !== 'color_tag' || api.value('color_scheme') === 'tag')
    .map((entry) => <SettingControl key={entry.key} entry={entry} api={api} disabled={disabled} />);
}

/**
 * The browser's display options (header, overview ruler, status bar, force
 * load, click-to-filter) behind the tile's settings action: the same icon,
 * colour and popover as every other tile's viz settings, with one switch per
 * option grouped like the advanced-viz controls. The popover portals into the
 * fullscreen element itself (`useFullscreenPortalTarget`).
 *
 * With `displaySettings`, the view's own options join the View section and a
 * section per kind of open track (alignments, coverage, features, variants)
 * follows, ending in a reset to the dashboard's defaults. The popover itself
 * caps its height and scrolls.
 */
const ViewMenu: React.FC<ViewMenuProps> = ({ items, displaySettings, disabled }) => (
  <AdvancedVizSettingsPopover
    controls={[
      ...GROUP_ORDER.map((group) => {
        const rows = items.filter((item) => item.group === group);
        const settings =
          group === 'View' && displaySettings ? settingRows('view', displaySettings, disabled) : [];
        if (rows.length === 0 && settings.length === 0) return null;
        return (
          <VizControlGroup key={group} title={group}>
            {rows.map((item) => (
              <VizSwitch
                key={item.key}
                label={item.label}
                description={item.description}
                checked={item.checked}
                disabled={disabled}
                onChange={item.onChange}
                data-testid={`jbrowse-option-${item.key}`}
              />
            ))}
            {settings}
          </VizControlGroup>
        );
      }),
      ...(displaySettings
        ? DISPLAY_GROUP_ORDER.filter((group) => displaySettings.groups.includes(group)).map(
            (group) => (
              <VizControlGroup key={group} title={GROUP_LABELS[group]}>
                <GroupTracks names={displaySettings.tracksIn(group)} />
                {settingRows(group, displaySettings, disabled)}
              </VizControlGroup>
            ),
          )
        : []),
      displaySettings ? (
        <Button
          key="reset-display"
          size="xs"
          variant="subtle"
          disabled={disabled || !displaySettings.modified}
          onClick={displaySettings.reset}
          data-testid="jbrowse-display-reset"
        >
          Reset to dashboard defaults
        </Button>
      ) : null,
    ]}
  />
);

export default ViewMenu;
