import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Alert,
  Button,
  FileButton,
  Grid,
  Group,
  Loader,
  Menu,
  Paper,
  ScrollArea,
  Stack,
  Text,
  Title,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { notifications } from '@mantine/notifications';

import {
  BrandThemeForm,
  BrandThemePreview,
  fetchBrandingAdmin,
  fetchBrandPresets,
  isEmptyBrandTheme,
  resetBrandingAdmin,
  updateBrandingAdmin,
  uploadBrandingLogo,
  useResolvedBrandTheme,
} from 'depictio-react-core';
import type { AdminBrandingState, BrandPreset, BrandTheme } from 'depictio-react-core';
import { setBranding } from '../branding';

/** Client-side mirror of the server's upload cap. */
const LOGO_MAX_BYTES = 2 * 1024 * 1024;

/** Push the saved branding into this tab's live theme + localStorage cache, so
 *  the admin sees the result immediately; other visitors pick it up on their
 *  next /utils/public-config fetch. */
function applyEffective(state: AdminBrandingState) {
  setBranding(state.effective);
}

/** The logo fields of the current draft, carried across a palette-shaped
 *  change: a preset and an imported theme file are both a palette, not an
 *  identity, so neither drops an uploaded logo unless it names one itself. */
function carriedLogos(
  draft: BrandTheme | null,
): Pick<BrandTheme, 'logo_mode' | 'logo_url' | 'logo_url_dark'> {
  return {
    logo_mode: draft?.logo_mode,
    logo_url: draft?.logo_url,
    logo_url_dark: draft?.logo_url_dark,
  };
}

const LogoField: React.FC<{
  label: string;
  hint: string;
  value: string | null | undefined;
  envDefault: string | null | undefined;
  uploading: boolean;
  onUpload: (file: File | null) => void;
  onClear: () => void;
}> = ({ label, hint, value, envDefault, uploading, onUpload, onClear }) => (
  <Stack gap={6}>
    <Text fw={500} size="xs">
      {label}
    </Text>
    <Text size="xs" c="dimmed">
      {hint}
    </Text>
    <Group gap="xs" align="center">
      <FileButton onChange={onUpload} accept="image/png,image/jpeg,image/webp">
        {(props) => (
          <Button
            {...props}
            variant="default"
            size="xs"
            loading={uploading}
            leftSection={<Icon icon="mdi:upload" width={14} />}
          >
            {value ? 'Replace' : 'Upload'}
          </Button>
        )}
      </FileButton>
      {value && (
        <Tooltip label="Remove the override (deployment default applies)" withArrow>
          <Button variant="subtle" color="red" size="xs" onClick={onClear}>
            Clear
          </Button>
        </Tooltip>
      )}
      {(value ?? envDefault) && (
        <img
          src={value ?? envDefault ?? undefined}
          alt=""
          style={{ height: 32, maxWidth: 160, objectFit: 'contain' }}
        />
      )}
      {!value && envDefault && (
        <Text size="xs" c="dimmed">
          (deployment default)
        </Text>
      )}
    </Group>
  </Stack>
);

/**
 * Admin Branding panel (issue #397): live overrides of the
 * `DEPICTIO_BRANDING_*` env defaults — name, logos, brand and status colors,
 * surfaces, typography and figure defaults — persisted server-side and served
 * to every visitor through `/utils/public-config`. A cleared field falls back
 * to the deployment default, and "Reset all" returns the whole instance to its
 * env-var configuration.
 *
 * Two columns: the form on the left, a live preview on the right rendered from
 * the *draft* under its own scoped MantineProvider. Nothing here needs a save
 * to be seen, which is the whole point — a palette is a thing you judge by
 * looking at it.
 */
const AdminBrandingPanel: React.FC = () => {
  const [state, setState] = useState<AdminBrandingState | null>(null);
  const [form, setForm] = useState<BrandTheme | null>(null);
  const [presets, setPresets] = useState<BrandPreset[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState<'light' | 'dark' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const importRef = useRef<HTMLInputElement>(null);

  const adopt = useCallback((next: AdminBrandingState) => {
    setState(next);
    setForm(next.overrides ?? {});
  }, []);

  useEffect(() => {
    fetchBrandingAdmin()
      .then(adopt)
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load branding.'))
      .finally(() => setLoading(false));
    fetchBrandPresets().then(setPresets);
  }, [adopt]);

  // The preview follows the draft, not the saved state, and needs the derived
  // figure colors — which only the server computes (see useResolvedBrandTheme).
  const resolved = useResolvedBrandTheme(form ?? {});

  const handleSave = async () => {
    if (!form) return;
    setSaving(true);
    try {
      const next = await updateBrandingAdmin(form);
      adopt(next);
      applyEffective(next);
      notifications.show({ message: 'Branding saved.' });
    } catch (err) {
      notifications.show({
        message: err instanceof Error ? err.message : 'Failed to save branding.',
        color: 'red',
      });
    } finally {
      setSaving(false);
    }
  };

  const handleReset = async () => {
    setSaving(true);
    try {
      const next = await resetBrandingAdmin();
      adopt(next);
      applyEffective(next);
      notifications.show({ message: 'Branding reset to deployment defaults.' });
    } catch (err) {
      notifications.show({
        message: err instanceof Error ? err.message : 'Failed to reset branding.',
        color: 'red',
      });
    } finally {
      setSaving(false);
    }
  };

  const handleLogoUpload = (variant: 'light' | 'dark') => async (file: File | null) => {
    if (!file) return;
    if (file.size > LOGO_MAX_BYTES) {
      notifications.show({ message: 'File is too large (max 2MB).', color: 'red' });
      return;
    }
    setUploading(variant);
    try {
      const next = await uploadBrandingLogo(variant, file);
      adopt(next);
      applyEffective(next);
    } catch (err) {
      notifications.show({
        message: err instanceof Error ? err.message : 'Upload failed.',
        color: 'red',
      });
    } finally {
      setUploading(null);
    }
  };

  /** A preset seeds the form; it is not applied until Save, like every other
   *  edit here. Logos and the instance name are left alone. */
  const applyPreset = (preset: BrandPreset) =>
    setForm((prev) => ({
      ...carriedLogos(prev),
      app_name: prev?.app_name,
      ...preset.theme,
    }));

  const handleExport = () => {
    const blob = new Blob([JSON.stringify(form ?? {}, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${(form?.app_name || 'depictio').toLowerCase().replace(/\s+/g, '-')}-brand-theme.json`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const handleImport = async (file: File | null) => {
    if (!file) return;
    try {
      const parsed = JSON.parse(await file.text());
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new Error('Not a brand theme object.');
      }
      // Seeded into the form, not saved: the admin still sees it in the
      // preview and decides. Unknown keys are rejected server-side on Save.
      // Carrying the logos matters here because Save replaces the whole
      // document: without it an import dropped `logo_url` and left the
      // uploaded image behind, orphaned.
      setForm((prev) => ({ ...carriedLogos(prev), ...(parsed as BrandTheme) }));
      notifications.show({ message: 'Theme imported — review the preview, then Save.' });
    } catch (err) {
      notifications.show({
        message: err instanceof Error ? err.message : 'Could not read that file.',
        color: 'red',
      });
    }
  };

  if (loading) {
    return (
      <Group justify="center" py="xl">
        <Loader />
      </Group>
    );
  }
  if (error || !form || !state) {
    return (
      <Alert color="red" icon={<Icon icon="mdi:alert-circle-outline" width={18} />}>
        {error ?? 'Failed to load branding.'}
      </Alert>
    );
  }

  const env = state.env_defaults;
  const hasOverrides = !isEmptyBrandTheme(state.overrides);

  return (
    <Stack gap="md" data-testid="admin-branding-panel">
      <Group justify="space-between" align="flex-end" wrap="wrap">
        <Stack gap={4} style={{ flex: 1, minWidth: 280 }}>
          <Title order={4}>Instance branding</Title>
          <Text size="sm" c="dimmed">
            Rebrand this deployment without touching its configuration: name, logos, colors,
            surfaces and figure palette apply to every visitor. Cleared fields fall back to
            the deployment&apos;s <code>DEPICTIO_BRANDING_*</code> defaults.
          </Text>
        </Stack>
        <Group gap="xs">
          {presets.length > 0 && (
            <Menu position="bottom-end" withinPortal shadow="md">
              <Menu.Target>
                <Button
                  variant="default"
                  size="xs"
                  leftSection={<Icon icon="mdi:palette-swatch" width={14} />}
                  data-testid="branding-preset-menu"
                >
                  Presets
                </Button>
              </Menu.Target>
              <Menu.Dropdown>
                {presets.map((preset) => (
                  <Menu.Item
                    key={preset.id}
                    onClick={() => applyPreset(preset)}
                    data-testid={`branding-preset-${preset.id}`}
                    leftSection={
                      <Group gap={2} wrap="nowrap">
                        {[preset.preview.primary, preset.preview.secondary, preset.preview.tertiary]
                          .filter(Boolean)
                          .map((color) => (
                            <div
                              key={color as string}
                              style={{
                                width: 10,
                                height: 10,
                                borderRadius: 2,
                                background: color as string,
                              }}
                            />
                          ))}
                      </Group>
                    }
                  >
                    {preset.label}
                  </Menu.Item>
                ))}
              </Menu.Dropdown>
            </Menu>
          )}
          <Button
            variant="default"
            size="xs"
            leftSection={<Icon icon="mdi:tray-arrow-up" width={14} />}
            onClick={() => importRef.current?.click()}
          >
            Import
          </Button>
          {/* A bare input rather than Mantine's FileButton: re-importing the
              same file must re-fire, which needs the value reset on open. */}
          <input
            ref={importRef}
            type="file"
            accept="application/json,.json"
            hidden
            onChange={(e) => {
              void handleImport(e.currentTarget.files?.[0] ?? null);
              e.currentTarget.value = '';
            }}
            data-testid="branding-import"
          />
          <Button
            variant="default"
            size="xs"
            leftSection={<Icon icon="mdi:tray-arrow-down" width={14} />}
            onClick={handleExport}
            data-testid="branding-export"
          >
            Export
          </Button>
        </Group>
      </Group>

      <Grid gutter="md" align="flex-start">
        <Grid.Col span={{ base: 12, md: 7 }}>
          <Paper withBorder p="md">
            <BrandThemeForm
              scope="instance"
              value={form}
              defaults={env}
              onChange={setForm}
              logoSlot={
                <Stack gap="sm">
                  <LogoField
                    label="Logo"
                    hint="Replaces the depictio logo in the sidebar and on the login page. PNG, JPEG or WebP, up to 2MB."
                    value={form.logo_url}
                    envDefault={env.logo_url}
                    uploading={uploading === 'light'}
                    onUpload={handleLogoUpload('light')}
                    onClear={() => setForm({ ...form, logo_url: null, logo_mode: null })}
                  />
                  <LogoField
                    label="Logo (dark mode)"
                    hint="Optional dark-mode variant; falls back to the logo above."
                    value={form.logo_url_dark}
                    envDefault={env.logo_url_dark}
                    uploading={uploading === 'dark'}
                    onUpload={handleLogoUpload('dark')}
                    onClear={() => setForm({ ...form, logo_url_dark: null })}
                  />
                </Stack>
              }
            />
          </Paper>
        </Grid.Col>

        <Grid.Col span={{ base: 12, md: 5 }}>
          {/* Sticky so the preview stays in view while the form scrolls past
              it — judging a palette means watching it while you change it. */}
          <Stack gap="xs" style={{ position: 'sticky', top: 16 }}>
            <Text fw={600} size="sm">
              Preview
            </Text>
            <ScrollArea.Autosize mah="calc(100vh - 220px)" type="auto">
              <BrandThemePreview theme={resolved} />
            </ScrollArea.Autosize>
          </Stack>
        </Grid.Col>
      </Grid>

      <Group justify="space-between">
        <Button
          variant="subtle"
          color="red"
          disabled={!hasOverrides || saving}
          onClick={handleReset}
          leftSection={<Icon icon="mdi:restore" width={16} />}
          data-testid="branding-reset"
        >
          Reset all to deployment defaults
        </Button>
        <Button
          onClick={handleSave}
          loading={saving}
          leftSection={<Icon icon="mdi:content-save" width={16} />}
          data-testid="branding-save"
        >
          Save
        </Button>
      </Group>
    </Stack>
  );
};

export default AdminBrandingPanel;
