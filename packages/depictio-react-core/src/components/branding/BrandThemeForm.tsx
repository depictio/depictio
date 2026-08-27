import React from 'react';
import {
  ActionIcon,
  ColorInput,
  Divider,
  Grid,
  Group,
  SegmentedControl,
  Select,
  Stack,
  Text,
  TextInput,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import type { BrandPlots, BrandSurfaces, BrandTheme } from '../../brandTheme';

/**
 * The brand theme editor (#397), shared by the /admin Branding panel and the
 * per-dashboard appearance panel.
 *
 * Both levels edit the *same* model, so they get the same controls; `scope`
 * only decides which sections make sense where (an instance names itself, a
 * dashboard doesn't). `defaults` supplies the placeholders — the deployment's
 * env vars at instance level, the resolved instance theme at dashboard level —
 * so an empty field visibly means "inherit that" rather than "unset".
 *
 * Every change emits the whole theme. Clearing a field emits `null` for it,
 * which is what makes it inherit again.
 */

const HEX_RE = /^#[0-9a-fA-F]{6}$/;

/** Plotly templates offered to authors. One list, not four. */
export const PLOT_TEMPLATE_OPTIONS = [
  { value: '', label: 'Follow the UI theme' },
  { value: 'plotly', label: 'Plotly' },
  { value: 'plotly_white', label: 'Plotly white' },
  { value: 'plotly_dark', label: 'Plotly dark' },
  { value: 'ggplot2', label: 'ggplot2' },
  { value: 'seaborn', label: 'Seaborn' },
  { value: 'simple_white', label: 'Simple white' },
  { value: 'presentation', label: 'Presentation' },
];

const RADIUS_OPTIONS = [
  { value: 'xs', label: 'Sharp (xs)' },
  { value: 'sm', label: 'Small' },
  { value: 'md', label: 'Medium' },
  { value: 'lg', label: 'Large' },
  { value: 'xl', label: 'Round (xl)' },
];

/**
 * Renders the two stacks as they will actually paint.
 *
 * A font stack is a request, not a guarantee: nothing is downloaded, so a name
 * the viewer's machine doesn't have falls silently through to the next entry.
 * Showing the result beside the input is the only way to tell "Inter applied"
 * from "Inter was ignored and you are looking at the fallback".
 */
const FontSample: React.FC<{ body?: string | null; heading?: string | null }> = ({
  body,
  heading,
}) => (
  <Stack gap={2}>
    <Text size="xs" c="dimmed">
      Preview
    </Text>
    <Text style={{ fontFamily: heading || body || undefined }} fw={700} size="lg">
      Heading — Aa Bb Gg 0123
    </Text>
    <Text style={{ fontFamily: body || undefined }} size="sm">
      Body text — the quick brown fox jumps over the lazy dog.
    </Text>
  </Stack>
);

export type BrandFormScope = 'instance' | 'dashboard';

export interface BrandThemeFormProps {
  value: BrandTheme;
  /** Placeholder layer: what an empty field will inherit. */
  defaults?: BrandTheme | null;
  onChange: (next: BrandTheme) => void;
  scope?: BrandFormScope;
  /** Rendered inside the Identity section (the logo upload lives in the host,
   *  which owns the endpoint). */
  logoSlot?: React.ReactNode;
}

/** Drop empty strings/arrays back to `null` so "cleared" means "inherit". */
function clean<T>(value: T | '' | undefined): T | null {
  if (value === '' || value === undefined) return null;
  return value as T;
}

const ColorField: React.FC<{
  label: string;
  description?: string;
  value: string | null | undefined;
  placeholder?: string | null;
  onChange: (value: string | null) => void;
  testId?: string;
}> = ({ label, description, value, placeholder, onChange, testId }) => (
  <ColorInput
    size="xs"
    format="hex"
    label={label}
    description={description}
    placeholder={placeholder ?? 'Inherit'}
    value={value ?? ''}
    onChange={(next) => onChange(clean(next))}
    data-testid={testId}
  />
);

const SurfaceFields: React.FC<{
  value: BrandSurfaces | null | undefined;
  onChange: (next: BrandSurfaces | null) => void;
}> = ({ value, onChange }) => {
  const patch = (next: Partial<BrandSurfaces>) => {
    const merged = { ...(value ?? {}), ...next };
    const any = Object.values(merged).some((v) => v != null);
    onChange(any ? merged : null);
  };
  return (
    <Grid gutter="xs">
      <Grid.Col span={6}>
        <ColorField
          label="Page background"
          value={value?.app_bg}
          onChange={(v) => patch({ app_bg: v })}
        />
      </Grid.Col>
      <Grid.Col span={6}>
        <ColorField
          label="Cards & sections"
          value={value?.section_bg}
          onChange={(v) => patch({ section_bg: v })}
        />
      </Grid.Col>
      <Grid.Col span={6}>
        <ColorField
          label="Header & sidebar"
          value={value?.nav_bg}
          onChange={(v) => patch({ nav_bg: v })}
        />
      </Grid.Col>
      <Grid.Col span={6}>
        <ColorField
          label="Titles"
          value={value?.heading}
          onChange={(v) => patch({ heading: v })}
        />
      </Grid.Col>
    </Grid>
  );
};

const ColorwayEditor: React.FC<{
  value: string[] | null | undefined;
  derived: string[] | null | undefined;
  onChange: (next: string[] | null) => void;
}> = ({ value, derived, onChange }) => {
  const colors = value ?? [];
  const isDerived = colors.length === 0;

  return (
    <Stack gap={6}>
      <Group justify="space-between" align="center">
        <Text size="xs" fw={500}>
          Figure colorway
        </Text>
        <SegmentedControl
          size="xs"
          value={isDerived ? 'auto' : 'custom'}
          onChange={(mode) =>
            onChange(mode === 'auto' ? null : [...(derived ?? []), ...(colors.length ? colors : [])])
          }
          data={[
            { value: 'auto', label: 'From palette' },
            { value: 'custom', label: 'Custom' },
          ]}
          data-testid="colorway-mode"
        />
      </Group>
      {isDerived ? (
        <Text size="xs" c="dimmed">
          Derived from the brand colors above, so figures follow the palette without a
          second list to keep in step.
        </Text>
      ) : (
        <Stack gap={4}>
          {colors.map((color, idx) => (
            // eslint-disable-next-line react/no-array-index-key
            <Group key={idx} gap="xs" wrap="nowrap">
              <ColorInput
                size="xs"
                format="hex"
                value={color}
                error={!HEX_RE.test(color)}
                onChange={(next) =>
                  onChange(colors.map((c, i) => (i === idx ? next : c)))
                }
                style={{ flex: 1 }}
              />
              <Tooltip label="Remove color" withArrow>
                <ActionIcon
                  variant="subtle"
                  color="red"
                  size="sm"
                  aria-label="Remove color"
                  onClick={() => {
                    const next = colors.filter((_, i) => i !== idx);
                    onChange(next.length ? next : null);
                  }}
                >
                  <Icon icon="mdi:close" width={14} />
                </ActionIcon>
              </Tooltip>
            </Group>
          ))}
          <Group gap="xs">
            <ActionIcon
              variant="default"
              size="sm"
              aria-label="Add color"
              onClick={() => onChange([...colors, colors[colors.length - 1] ?? '#636efa'])}
            >
              <Icon icon="mdi:plus" width={14} />
            </ActionIcon>
            <Text size="xs" c="dimmed">
              {colors.length} color{colors.length === 1 ? '' : 's'}
            </Text>
          </Group>
        </Stack>
      )}
    </Stack>
  );
};

const BrandThemeForm: React.FC<BrandThemeFormProps> = ({
  value,
  defaults,
  onChange,
  scope = 'instance',
  logoSlot,
}) => {
  const patch = (next: Partial<BrandTheme>) => onChange({ ...value, ...next });
  const tintMode = value.tint_mode ?? defaults?.tint_mode ?? 'accent';
  // Same inherit-then-default chain as the inputs' placeholders, so the sample
  // shows what this scope will actually paint rather than only what it states.
  const bodyFont = value.font_family ?? defaults?.font_family ?? null;
  const headingFont = value.headings_font_family ?? defaults?.headings_font_family ?? null;
  const patchPlots = (next: Partial<BrandPlots>) => {
    const merged = { ...(value.plots ?? {}), ...next };
    const any = Object.values(merged).some((v) => v != null);
    patch({ plots: any ? merged : null });
  };
  const inherit = (color: string | null | undefined) => color ?? undefined;

  return (
    <Stack gap="md">
      {scope === 'instance' && (
        <Stack gap="xs">
          <Text fw={600} size="sm">
            Identity
          </Text>
          <TextInput
            size="xs"
            label="Instance name"
            description="Browser tab title and login-page greeting."
            placeholder={defaults?.app_name ?? 'Depictio'}
            value={value.app_name ?? ''}
            onChange={(e) => patch({ app_name: clean(e.currentTarget.value.trim()) })}
            data-testid="branding-app-name"
          />
          {logoSlot}
        </Stack>
      )}
      {scope === 'dashboard' && logoSlot}

      <Divider />

      <Stack gap="xs">
        <Text fw={600} size="sm">
          Brand colors
        </Text>
        <Grid gutter="xs">
          <Grid.Col span={4}>
            <ColorField
              label="Primary"
              value={value.primary}
              placeholder={inherit(defaults?.primary)}
              onChange={(v) => patch({ primary: v })}
              testId="branding-primary-color"
            />
          </Grid.Col>
          <Grid.Col span={4}>
            <ColorField
              label="Secondary"
              value={value.secondary}
              placeholder={inherit(defaults?.secondary)}
              onChange={(v) => patch({ secondary: v })}
              testId="branding-secondary-color"
            />
          </Grid.Col>
          <Grid.Col span={4}>
            <ColorField
              label="Tertiary"
              value={value.tertiary}
              placeholder={inherit(defaults?.tertiary)}
              onChange={(v) => patch({ tertiary: v })}
              testId="branding-tertiary-color"
            />
          </Grid.Col>
        </Grid>
        <Stack gap={4}>
          <Text size="xs" fw={500}>
            Reach
          </Text>
          <SegmentedControl
            size="xs"
            // A dashboard that hasn't stated a reach follows the instance's,
            // so showing the field default here would claim the wrong one.
            value={tintMode}
            onChange={(mode) => patch({ tint_mode: mode as 'accent' | 'full' })}
            data={[
              { value: 'accent', label: 'Primary accent' },
              { value: 'full', label: 'Full palette' },
            ]}
            data-testid="branding-tint-mode"
          />
          <Text size="xs" c="dimmed">
            {tintMode === 'full'
              ? 'Buttons, tabs, badges and section accents across the app follow all three brand colors.'
              : 'Only the primary accent is re-tinted; the app keeps its existing secondary accents.'}
          </Text>
        </Stack>
      </Stack>

      <Divider />

      <Stack gap="xs">
        <Text fw={600} size="sm">
          Status colors
        </Text>
        <Text size="xs" c="dimmed">
          Left alone by the brand reach above, because pass / warn / fail have to stay
          readable as meaning rather than as decoration.
        </Text>
        <Grid gutter="xs">
          <Grid.Col span={4}>
            <ColorField
              label="Success"
              value={value.success}
              placeholder={inherit(defaults?.success)}
              onChange={(v) => patch({ success: v })}
            />
          </Grid.Col>
          <Grid.Col span={4}>
            <ColorField
              label="Warning"
              value={value.warning}
              placeholder={inherit(defaults?.warning)}
              onChange={(v) => patch({ warning: v })}
            />
          </Grid.Col>
          <Grid.Col span={4}>
            <ColorField
              label="Danger"
              value={value.danger}
              placeholder={inherit(defaults?.danger)}
              onChange={(v) => patch({ danger: v })}
            />
          </Grid.Col>
        </Grid>
      </Stack>

      <Divider />

      <Stack gap="xs">
        <Text fw={600} size="sm">
          Surfaces
        </Text>
        <Text size="xs" c="dimmed">
          Backgrounds and title color, per color scheme. Leave empty to keep Mantine&apos;s.
        </Text>
        <Stack gap={4}>
          <Text size="xs" fw={500}>
            Light
          </Text>
          <SurfaceFields
            value={value.surfaces_light}
            onChange={(next) => patch({ surfaces_light: next })}
          />
        </Stack>
        <Stack gap={4}>
          <Text size="xs" fw={500}>
            Dark
          </Text>
          <SurfaceFields
            value={value.surfaces_dark}
            onChange={(next) => patch({ surfaces_dark: next })}
          />
        </Stack>
      </Stack>

      <Divider />

      <Stack gap="xs">
        <Text fw={600} size="sm">
          Typography & shape
        </Text>
        <TextInput
          size="xs"
          label="Font stack"
          description="CSS font-family list, e.g. Inter, system-ui, sans-serif. Nothing is downloaded — name a font your viewers already have, and always end the list with a generic family."
          placeholder={defaults?.font_family ?? 'System sans'}
          value={value.font_family ?? ''}
          onChange={(e) => patch({ font_family: clean(e.currentTarget.value.trim()) })}
        />
        <TextInput
          size="xs"
          label="Heading font stack"
          description="Falls back to the font stack above."
          placeholder={defaults?.headings_font_family ?? 'Same as body'}
          value={value.headings_font_family ?? ''}
          onChange={(e) =>
            patch({ headings_font_family: clean(e.currentTarget.value.trim()) })
          }
        />
        <FontSample body={bodyFont} heading={headingFont} />
        <Select
          size="xs"
          label="Corner radius"
          description="Applies wherever a component doesn't set its own corner radius."
          placeholder={defaults?.default_radius ?? 'Medium'}
          data={RADIUS_OPTIONS}
          value={value.default_radius ?? null}
          clearable
          onChange={(v) => patch({ default_radius: clean(v ?? '') })}
        />
      </Stack>

      <Divider />

      <Stack gap="xs">
        <Text fw={600} size="sm">
          Figures
        </Text>
        <Select
          size="xs"
          label="Plot template"
          description="Applied to figures whose component doesn't pick one."
          data={PLOT_TEMPLATE_OPTIONS}
          value={value.plots?.template ?? ''}
          onChange={(v) => patchPlots({ template: clean(v ?? '') })}
          data-testid="branding-plot-template"
        />
        <ColorwayEditor
          value={value.plots?.colorway}
          derived={defaults?.plots?.colorway}
          onChange={(next) => patchPlots({ colorway: next })}
        />
      </Stack>
    </Stack>
  );
};

export default BrandThemeForm;
