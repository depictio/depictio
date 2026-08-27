import React from 'react';
import {
  Alert,
  Badge,
  Button,
  Card,
  Group,
  MantineProvider,
  SegmentedControl,
  Stack,
  Tabs,
  Text,
  Title,
} from '@mantine/core';

import {
  brandCssVariablesResolver,
  buildDepictioTheme,
  BRAND_PALETTES,
  type BrandTheme,
} from '../../brandTheme';

/**
 * Live preview of a brand theme (#397).
 *
 * The point of a branding panel is seeing the result before committing to it,
 * so this renders real Mantine components under a *nested* MantineProvider fed
 * by the draft theme. Two things make that scoped rather than global:
 *
 * - `cssVariablesSelector` puts the generated variables on the wrapper class
 *   instead of `:root`, so the draft can't leak into the surrounding page;
 * - `getRootElement` returns undefined so the provider never writes attributes
 *   onto `<html>`.
 *
 * `theme` must already be *resolved* (derived colorway and sequential filled
 * in). Derivation is server-side on purpose — see `resolveBrandTheme` in
 * `api.ts` — so callers debounce a request rather than re-deriving here.
 */

const PREVIEW_CLASS = 'depictio-brand-preview';

/** Bar heights for the sample chart. Fixed, so the eye compares colors only. */
const SAMPLE_BARS = [0.95, 0.62, 0.78, 0.41, 0.86, 0.55, 0.7, 0.33];

export interface BrandThemePreviewProps {
  /** Resolved theme to preview. */
  theme: BrandTheme | null;
  /** Which color scheme to render. Defaults to a user-switchable control. */
  scheme?: 'light' | 'dark';
  /** Hide the light/dark switcher (when the caller drives `scheme`). */
  hideSchemeControl?: boolean;
  /** Drop the chart block — useful in the narrow dashboard settings drawer. */
  compact?: boolean;
}

function Swatches({ colors, label }: { colors: string[]; label: string }) {
  if (!colors.length) return null;
  return (
    <Stack gap={4}>
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      <Group gap={0} wrap="nowrap" style={{ borderRadius: 4, overflow: 'hidden' }}>
        {colors.map((color, idx) => (
          <div
            // eslint-disable-next-line react/no-array-index-key
            key={`${color}-${idx}`}
            title={color}
            style={{ background: color, height: 18, flex: 1, minWidth: 8 }}
          />
        ))}
      </Group>
    </Stack>
  );
}

function SampleChart({ colors }: { colors: string[] }) {
  const palette = colors.length ? colors : ['var(--mantine-primary-color-filled)'];
  return (
    <svg viewBox="0 0 160 48" role="img" aria-label="Sample chart" style={{ width: '100%' }}>
      {SAMPLE_BARS.map((height, idx) => (
        <rect
          // eslint-disable-next-line react/no-array-index-key
          key={idx}
          x={idx * 20 + 2}
          y={48 - height * 44}
          width={16}
          height={height * 44}
          rx={2}
          fill={palette[idx % palette.length]}
        />
      ))}
    </svg>
  );
}

const BrandThemePreview: React.FC<BrandThemePreviewProps> = ({
  theme,
  scheme,
  hideSchemeControl = false,
  compact = false,
}) => {
  const [ownScheme, setOwnScheme] = React.useState<'light' | 'dark'>('light');
  const activeScheme = scheme ?? ownScheme;

  const mantineTheme = React.useMemo(() => buildDepictioTheme({ brand: theme }), [theme]);
  const cssVariablesResolver = React.useMemo(() => brandCssVariablesResolver(theme), [theme]);

  const colorway = theme?.plots?.colorway ?? [];
  const sequential = theme?.plots?.sequential ?? [];
  const hasSecondary = !!theme?.secondary;
  const hasTertiary = !!theme?.tertiary;

  return (
    <Stack gap="xs" data-testid="brand-theme-preview">
      {!hideSchemeControl && (
        <SegmentedControl
          size="xs"
          value={activeScheme}
          onChange={(value) => setOwnScheme(value as 'light' | 'dark')}
          data={[
            { value: 'light', label: 'Light' },
            { value: 'dark', label: 'Dark' },
          ]}
          data-testid="brand-preview-scheme"
        />
      )}

      <MantineProvider
        theme={mantineTheme}
        cssVariablesResolver={cssVariablesResolver}
        cssVariablesSelector={`.${PREVIEW_CLASS}`}
        getRootElement={() => undefined}
      >
        {
          /* Mantine emits its per-scheme block as
             `.selector[data-mantine-color-scheme="dark"]` — one compound
             selector, not a descendant one — so the attribute has to sit on
             the scoped element ITSELF. On an ancestor those rules never match,
             and every variable defined only there (the whole brand palette
             included) silently falls back to the outer theme. */
          <div
            className={PREVIEW_CLASS}
            data-mantine-color-scheme={activeScheme}
            style={{
              background: 'var(--mantine-color-body)',
              color: 'var(--mantine-color-text)',
              border: '1px solid var(--mantine-color-default-border)',
              borderRadius: 'var(--mantine-radius-md)',
              overflow: 'hidden',
            }}
          >
            {/* Nav bar — the surface that reads as "this instance" first. */}
            <Group
              justify="space-between"
              px="sm"
              py={6}
              style={{
                background: 'var(--depictio-nav-bg, var(--mantine-color-default))',
                borderBottom: '1px solid var(--mantine-color-default-border)',
              }}
            >
              <Text size="sm" fw={600}>
                {theme?.app_name || 'Depictio'}
              </Text>
              <Group gap={6}>
                <Badge size="xs" variant="light">
                  Live
                </Badge>
                <Badge size="xs" color={hasTertiary ? BRAND_PALETTES.tertiary : 'orange'}>
                  Beta
                </Badge>
              </Group>
            </Group>

            <Stack gap="sm" p="sm">
              <Stack gap={2}>
                <Title order={5}>Section heading</Title>
                <Text size="xs" c="dimmed">
                  Body copy, links and captions keep their neutral tone.
                </Text>
              </Stack>

              <Group gap={6}>
                <Button size="compact-xs">Primary</Button>
                <Button size="compact-xs" variant="light">
                  Light
                </Button>
                <Button size="compact-xs" variant="outline">
                  Outline
                </Button>
                <Button size="compact-xs" variant="subtle">
                  Subtle
                </Button>
                <Button size="compact-xs" variant="default">
                  Default
                </Button>
              </Group>

              {(hasSecondary || hasTertiary) && (
                <Group gap={6}>
                  {hasSecondary && (
                    <Button size="compact-xs" color={BRAND_PALETTES.secondary}>
                      Secondary
                    </Button>
                  )}
                  {hasTertiary && (
                    <Button size="compact-xs" color={BRAND_PALETTES.tertiary}>
                      Tertiary
                    </Button>
                  )}
                </Group>
              )}

              {/* A dashboard's tabs are colored per tab, cycling the three
                  roles — so the sample names the roles rather than inventing
                  feature names, which read as real sections and only raise the
                  question of what distinguishes them. */}
              <Stack gap={4}>
                <Text size="xs" c="dimmed">
                  Dashboard tabs
                </Text>
                <Tabs variant="pills" defaultValue="primary">
                  <Tabs.List>
                    <Tabs.Tab value="primary">Primary</Tabs.Tab>
                    <Tabs.Tab
                      value="secondary"
                      color={hasSecondary ? BRAND_PALETTES.secondary : 'teal'}
                    >
                      Secondary
                    </Tabs.Tab>
                    <Tabs.Tab
                      value="tertiary"
                      color={hasTertiary ? BRAND_PALETTES.tertiary : 'orange'}
                    >
                      Tertiary
                    </Tabs.Tab>
                  </Tabs.List>
                </Tabs>
              </Stack>

              <Card
                withBorder
                padding="xs"
                radius="md"
                style={{ background: 'var(--depictio-section-bg, var(--mantine-color-body))' }}
              >
                <Stack gap={6}>
                  <Text size="xs" fw={600}>
                    Card / section surface
                  </Text>
                  {!compact && <SampleChart colors={colorway} />}
                  <Swatches colors={colorway} label="Figure colorway" />
                  <Swatches colors={sequential} label="Continuous scale" />
                </Stack>
              </Card>

              <Alert variant="light" color="red" p="xs" title="Errors stay red">
                <Text size="xs">Pass / warn / fail keep their meaning.</Text>
              </Alert>
            </Stack>
          </div>
        }
      </MantineProvider>
    </Stack>
  );
};

export default BrandThemePreview;
