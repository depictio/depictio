import React, { useState } from 'react';
import {
  ActionIcon,
  Button,
  Divider,
  Drawer,
  FileButton,
  Group,
  SegmentedControl,
  Stack,
  Switch,
  Text,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import {
  BrandThemeForm,
  BrandThemePreview,
  isEmptyBrandTheme,
  useResolvedBrandTheme,
  type AnalysisState,
  type BrandTheme,
  type DashboardData,
  type LogoMode,
} from 'depictio-react-core';
import DashboardInfoBody from './DashboardInfoBody';
import NotebookExportModal from './NotebookExportModal';
import { useBranding } from '../branding';
import { useUiScalePref } from '../hooks/useUiScalePref';

/** Client-side mirror of the server's upload cap (routes.py). */
const LOGO_MAX_BYTES = 2 * 1024 * 1024;

/** A color-picker drag fires continuously; this is how long the drawer waits
 *  before writing. Long enough to coalesce a drag, short enough that letting
 *  go feels like it saved. */
const SAVE_DEBOUNCE_MS = 600;

/** A− / percent / A+ control for the dashboard content font-size preference
 *  (#854). Scales figures, tables and the other dashboard tiles — never the
 *  app chrome — and is a per-browser preference, so it renders in both the
 *  viewer and the editor. */
const FontSizeBlock: React.FC = () => {
  const { scale, increase, decrease, reset, canIncrease, canDecrease } = useUiScalePref();

  return (
    <Stack gap={6} data-testid="font-size-section">
      <Text fw={500} size="sm">
        Font size
      </Text>
      <Text size="xs" c="dimmed">
        Scales the dashboard components (figures, tables, cards…). Saved in this browser.
        Each figure can also carry its own font size from its tile menu while editing.
      </Text>
      <Group gap="xs">
        <ActionIcon.Group data-testid="font-size-control">
          <Tooltip label="Decrease font size" withArrow>
            <ActionIcon
              variant="default"
              size="input-xs"
              onClick={decrease}
              disabled={!canDecrease}
              data-testid="font-size-decrease"
              aria-label="Decrease font size"
            >
              <Icon icon="mdi:format-font-size-decrease" width={14} />
            </ActionIcon>
          </Tooltip>
          <Button
            variant="default"
            size="compact-xs"
            h="var(--input-height-xs)"
            style={{ pointerEvents: 'none' }}
            data-testid="font-size-value"
            tabIndex={-1}
          >
            {Math.round(scale * 100)}%
          </Button>
          <Tooltip label="Increase font size" withArrow>
            <ActionIcon
              variant="default"
              size="input-xs"
              onClick={increase}
              disabled={!canIncrease}
              data-testid="font-size-increase"
              aria-label="Increase font size"
            >
              <Icon icon="mdi:format-font-size-increase" width={14} />
            </ActionIcon>
          </Tooltip>
        </ActionIcon.Group>
        {scale !== 1 && (
          <Button variant="subtle" size="compact-xs" onClick={reset} data-testid="font-size-reset">
            Reset
          </Button>
        )}
      </Group>
    </Stack>
  );
};

/**
 * Logo source for this dashboard: inherit the instance's, upload one, or show
 * none. "Inherit" is the piece that was missing — a dashboard used to show
 * nothing at all unless it carried its own upload.
 */
const LogoBlock: React.FC<{
  theme: BrandTheme;
  instanceHasLogo: boolean;
  onChangeMode: (mode: LogoMode) => void;
  onUpload: (file: File) => Promise<void>;
}> = ({ theme, instanceHasLogo, onChangeMode, onUpload }) => {
  const [uploading, setUploading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const mode: LogoMode = theme.logo_mode ?? (theme.logo_url ? 'custom' : 'inherit');

  const handleFile = async (file: File | null) => {
    if (!file) return;
    if (file.size > LOGO_MAX_BYTES) {
      setError('File is too large (max 2MB).');
      return;
    }
    setError(null);
    setUploading(true);
    try {
      await onUpload(file);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed.');
    } finally {
      setUploading(false);
    }
  };

  return (
    <Stack gap={6} data-testid="dashboard-logo-section">
      <Text fw={500} size="sm">
        Logo
      </Text>
      <Text size="xs" c="dimmed">
        Shown at the bottom of the dashboard sidebar.
      </Text>
      <SegmentedControl
        size="xs"
        value={mode}
        onChange={(value) => onChangeMode(value as LogoMode)}
        data={[
          { value: 'inherit', label: 'Instance logo' },
          { value: 'custom', label: 'Upload' },
          { value: 'none', label: 'None' },
        ]}
        data-testid="dashboard-logo-mode"
      />
      {mode === 'inherit' && !instanceHasLogo && (
        <Text size="xs" c="dimmed">
          This instance has no custom logo, so nothing is shown here.
        </Text>
      )}
      {mode === 'custom' && (
        <>
          <Group gap="xs">
            <FileButton onChange={handleFile} accept="image/png,image/jpeg,image/webp">
              {(props) => (
                <Button
                  {...props}
                  variant="default"
                  size="xs"
                  loading={uploading}
                  leftSection={<Icon icon="mdi:upload" width={14} />}
                  data-testid="dashboard-logo-upload"
                >
                  {theme.logo_url ? 'Replace logo' : 'Upload logo'}
                </Button>
              )}
            </FileButton>
            <Text size="xs" c="dimmed">
              PNG, JPEG or WebP, up to 2MB.
            </Text>
          </Group>
          {error && (
            <Text size="xs" c="red">
              {error}
            </Text>
          )}
          {theme.logo_url && (
            <img
              src={theme.logo_url}
              alt="Dashboard logo"
              style={{ height: 40, maxWidth: 220, objectFit: 'contain', alignSelf: 'center' }}
            />
          )}
        </>
      )}
    </Stack>
  );
};

/**
 * The dashboard's brand override: inherit the instance identity, or state the
 * parts that differ. Edits go into a local draft and are written on a debounce
 * (and on close) — a color picker fires on every pointer move, and each write
 * makes every figure on the dashboard refetch.
 */
const BrandingBlock: React.FC<{
  dashboard: DashboardData | null;
  onChange: (theme: BrandTheme | null) => void;
  onUploadLogo?: (file: File) => Promise<void>;
  opened: boolean;
}> = ({ dashboard, onChange, onUploadLogo, opened }) => {
  const instance = useBranding();
  const saved = dashboard?.brand_theme ?? null;
  const [draft, setDraft] = React.useState<BrandTheme | null>(saved);

  // Adopt whatever the dashboard carries each time the drawer opens; a logo
  // upload lands on the dashboard directly, so the draft must not shadow it.
  React.useEffect(() => {
    if (opened) setDraft(dashboard?.brand_theme ?? null);
  }, [opened, dashboard?.brand_theme]);

  const timer = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const pending = React.useRef<BrandTheme | null>(null);

  const flush = React.useCallback(() => {
    if (timer.current) {
      clearTimeout(timer.current);
      timer.current = null;
    }
    if (pending.current !== null) {
      const value = pending.current;
      pending.current = null;
      onChange(isEmptyBrandTheme(value) ? null : value);
    }
  }, [onChange]);

  // Closing mid-debounce must not lose the last edit.
  React.useEffect(() => {
    if (!opened) flush();
  }, [opened, flush]);
  React.useEffect(() => flush, [flush]);

  const emit = (next: BrandTheme | null) => {
    setDraft(next);
    pending.current = next ?? {};
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(flush, SAVE_DEBOUNCE_MS);
  };

  const customising = draft !== null;
  const value = draft ?? {};
  const resolved = useResolvedBrandTheme(customising ? value : (instance ?? {}));

  return (
    <Stack gap="sm" data-testid="dashboard-branding-section">
      <Stack gap={6}>
        <Text fw={500} size="sm">
          Branding
        </Text>
        <SegmentedControl
          size="xs"
          value={customising ? 'custom' : 'inherit'}
          onChange={(mode) => emit(mode === 'custom' ? (saved ?? {}) : null)}
          data={[
            { value: 'inherit', label: 'Inherit instance' },
            { value: 'custom', label: 'Customise' },
          ]}
          data-testid="dashboard-branding-mode"
        />
        <Text size="xs" c="dimmed">
          {customising
            ? 'Anything left empty still follows the instance branding.'
            : 'This dashboard uses the instance colors, logo and figure palette.'}
        </Text>
      </Stack>

      {customising && (
        <>
          <BrandThemeForm
            scope="dashboard"
            value={value}
            defaults={instance}
            onChange={emit}
            logoSlot={
              onUploadLogo ? (
                <LogoBlock
                  theme={value}
                  instanceHasLogo={!!instance?.logo_url}
                  onChangeMode={(mode) => emit({ ...value, logo_mode: mode })}
                  onUpload={onUploadLogo}
                />
              ) : undefined
            }
          />
          <Divider />
          <Text fw={500} size="sm">
            Preview
          </Text>
          <BrandThemePreview theme={resolved} compact />
        </>
      )}
    </Stack>
  );
};

interface SettingsDrawerProps {
  opened: boolean;
  onClose: () => void;
  dashboard: DashboardData | null;
  /** Editor only: makes the Branding section editable. The viewer leaves this
   *  unset and the section is not rendered. */
  onChangeBrandTheme?: (theme: BrandTheme | null) => void;
  /** Editor-only: persists the dashboard's `funnel_filtering` field (issue
   *  #939). Omitted in the viewer, where the drawer stays read-only. */
  onToggleFunnelFiltering?: (enabled: boolean) => void;
  /** Editor only: uploads a dashboard logo (the server stamps it on the
   *  dashboard's brand theme) — reject to surface an error. */
  onUploadLogo?: (file: File) => Promise<void>;
  /** Viewer: a snapshot of the current analysis state (filters, funnel order,
   *  groups) for the notebook export. The Export section renders only when
   *  this is provided. */
  getAnalysisState?: () => AnalysisState;
}

/** "Export" section: the dashboard as a marimo / Jupyter / Quarto notebook. */
const ExportBlock: React.FC<{
  dashboard: DashboardData | null;
  getAnalysisState: () => AnalysisState;
}> = ({ dashboard, getAnalysisState }) => {
  const [opened, setOpened] = useState(false);
  const dashboardId = String(dashboard?.dashboard_id ?? dashboard?._id ?? '');
  return (
    <Stack gap="sm" data-testid="export-section">
      <Group gap="xs">
        <Icon icon="mdi:export-variant" width={18} />
        <Text fw={600} size="sm">
          Export
        </Text>
      </Group>
      <Text size="xs" c="dimmed">
        Take this dashboard with you as code: the same table, the same filters in funnel order,
        every tile — as a marimo notebook, a Jupyter notebook or a Quarto report.
      </Text>
      <Button
        variant="light"
        leftSection={<Icon icon="mdi:notebook-outline" width={16} />}
        onClick={() => setOpened(true)}
        disabled={!dashboardId}
        data-testid="export-notebook"
      >
        Export as notebook
      </Button>
      <NotebookExportModal
        opened={opened}
        onClose={() => setOpened(false)}
        dashboardId={dashboardId}
        dashboardTitle={dashboard?.title}
        getAnalysisState={getAnalysisState}
      />
    </Stack>
  );
};

/**
 * Right-side drawer for the current dashboard: metadata on top, then an
 * "Appearance" section grouping the content font-size preference (#854) and
 * the dashboard's brand override (#397 — logo, colors, surfaces and figure
 * defaults, inheriting the instance branding for anything left unset). The
 * editor also carries the funnel-filtering default (issue #939).
 *
 * The metadata content lives in `DashboardInfoBody`, shared with the
 * inspector's Info tab — which is what the inspector replaces this drawer
 * with when enabled.
 */
const SettingsDrawer: React.FC<SettingsDrawerProps> = ({
  opened,
  onClose,
  dashboard,
  onChangeBrandTheme,
  onToggleFunnelFiltering,
  onUploadLogo,
  getAnalysisState,
}) => (
  <Drawer
    opened={opened}
    onClose={onClose}
    position="right"
    size="md"
    title={
      <Group gap="xs">
        <Icon icon="mdi:cog" width={20} />
        <Text fw={600}>Dashboard settings</Text>
      </Group>
    }
  >
    <Stack gap="md">
      <DashboardInfoBody dashboard={dashboard} active={opened} />
      {onToggleFunnelFiltering && (
        <>
          <Divider />
          <Switch
            label="Funnel filtering by default"
            description="Highlight, in every other filter, the values that still lead to a non-empty result set. Viewers can still turn it off from the filter panel."
            checked={dashboard?.funnel_filtering !== false}
            onChange={(e) => onToggleFunnelFiltering(e.currentTarget.checked)}
          />
        </>
      )}
      {getAnalysisState && (
        <>
          <Divider />
          <ExportBlock dashboard={dashboard} getAnalysisState={getAnalysisState} />
        </>
      )}
      <Divider />
      <Stack gap="sm" data-testid="appearance-section">
        <Group gap="xs">
          <Icon icon="mdi:palette-outline" width={18} />
          <Text fw={600} size="sm">
            Appearance
          </Text>
        </Group>
        <FontSizeBlock />
        {onChangeBrandTheme && (
          <>
            <Divider />
            <BrandingBlock
              dashboard={dashboard}
              onChange={onChangeBrandTheme}
              onUploadLogo={onUploadLogo}
              opened={opened}
            />
          </>
        )}
      </Stack>
    </Stack>
  </Drawer>
);

export default SettingsDrawer;
