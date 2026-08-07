import React, { useCallback, useEffect, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Button,
  ColorInput,
  Divider,
  FileButton,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
  TextInput,
  Title,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { notifications } from '@mantine/notifications';

import {
  fetchBrandingAdmin,
  resetBrandingAdmin,
  updateBrandingAdmin,
  uploadBrandingLogo,
} from 'depictio-react-core';
import type { AdminBrandingState, BrandingFields } from 'depictio-react-core';
import { setBranding } from '../branding';

const HEX_RE = /^#([0-9a-fA-F]{6})$/;
/** Client-side mirror of the server's upload cap. */
const LOGO_MAX_BYTES = 2 * 1024 * 1024;

interface FormState {
  app_name: string;
  primary_color: string;
  colorway: string[];
  logo_url: string | null;
  logo_url_dark: string | null;
}

function formFromOverrides(overrides: Partial<BrandingFields>): FormState {
  return {
    app_name: overrides.app_name ?? '',
    primary_color: overrides.primary_color ?? '',
    colorway: overrides.colorway ? [...overrides.colorway] : [],
    logo_url: overrides.logo_url ?? null,
    logo_url_dark: overrides.logo_url_dark ?? null,
  };
}

function overridesFromForm(form: FormState): Partial<BrandingFields> {
  return {
    app_name: form.app_name.trim() || null,
    primary_color: form.primary_color.trim() || null,
    colorway: form.colorway.length ? form.colorway : null,
    logo_url: form.logo_url,
    logo_url_dark: form.logo_url_dark,
  };
}

/** Push the saved branding into this tab's live theme + localStorage cache, so
 *  the admin sees the result immediately; other visitors pick it up on their
 *  next /utils/public-config fetch. */
function applyEffective(state: AdminBrandingState) {
  setBranding(state.effective);
}

const LogoField: React.FC<{
  label: string;
  hint: string;
  value: string | null;
  envDefault: string | null;
  uploading: boolean;
  onUpload: (file: File | null) => void;
  onClear: () => void;
}> = ({ label, hint, value, envDefault, uploading, onUpload, onClear }) => (
  <Stack gap={6}>
    <Text fw={500} size="sm">
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
 * Admin Branding panel (issue #397 follow-up): live, per-field overrides of
 * the `DEPICTIO_BRANDING_*` env defaults — instance name, primary UI color,
 * default figure colorway and logos — persisted server-side and served to
 * every visitor through `/utils/public-config`. A cleared field falls back
 * to the deployment default, and "Reset all" returns the whole instance to
 * its env-var configuration.
 */
const AdminBrandingPanel: React.FC = () => {
  const [state, setState] = useState<AdminBrandingState | null>(null);
  const [form, setForm] = useState<FormState | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState<'light' | 'dark' | null>(null);
  const [error, setError] = useState<string | null>(null);

  const adopt = useCallback((next: AdminBrandingState) => {
    setState(next);
    setForm(formFromOverrides(next.overrides));
  }, []);

  useEffect(() => {
    fetchBrandingAdmin()
      .then(adopt)
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load branding.'))
      .finally(() => setLoading(false));
  }, [adopt]);

  const patchForm = (patch: Partial<FormState>) =>
    setForm((prev) => (prev ? { ...prev, ...patch } : prev));

  const colorwayValid = !form || form.colorway.every((c) => HEX_RE.test(c));

  const handleSave = async () => {
    if (!form) return;
    setSaving(true);
    try {
      const next = await updateBrandingAdmin(overridesFromForm(form));
      adopt(next);
      applyEffective(next);
      notifications.show({ message: 'Branding saved.', color: 'teal' });
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
      notifications.show({ message: 'Branding reset to deployment defaults.', color: 'teal' });
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
  const hasOverrides = Object.keys(state.overrides).length > 0;

  return (
    <Stack gap="md" maw={640} data-testid="admin-branding-panel">
      <Stack gap={4}>
        <Title order={4}>Instance branding</Title>
        <Text size="sm" c="dimmed">
          Rebrand this deployment (e.g. for a core facility) without touching its
          configuration: name, logos and colors apply to every visitor. Cleared fields fall
          back to the deployment&apos;s <code>DEPICTIO_BRANDING_*</code> defaults.
        </Text>
      </Stack>

      <Paper withBorder p="md">
        <Stack gap="md">
          <TextInput
            label="Instance name"
            description="Browser tab title and login-page greeting."
            placeholder={env.app_name ?? 'Depictio'}
            value={form.app_name}
            onChange={(e) => patchForm({ app_name: e.currentTarget.value })}
            data-testid="branding-app-name"
          />
          <ColorInput
            label="Primary UI color"
            description="Buttons, links and accents across the whole app."
            placeholder={env.primary_color ?? 'Default (blue)'}
            value={form.primary_color}
            onChange={(value) => patchForm({ primary_color: value })}
            format="hex"
            data-testid="branding-primary-color"
          />

          <Divider />

          <LogoField
            label="Logo"
            hint="Replaces the depictio logo in the sidebar and on the login page. PNG, JPEG or WebP, up to 2MB."
            value={form.logo_url}
            envDefault={env.logo_url}
            uploading={uploading === 'light'}
            onUpload={handleLogoUpload('light')}
            onClear={() => patchForm({ logo_url: null })}
          />
          <LogoField
            label="Logo (dark mode)"
            hint="Optional dark-mode variant; falls back to the logo above."
            value={form.logo_url_dark}
            envDefault={env.logo_url_dark}
            uploading={uploading === 'dark'}
            onUpload={handleLogoUpload('dark')}
            onClear={() => patchForm({ logo_url_dark: null })}
          />

          <Divider />

          <Stack gap={6}>
            <Text fw={500} size="sm">
              Figure color palette
            </Text>
            <Text size="xs" c="dimmed">
              Default categorical colorway of server-rendered figures. Dashboards and
              individual figures can still pick their own.
            </Text>
            {form.colorway.map((color, idx) => (
              // eslint-disable-next-line react/no-array-index-key
              <Group key={idx} gap="xs" wrap="nowrap">
                <ColorInput
                  size="xs"
                  value={color}
                  onChange={(value) =>
                    patchForm({
                      colorway: form.colorway.map((c, i) => (i === idx ? value : c)),
                    })
                  }
                  format="hex"
                  style={{ flex: 1 }}
                />
                <Tooltip label="Remove color" withArrow>
                  <ActionIcon
                    variant="subtle"
                    color="red"
                    size="sm"
                    onClick={() =>
                      patchForm({ colorway: form.colorway.filter((_, i) => i !== idx) })
                    }
                    aria-label="Remove color"
                  >
                    <Icon icon="mdi:close" width={14} />
                  </ActionIcon>
                </Tooltip>
              </Group>
            ))}
            <Group gap="xs">
              <Button
                variant="default"
                size="compact-xs"
                leftSection={<Icon icon="mdi:plus" width={14} />}
                onClick={() =>
                  patchForm({
                    colorway: [
                      ...form.colorway,
                      form.colorway[form.colorway.length - 1] ?? '#636efa',
                    ],
                  })
                }
              >
                Add color
              </Button>
              {form.colorway.length === 0 && (env.colorway?.length ?? 0) > 0 && (
                <Text size="xs" c="dimmed">
                  Deployment default in use ({env.colorway!.length} colors).
                </Text>
              )}
            </Group>
          </Stack>
        </Stack>
      </Paper>

      <Group justify="space-between">
        <Button
          variant="subtle"
          color="red"
          disabled={!hasOverrides || saving}
          onClick={handleReset}
          leftSection={<Icon icon="mdi:restore" width={16} />}
        >
          Reset all to deployment defaults
        </Button>
        <Button
          onClick={handleSave}
          loading={saving}
          disabled={!colorwayValid}
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
