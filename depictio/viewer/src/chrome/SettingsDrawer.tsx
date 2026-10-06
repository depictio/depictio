import React from 'react';
import {
  Accordion,
  ActionIcon,
  Anchor,
  Button,
  Divider,
  Drawer,
  FileButton,
  Group,
  SegmentedControl,
  Stack,
  Switch,
  Text,
  ThemeIcon,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import {
  BrandThemeForm,
  BrandThemePreview,
  isEmptyBrandTheme,
  useResolvedBrandTheme,
  Z_LAYERS,
  type BrandTheme,
  type DashboardData,
  type LogoMode,
} from 'depictio-react-core';
import DashboardInfoBody from './DashboardInfoBody';
import { useBranding } from '../branding';
import { useFeedbackLink } from '../feedback';
import { useUiScalePref } from '../hooks/useUiScalePref';
import { CONTENT_WIDTHS, type ContentWidth, useContentWidthPref } from '../hooks/useContentWidthPref';

/** Client-side mirror of the server's upload cap (routes.py). */
const LOGO_MAX_BYTES = 2 * 1024 * 1024;

/** A color-picker drag fires continuously; this is how long the drawer waits
 *  before writing. Long enough to coalesce a drag, short enough that letting
 *  go feels like it saved. */
const SAVE_DEBOUNCE_MS = 600;

// ---------------------------------------------------------------------------
// Shared layout pieces
// ---------------------------------------------------------------------------

/**
 * Header of one drawer section: icon, title, and a one-line subtitle saying
 * what the section is for and who it affects. Every section uses this one, so
 * the drawer reads as a list of like things rather than a stack of ad-hoc
 * headings.
 */
const SectionHeader: React.FC<{ icon: string; title: string; subtitle: string }> = ({
  icon,
  title,
  subtitle,
}) => (
  <Group gap="sm" wrap="nowrap" align="center">
    <ThemeIcon variant="light" size="md" radius="md">
      <Icon icon={icon} width={16} />
    </ThemeIcon>
    <Stack gap={0} style={{ minWidth: 0 }}>
      <Text size="sm" fw={600} lh={1.3}>
        {title}
      </Text>
      <Text size="xs" c="dimmed" lh={1.3}>
        {subtitle}
      </Text>
    </Stack>
  </Group>
);

/**
 * One setting inside a section: label, a short dimmed description, then the
 * control. `inline` puts the control to the right of the text instead (for a
 * switch), keeping the same label / description pair.
 */
const Field: React.FC<{
  label: React.ReactNode;
  description?: React.ReactNode;
  /** id of the control the label names (for a switch, whose own label is not used). */
  htmlFor?: string;
  inline?: boolean;
  testId?: string;
  children: React.ReactNode;
}> = ({ label, description, htmlFor, inline = false, testId, children }) => {
  const text = (
    <Stack gap={2} style={{ minWidth: 0, flex: 1 }}>
      <Text
        size="sm"
        fw={500}
        lh={1.3}
        component={htmlFor ? 'label' : 'div'}
        htmlFor={htmlFor}
        style={htmlFor ? { cursor: 'pointer' } : undefined}
      >
        {label}
      </Text>
      {description && (
        <Text size="xs" c="dimmed" lh={1.35}>
          {description}
        </Text>
      )}
    </Stack>
  );
  if (inline) {
    return (
      <Group gap="md" wrap="nowrap" align="flex-start" justify="space-between" data-testid={testId}>
        {text}
        <div style={{ flexShrink: 0, paddingTop: 2 }}>{children}</div>
      </Group>
    );
  }
  return (
    <Stack gap={6} data-testid={testId}>
      {text}
      {children}
    </Stack>
  );
};

/** A switch laid out as a Field: the text on the left labels it. */
const SwitchField: React.FC<{
  label: string;
  description: React.ReactNode;
  checked: boolean;
  onChange: (checked: boolean) => void;
  testId?: string;
}> = ({ label, description, checked, onChange, testId }) => {
  const id = React.useId();
  return (
    <Field label={label} description={description} htmlFor={id} inline>
      <Switch
        id={id}
        checked={checked}
        onChange={(e) => onChange(e.currentTarget.checked)}
        data-testid={testId}
      />
    </Field>
  );
};

// ---------------------------------------------------------------------------
// Your view (per browser)
// ---------------------------------------------------------------------------

/** A− / percent / A+ control for the dashboard content font-size preference
 *  (#854). Scales figures, tables and the other dashboard tiles — never the
 *  app chrome — and is a per-browser preference, so it renders in both the
 *  viewer and the editor. */
const FontSizeBlock: React.FC = () => {
  const { scale, increase, decrease, reset, canIncrease, canDecrease } = useUiScalePref();

  return (
    <Field
      label="Font size"
      description="Scales the figures, tables and cards. While editing, a figure can also carry its own font size from its tile menu."
      testId="font-size-section"
    >
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
    </Field>
  );
};

/** The reader's own page width (Full / Wide / Comfortable / Compact). Lives
 *  here only: a header button for it was one more control in a bar that
 *  already carries the dashboard's own actions. */
const PageWidthBlock: React.FC = () => {
  const { width, set } = useContentWidthPref();
  return (
    <Field
      label="Page width"
      description="How wide the dashboard runs on a large screen: Wide 1600px, Comfortable 1240px, Compact 1080px. Each tab remembers its own."
      testId="page-width-section"
    >
      <SegmentedControl
        size="xs"
        value={width}
        onChange={(value) => set(value as ContentWidth)}
        data={CONTENT_WIDTHS.map((w) => ({ value: w.value, label: w.label }))}
        data-testid="page-width-control"
      />
    </Field>
  );
};

// ---------------------------------------------------------------------------
// Tab defaults (editor, saved on the dashboard)
// ---------------------------------------------------------------------------

/** The dashboard-level defaults this drawer can change, saved on the tab. */
export type TabDefaults = Pick<
  DashboardData,
  'content_width_default' | 'filter_panel_default' | 'show_tab_header'
>;

/**
 * What a tab opens with before a viewer has chosen otherwise: its page width,
 * whether the filter panel starts open, whether its name sits above the
 * canvas. Saved with the dashboard for everyone, unlike "Your view", which is
 * the reader's own preference kept in their browser and wins over these.
 */
const TabDefaultsBlock: React.FC<{
  dashboard: DashboardData | null;
  onChange: (patch: TabDefaults) => void;
}> = ({ dashboard, onChange }) => (
  <Stack gap="sm" data-testid="tab-defaults-section">
    <Text size="xs" c="dimmed" lh={1.35}>
      These only set where the tab starts. A viewer who picks a page width or toggles the
      filter panel keeps their own choice.
    </Text>
    <Field label="Page width" description="The width the tab opens at.">
      <SegmentedControl
        size="xs"
        value={dashboard?.content_width_default ?? 'full'}
        onChange={(value) =>
          onChange({ content_width_default: value as TabDefaults['content_width_default'] })
        }
        data={CONTENT_WIDTHS.map((w) => ({ value: w.value, label: w.label }))}
        data-testid="tab-default-width-control"
      />
    </Field>
    <Field label="Filter panel" description="Whether the filter panel starts open or collapsed.">
      <SegmentedControl
        size="xs"
        value={dashboard?.filter_panel_default ?? 'open'}
        onChange={(value) =>
          onChange({ filter_panel_default: value === 'collapsed' ? 'collapsed' : 'open' })
        }
        data={[
          { value: 'open', label: 'Open' },
          { value: 'collapsed', label: 'Collapsed' },
        ]}
        data-testid="tab-default-filter-panel-control"
      />
    </Field>
    <SwitchField
      label="Show the tab's name"
      description="The tab's name and subtitle above its content. Turn off for a tab that opens on its own title, such as a landing page."
      checked={dashboard?.show_tab_header !== false}
      onChange={(checked) => onChange({ show_tab_header: checked })}
      testId="tab-default-header-switch"
    />
  </Stack>
);

// ---------------------------------------------------------------------------
// Branding (editor)
// ---------------------------------------------------------------------------

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
      <Text fw={500} size="sm" lh={1.3}>
        Logo
      </Text>
      <Text size="xs" c="dimmed" lh={1.35}>
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
  // A child tab with no brand of its own is drawn in its main tab's.
  const inherited = dashboard?.inherited_brand_theme ?? null;
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
  const resolved = useResolvedBrandTheme(customising ? value : (inherited ?? instance ?? {}));

  return (
    <Stack gap="sm" data-testid="dashboard-branding-section">
      <Field
        label="Source"
        description={
          customising
            ? 'Anything left empty still follows the instance branding.'
            : inherited
              ? "This tab uses the main tab's branding. Change it there for every tab, or customise this tab alone."
              : 'This dashboard uses the instance colors, logo and figure palette.'
        }
      >
        <SegmentedControl
          size="xs"
          value={customising ? 'custom' : 'inherit'}
          // Customising a tab that inherits starts from the main tab's brand,
          // so overriding one colour doesn't drop its logo and palette.
          onChange={(mode) => emit(mode === 'custom' ? (saved ?? inherited ?? {}) : null)}
          data={[
            { value: 'inherit', label: inherited ? 'Inherit main tab' : 'Inherit instance' },
            { value: 'custom', label: 'Customise' },
          ]}
          data-testid="dashboard-branding-mode"
        />
      </Field>

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
          <Field label="Preview" description="How the dashboard looks with these settings.">
            <BrandThemePreview theme={resolved} compact />
          </Field>
        </>
      )}
    </Stack>
  );
};


// ---------------------------------------------------------------------------
// Feedback
// ---------------------------------------------------------------------------

/**
 * The deployment's feedback link, as a labelled row.
 *
 * The header carries the same link as a bare icon, for reacting in the moment.
 * This is the other half: somewhere to find it when you went looking for it,
 * with a line saying what it is for. Both read the one config, so there is a
 * single place the URL can be wrong.
 */
const FeedbackBlock: React.FC<{ href: string; label: string }> = ({ href, label }) => (
  <Stack gap={6} data-testid="feedback-section">
    <Text size="xs" c="dimmed" lh={1.35}>
      Tell us what this dashboard gets wrong, or what it is missing. The link carries which
      dashboard you were on.
    </Text>
    <Anchor
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      size="sm"
      data-testid="feedback-link"
    >
      {label}
    </Anchor>
  </Stack>
);

// ---------------------------------------------------------------------------
// Drawer
// ---------------------------------------------------------------------------

type SectionKey = 'about' | 'view' | 'tab-defaults' | 'filtering' | 'branding' | 'feedback';

/** Which sections start open, per surface. The viewer is mostly about reading
 *  and adjusting one's own view; the editor opens on the metadata only, so the
 *  authoring sections don't all unfold at once. */
const DEFAULT_OPEN: Record<'viewer' | 'editor', SectionKey[]> = {
  viewer: ['about', 'view'],
  editor: ['about'],
};

const openSectionsKey = (surface: 'viewer' | 'editor') =>
  `depictio-settings-drawer-open:${surface}`;

function readOpenSections(surface: 'viewer' | 'editor'): SectionKey[] {
  try {
    const raw = localStorage.getItem(openSectionsKey(surface));
    if (raw) {
      const parsed: unknown = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.every((v) => typeof v === 'string')) {
        return parsed as SectionKey[];
      }
    }
  } catch {
    // Storage blocked or corrupt: fall back to the defaults.
  }
  return DEFAULT_OPEN[surface];
}

function writeOpenSections(surface: 'viewer' | 'editor', value: string[]) {
  try {
    localStorage.setItem(openSectionsKey(surface), JSON.stringify(value));
  } catch {
    // Remembering the open sections is a convenience; ignore failures.
  }
}

interface SettingsDrawerProps {
  opened: boolean;
  onClose: () => void;
  dashboard: DashboardData | null;
  /** Editor only: shows the Branding section. The viewer leaves this unset
   *  and the section is not rendered. */
  onChangeBrandTheme?: (theme: BrandTheme | null) => void;
  /** Editor only: persists the dashboard's `funnel_filtering` field (issue
   *  #939) and shows the Filtering section. */
  onToggleFunnelFiltering?: (enabled: boolean) => void;
  /** Editor only: uploads a dashboard logo (the server stamps it on the
   *  dashboard's brand theme) — reject to surface an error. */
  onUploadLogo?: (file: File) => Promise<void>;
  /** Editor only: saves the tab's display defaults (page width, filter panel,
   *  tab header) on its dashboard document, and shows the Tab defaults
   *  section. */
  onChangeTabDefaults?: (patch: TabDefaults) => void;
}

/**
 * Right-side drawer for the current dashboard, as collapsible sections. Each
 * section header says what it holds and who it affects:
 *
 * 1. About this dashboard: metadata (`DashboardInfoBody`, shared with the
 *    inspector's Info tab, which replaces this drawer when enabled).
 * 2. Your view: the reader's own font size (#854) and page width, kept in
 *    this browser.
 * 3. Tab defaults (editor): page width, filter panel and tab name the tab
 *    opens with, for everyone; a reader's own choice still wins.
 * 4. Filtering (editor): the funnel-filtering default (#939).
 * 5. Branding (editor): the dashboard's brand override (#397 — logo, colors,
 *    surfaces and figure palette, inheriting the main tab or instance).
 * 6. Feedback: the deployment's feedback link, when one is configured.
 *
 * Editor sections render only when their callback is given. Which sections
 * are open is remembered per browser, separately for viewer and editor.
 */
const SettingsDrawer: React.FC<SettingsDrawerProps> = ({
  opened,
  onClose,
  dashboard,
  onChangeBrandTheme,
  onToggleFunnelFiltering,
  onUploadLogo,
  onChangeTabDefaults,
}) => {
  const surface: 'viewer' | 'editor' =
    onChangeBrandTheme || onToggleFunnelFiltering || onChangeTabDefaults ? 'editor' : 'viewer';
  const [openSections, setOpenSections] = React.useState<string[]>(() =>
    readOpenSections(surface),
  );
  const handleSectionsChange = (value: string[]) => {
    setOpenSections(value);
    writeOpenSections(surface, value);
  };

  const feedback = useFeedbackLink({
    dashboard: dashboard?.title ?? null,
    dashboardId: dashboard?.dashboard_id ?? dashboard?._id ?? null,
    tab: null,
  });

  const section = (
    key: SectionKey,
    icon: string,
    title: string,
    subtitle: string,
    body: React.ReactNode,
  ) => (
    <Accordion.Item value={key} data-testid={`settings-section-${key}`}>
      <Accordion.Control>
        <SectionHeader icon={icon} title={title} subtitle={subtitle} />
      </Accordion.Control>
      <Accordion.Panel>{body}</Accordion.Panel>
    </Accordion.Item>
  );

  return (
    <Drawer
      opened={opened}
      onClose={onClose}
      position="right"
      size="md"
      // Above the floating map card, so the drawer's overlay dims it like the
      // rest of the dashboard instead of leaving it lit on top.
      zIndex={Z_LAYERS.overlay}
      title={
        <Group gap="xs">
          <Icon icon="mdi:cog" width={20} />
          <Text fw={600}>Dashboard settings</Text>
        </Group>
      }
    >
      <Accordion
        multiple
        variant="separated"
        radius="md"
        chevronPosition="right"
        value={openSections}
        onChange={handleSectionsChange}
        // A flex gap rather than the separated variant's md margin between
        // items, so the drawer stays compact.
        style={{ display: 'flex', flexDirection: 'column', gap: 'var(--mantine-spacing-xs)' }}
        styles={{
          item: { marginTop: 0 },
          control: { paddingInline: 'var(--mantine-spacing-sm)' },
          label: { paddingBlock: 'var(--mantine-spacing-xs)' },
          content: {
            paddingInline: 'var(--mantine-spacing-sm)',
            paddingTop: 'var(--mantine-spacing-xs)',
            paddingBottom: 'var(--mantine-spacing-sm)',
          },
        }}
      >
        {section(
          'about',
          'mdi:information-outline',
          'About this dashboard',
          'Project, template, run and owner',
          <DashboardInfoBody dashboard={dashboard} active={opened} />,
        )}
        {section(
          'view',
          'mdi:monitor-eye',
          'Your view',
          'Only for you, saved in this browser',
          <Stack gap="md">
            <FontSizeBlock />
            <PageWidthBlock />
          </Stack>,
        )}
        {onChangeTabDefaults &&
          section(
            'tab-defaults',
            'mdi:tab',
            'Tab defaults',
            'What this tab opens with, for everyone',
            <TabDefaultsBlock dashboard={dashboard} onChange={onChangeTabDefaults} />,
          )}
        {onToggleFunnelFiltering &&
          section(
            'filtering',
            'mdi:filter-variant',
            'Filtering',
            'How the filters behave on this dashboard, for everyone',
            <SwitchField
              label="Funnel filtering by default"
              description="Highlight, in every other filter, the values that still lead to a non-empty result set. Viewers can still turn it off from the filter panel."
              checked={dashboard?.funnel_filtering !== false}
              onChange={onToggleFunnelFiltering}
              testId="funnel-filtering-default-switch"
            />,
          )}
        {onChangeBrandTheme &&
          section(
            'branding',
            'mdi:palette-outline',
            'Branding',
            'Logo, colours and figure palette, for everyone',
            <BrandingBlock
              dashboard={dashboard}
              onChange={onChangeBrandTheme}
              onUploadLogo={onUploadLogo}
              opened={opened}
            />,
          )}
        {feedback &&
          section(
            'feedback',
            'mdi:comment-quote-outline',
            'Feedback',
            'Report a problem or suggest an improvement',
            <FeedbackBlock href={feedback.href} label={feedback.label} />,
          )}
      </Accordion>
    </Drawer>
  );
};

export default SettingsDrawer;
