import React from 'react';
import {
  Accordion,
  ActionIcon,
  Anchor,
  Box,
  Button,
  Divider,
  Drawer,
  FileButton,
  Group,
  Modal,
  NavLink,
  ScrollArea,
  SegmentedControl,
  Select,
  Stack,
  Switch,
  Text,
  Tooltip,
} from '@mantine/core';
import { useMediaQuery } from '@mantine/hooks';
import { Icon } from '@iconify/react';

import {
  BrandThemeForm,
  BrandThemePreview,
  isEmptyBrandTheme,
  useBrandScopeAttributes,
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

/** A bare glyph in the (dashboard's) primary colour, the way the chrome draws
 *  its icons elsewhere (`SectionIcon`, the sidebar): a tinted square read as a
 *  button in a row that already carries a chevron. */
const SECTION_ICON_STYLE: React.CSSProperties = {
  color: 'var(--mantine-primary-color-filled)',
  flexShrink: 0,
};

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
    <Icon icon={icon} width={20} height={20} style={SECTION_ICON_STYLE} />
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
// Sections
// ---------------------------------------------------------------------------

type SectionKey = 'about' | 'view' | 'tab-defaults' | 'filtering' | 'branding' | 'feedback';
type Surface = 'viewer' | 'editor';

/** One settings section: what both layouts draw, so neither carries its own
 *  copy of the contents. */
interface SettingsSection {
  key: SectionKey;
  icon: string;
  title: string;
  /** Shorter name for the nav rail, when the title would wrap there. */
  navLabel?: string;
  /** What the section is for and who it affects. */
  subtitle: string;
  body: React.ReactNode;
}

/**
 * Which layout the settings use.
 *
 * - `nav`: a wide modal laid out like GitHub's or VS Code's settings, a rail
 *   of sections on the left and the active one as a page on the right.
 * - `accordion`: the earlier right-hand drawer of collapsible sections, kept
 *   for comparison.
 */
export type SettingsLayout = 'nav' | 'accordion';
const DEFAULT_LAYOUT: SettingsLayout = 'nav';

// ---------------------------------------------------------------------------
// Per-browser memory (both layouts)
// ---------------------------------------------------------------------------

function readStored<T>(key: string, valid: (v: unknown) => v is T): T | null {
  try {
    const raw = localStorage.getItem(key);
    if (raw) {
      const parsed: unknown = JSON.parse(raw);
      if (valid(parsed)) return parsed;
    }
  } catch {
    // Storage blocked or corrupt: the caller falls back to its default.
  }
  return null;
}

function writeStored(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Remembering a layout detail is a convenience; ignore failures.
  }
}

const isStringArray = (v: unknown): v is string[] =>
  Array.isArray(v) && v.every((x) => typeof x === 'string');
const isString = (v: unknown): v is string => typeof v === 'string';

// ---------------------------------------------------------------------------
// Accordion layout
// ---------------------------------------------------------------------------

/** Which sections start open in the accordion, per surface. The viewer is
 *  mostly about reading and adjusting one's own view; the editor opens on the
 *  metadata only, so the authoring sections don't all unfold at once. */
const DEFAULT_OPEN: Record<Surface, SectionKey[]> = {
  viewer: ['about', 'view'],
  editor: ['about'],
};

const AccordionLayout: React.FC<{
  sections: SettingsSection[];
  surface: Surface;
}> = ({ sections, surface }) => {
  const storageKey = `depictio-settings-drawer-open:${surface}`;
  const [open, setOpen] = React.useState<string[]>(
    () => readStored(storageKey, isStringArray) ?? DEFAULT_OPEN[surface],
  );
  return (
    <Accordion
      multiple
      variant="separated"
      radius="md"
      chevronPosition="right"
      value={open}
      onChange={(value) => {
        setOpen(value);
        writeStored(storageKey, value);
      }}
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
      {sections.map((s) => (
        <Accordion.Item key={s.key} value={s.key} data-testid={`settings-section-${s.key}`}>
          <Accordion.Control>
            <SectionHeader icon={s.icon} title={s.title} subtitle={s.subtitle} />
          </Accordion.Control>
          <Accordion.Panel>{s.body}</Accordion.Panel>
        </Accordion.Item>
      ))}
    </Accordion>
  );
};

// ---------------------------------------------------------------------------
// Nav layout
// ---------------------------------------------------------------------------

/** The section a surface opens on before the reader has picked one: a
 *  viewer's own display options, or the editor's tab defaults (what an author
 *  most often comes here to change; About is one click up the rail). */
const DEFAULT_ACTIVE: Record<Surface, SectionKey> = {
  viewer: 'view',
  editor: 'tab-defaults',
};

/** Below this the rail no longer fits beside the page and becomes a select. */
const NARROW_QUERY = '(max-width: 640px)';

const RAIL_WIDTH = 220;

const NavLayout: React.FC<{
  sections: SettingsSection[];
  surface: Surface;
}> = ({ sections, surface }) => {
  const storageKey = `depictio-settings-active:${surface}`;
  const [stored, setStored] = React.useState<string | null>(() =>
    readStored(storageKey, isString),
  );
  const narrow = useMediaQuery(NARROW_QUERY, false, { getInitialValueInEffect: false });

  // A remembered section can be missing today (no feedback link configured,
  // or an editor-only one in the viewer): fall back rather than draw nothing.
  const active =
    sections.find((s) => s.key === stored) ??
    sections.find((s) => s.key === DEFAULT_ACTIVE[surface]) ??
    sections[0];
  const select = (key: string) => {
    setStored(key);
    writeStored(storageKey, key);
  };

  const page = active && (
    <Stack gap="lg" data-testid={`settings-section-${active.key}`}>
      {narrow ? (
        // The select above already names the section; repeating it as a
        // heading on a phone only pushes the fields down.
        <Text size="sm" c="dimmed">
          {active.subtitle}
        </Text>
      ) : (
        <Stack gap={2}>
          <Group gap="sm" wrap="nowrap">
            <Icon icon={active.icon} width={22} height={22} style={SECTION_ICON_STYLE} />
            <Text fw={600} size="lg" lh={1.25}>
              {active.title}
            </Text>
          </Group>
          <Text size="sm" c="dimmed">
            {active.subtitle}
          </Text>
        </Stack>
      )}
      <Divider />
      {active.body}
    </Stack>
  );

  if (narrow) {
    return (
      <Stack gap="md">
        <Select
          aria-label="Settings section"
          value={active?.key ?? null}
          onChange={(value) => value && select(value)}
          data={sections.map((s) => ({ value: s.key, label: s.title }))}
          allowDeselect={false}
          comboboxProps={{ zIndex: Z_LAYERS.tooltip }}
          leftSection={
            active ? <Icon icon={active.icon} width={16} style={SECTION_ICON_STYLE} /> : null
          }
          data-testid="settings-nav-select"
        />
        {page}
      </Stack>
    );
  }

  return (
    <Group
      align="stretch"
      gap={0}
      wrap="nowrap"
      // A fixed height, so moving between a short and a long section doesn't
      // make the dialog jump.
      h="min(640px, calc(100dvh - 140px))"
    >
      <Stack
        w={RAIL_WIDTH}
        gap={0}
        justify="space-between"
        p="sm"
        style={{
          flexShrink: 0,
          borderRight: '1px solid var(--mantine-color-default-border)',
          background: 'var(--mantine-color-default-hover)',
        }}
      >
        <Stack gap={2} component="nav" aria-label="Settings sections">
          {sections.map((s) => {
            const isActive = s.key === active?.key;
            return (
              <NavLink
                key={s.key}
                label={s.navLabel ?? s.title}
                active={isActive}
                variant="light"
                onClick={() => select(s.key)}
                leftSection={
                  <Icon
                    icon={s.icon}
                    width={18}
                    height={18}
                    style={{
                      flexShrink: 0,
                      color: isActive
                        ? 'var(--mantine-primary-color-filled)'
                        : 'var(--mantine-color-dimmed)',
                    }}
                  />
                }
                styles={{
                  root: { borderRadius: 'var(--mantine-radius-sm)' },
                  label: { fontWeight: isActive ? 600 : 500 },
                }}
                data-testid={`settings-nav-${s.key}`}
              />
            );
          })}
        </Stack>
        <Group gap={6} wrap="nowrap" px={6} pt="sm">
          <Icon
            icon="mdi:check-circle-outline"
            width={14}
            style={{ color: 'var(--mantine-color-dimmed)', flexShrink: 0 }}
          />
          <Text size="xs" c="dimmed" lh={1.3}>
            Changes save as you make them.
          </Text>
        </Group>
      </Stack>
      <ScrollArea style={{ flex: 1 }} type="auto">
        <Box px="xl" py="lg" maw={620}>
          {page}
        </Box>
      </ScrollArea>
    </Group>
  );
};

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

interface SettingsDrawerProps {
  opened: boolean;
  onClose: () => void;
  dashboard: DashboardData | null;
  /** Which layout to draw. Defaults to `nav`; `accordion` keeps the earlier
   *  drawer available for comparison. */
  layout?: SettingsLayout;
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
 * The current dashboard's settings, in sections that each say what they hold
 * and who they affect:
 *
 * 1. About this dashboard: metadata (`DashboardInfoBody`, shared with the
 *    inspector's Info tab, which replaces these settings when enabled).
 * 2. Your view: the reader's own font size (#854) and page width, kept in
 *    this browser.
 * 3. Tab defaults (editor): page width, filter panel and tab name the tab
 *    opens with, for everyone; a reader's own choice still wins.
 * 4. Filtering (editor): the funnel-filtering default (#939).
 * 5. Branding (editor): the dashboard's brand override (#397 — logo, colors,
 *    surfaces and figure palette, inheriting the main tab or instance).
 * 6. Feedback: the deployment's feedback link, when one is configured.
 *
 * Editor sections render only when their callback is given. Two layouts draw
 * the same sections (see `SettingsLayout`): by default a wide modal with a
 * section rail, remembering the last section per browser (viewer and editor
 * apart); or the earlier drawer of collapsible sections, remembering which
 * are open.
 *
 * Both are portaled to <body>, outside the dashboard's BrandScope wrapper, so
 * the root carries the scope's attributes to stay in the dashboard's brand.
 */
const SettingsDrawer: React.FC<SettingsDrawerProps> = ({
  opened,
  onClose,
  dashboard,
  layout = DEFAULT_LAYOUT,
  onChangeBrandTheme,
  onToggleFunnelFiltering,
  onUploadLogo,
  onChangeTabDefaults,
}) => {
  const surface: Surface =
    onChangeBrandTheme || onToggleFunnelFiltering || onChangeTabDefaults ? 'editor' : 'viewer';
  const brandScope = useBrandScopeAttributes();

  const feedback = useFeedbackLink({
    dashboard: dashboard?.title ?? null,
    dashboardId: dashboard?.dashboard_id ?? dashboard?._id ?? null,
    tab: null,
  });

  const sections: SettingsSection[] = [
    {
      key: 'about',
      icon: 'mdi:information-outline',
      title: 'About this dashboard',
      navLabel: 'About',
      subtitle: 'Project, template, run and owner',
      body: <DashboardInfoBody dashboard={dashboard} active={opened} />,
    },
    {
      key: 'view',
      icon: 'mdi:monitor-eye',
      title: 'Your view',
      subtitle: 'Only for you, saved in this browser',
      body: (
        <Stack gap="lg">
          <FontSizeBlock />
          <PageWidthBlock />
        </Stack>
      ),
    },
  ];
  if (onChangeTabDefaults) {
    sections.push({
      key: 'tab-defaults',
      icon: 'mdi:tab',
      title: 'Tab defaults',
      subtitle: 'What this tab opens with, for everyone',
      body: <TabDefaultsBlock dashboard={dashboard} onChange={onChangeTabDefaults} />,
    });
  }
  if (onToggleFunnelFiltering) {
    sections.push({
      key: 'filtering',
      icon: 'mdi:filter-variant',
      title: 'Filtering',
      subtitle: 'How the filters behave on this dashboard, for everyone',
      body: (
        <SwitchField
          label="Funnel filtering by default"
          description="Highlight, in every other filter, the values that still lead to a non-empty result set. Viewers can still turn it off from the filter panel."
          checked={dashboard?.funnel_filtering !== false}
          onChange={onToggleFunnelFiltering}
          testId="funnel-filtering-default-switch"
        />
      ),
    });
  }
  if (onChangeBrandTheme) {
    sections.push({
      key: 'branding',
      icon: 'mdi:palette-outline',
      title: 'Branding',
      subtitle: 'Logo, colours and figure palette, for everyone',
      body: (
        <BrandingBlock
          dashboard={dashboard}
          onChange={onChangeBrandTheme}
          onUploadLogo={onUploadLogo}
          opened={opened}
        />
      ),
    });
  }
  if (feedback) {
    sections.push({
      key: 'feedback',
      icon: 'mdi:comment-quote-outline',
      title: 'Feedback',
      subtitle: 'Report a problem or suggest an improvement',
      body: <FeedbackBlock href={feedback.href} label={feedback.label} />,
    });
  }

  const title = (
    <Group gap="xs">
      <Icon icon="ic:baseline-settings" width={20} height={20} style={SECTION_ICON_STYLE} />
      <Text fw={600}>Dashboard settings</Text>
    </Group>
  );
  const rootProps = {
    className: brandScope?.className,
    'data-mantine-color-scheme': brandScope?.['data-mantine-color-scheme'],
    // Above the floating map card, so the overlay dims it like the rest of
    // the dashboard instead of leaving it lit on top.
    zIndex: Z_LAYERS.overlay,
  };

  if (layout === 'accordion') {
    return (
      <Drawer
        opened={opened}
        onClose={onClose}
        position="right"
        size="md"
        title={title}
        {...rootProps}
      >
        <AccordionLayout sections={sections} surface={surface} />
      </Drawer>
    );
  }

  return (
    <SettingsModal opened={opened} onClose={onClose} title={title} rootProps={rootProps}>
      <NavLayout sections={sections} surface={surface} />
    </SettingsModal>
  );
};

/** The nav layout's frame: a wide modal, full screen on a phone, with no
 *  body padding so the rail runs edge to edge. */
const SettingsModal: React.FC<{
  opened: boolean;
  onClose: () => void;
  title: React.ReactNode;
  rootProps: Record<string, unknown>;
  children: React.ReactNode;
}> = ({ opened, onClose, title, rootProps, children }) => {
  const narrow = useMediaQuery(NARROW_QUERY, false, { getInitialValueInEffect: false });
  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={title}
      size={860}
      fullScreen={narrow}
      radius="md"
      centered
      data-testid="settings-modal"
      styles={{
        header: { borderBottom: '1px solid var(--mantine-color-default-border)' },
        body: narrow ? { paddingTop: 'var(--mantine-spacing-md)' } : { padding: 0 },
      }}
      {...rootProps}
    >
      {children}
    </Modal>
  );
};

export default SettingsDrawer;
