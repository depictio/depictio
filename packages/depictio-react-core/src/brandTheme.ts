import { createContext, useContext } from 'react';
import { createTheme, DEFAULT_THEME, type MantineColorsTuple, type MantineTheme } from '@mantine/core';
import { generateColors } from '@mantine/colors-generator';

/**
 * Brand theme (#397): the one client-side declaration of a deployment's (or a
 * dashboard's) visual identity, mirroring `depictio/models/models/branding.py`.
 *
 * The server resolves the layers (env defaults -> admin overrides -> dashboard
 * override) and materialises the derived figure colors before shipping this,
 * so nothing here re-derives a palette. `buildMantineTheme` only has to map an
 * already-decided theme onto Mantine's tokens.
 *
 * Reaching the ~1,100 literal `color="teal"` / `color="orange"` props scattered
 * across the app is what `tint_mode` is for — see `paletteOverrides` below.
 */

export type TintMode = 'accent' | 'full';
export type LogoMode = 'inherit' | 'none' | 'custom';

/** Chrome colors for one color scheme. Hex only — these become raw CSS values. */
export interface BrandSurfaces {
  app_bg?: string | null;
  section_bg?: string | null;
  nav_bg?: string | null;
  heading?: string | null;
}

/** Figure defaults. Component-explicit values always win over these. */
export interface BrandPlots {
  template?: string | null;
  colorway?: string[] | null;
  sequential?: string[] | null;
}

export interface BrandTheme {
  app_name?: string | null;
  logo_mode?: LogoMode | null;
  logo_url?: string | null;
  logo_url_dark?: string | null;

  primary?: string | null;
  secondary?: string | null;
  tertiary?: string | null;
  success?: string | null;
  warning?: string | null;
  danger?: string | null;

  tint_mode?: TintMode | null;

  surfaces_light?: BrandSurfaces | null;
  surfaces_dark?: BrandSurfaces | null;
  font_family?: string | null;
  headings_font_family?: string | null;
  default_radius?: string | null;

  plots?: BrandPlots | null;

  /** Derived Mantine tuples keyed by role, filled in by the server's
   *  `resolve_brand_theme`. Never authored by hand. */
  palettes?: Record<string, string[]> | null;
}

/** Palette names the generated brand tuples are registered under. */
export const BRAND_PALETTES = {
  primary: 'brandPrimary',
  secondary: 'brandSecondary',
  tertiary: 'brandTertiary',
} as const;

const HEX_RE = /^#[0-9a-fA-F]{6}$/;

export function isHexColor(value: string | null | undefined): value is string {
  return !!value && HEX_RE.test(value);
}

/** True when the value names a Mantine palette rather than giving a hex color. */
export function isMantinePaletteName(value: string | null | undefined): value is string {
  return !!value && !value.startsWith('#') && /^[a-z][a-z0-9-]*$/i.test(value);
}

/** True when the theme says nothing at all — an unbranded deployment. */
export function isEmptyBrandTheme(theme: BrandTheme | null | undefined): boolean {
  if (!theme) return true;
  // `palettes` is derived from the colors, so a theme holding only derived
  // tuples still states nothing.
  return Object.entries(theme).every(([key, value]) => value == null || key === 'palettes');
}

/** The logo to render for this theme, or `null` to fall back / show none. */
export function resolveBrandLogo(
  theme: BrandTheme | null | undefined,
  isDark: boolean,
): { src: string | null; mode: LogoMode } {
  const mode: LogoMode = theme?.logo_mode ?? (theme?.logo_url ? 'custom' : 'inherit');
  if (mode !== 'custom') return { src: null, mode };
  const src = (isDark && theme?.logo_url_dark) || theme?.logo_url || null;
  return { src, mode: src ? 'custom' : 'inherit' };
}

// ── Mantine mapping ───────────────────────────────────────────────────────────

/**
 * A hex or palette name resolved to a 10-shade tuple.
 *
 * A palette name is looked up in Mantine's own defaults rather than generated,
 * so `primary: "teal"` gives the exact teal the rest of the app already uses.
 */
/**
 * The Mantine tuple for one brand role.
 *
 * A resolved theme carries `palettes`, derived server-side so that the brand
 * colour lands on shade 6 — the shade Mantine actually paints a filled control
 * with. `generateColors` places the seed by its lightness instead, which for a
 * dark brand leaves every button a washed-out cousin of it, so it is only the
 * fallback for a theme that has not been through `resolve_brand_theme` (an
 * unsaved draft, mid-request).
 */
function tupleFor(
  theme: BrandTheme,
  role: BrandRole | 'success' | 'warning' | 'danger',
): MantineColorsTuple | null {
  const color = theme[role];
  if (!color) return null;
  const derived = theme.palettes?.[role];
  if (derived && derived.length === 10) return derived as unknown as MantineColorsTuple;
  if (isHexColor(color)) return generateColors(color);
  if (isMantinePaletteName(color)) {
    return (DEFAULT_THEME.colors as Record<string, MantineColorsTuple>)[color] ?? null;
  }
  return null;
}

/**
 * Which built-in Mantine palettes the brand hues take over.
 *
 * This is the lever that brands the existing UI without touching its ~1,100
 * literal color props. `blue` is Mantine's default primary and this codebase's
 * "neutral accent", so it always follows the brand. In `full` mode the two
 * other accent families the chrome reaches for (`teal`, `orange`) follow the
 * secondary and tertiary hues.
 *
 * `gray`, `dark`, `red`, `green` and `yellow` are never remapped: they carry
 * pass/fail/warning meaning that a brand hue would quietly destroy.
 */
function paletteOverrides(theme: BrandTheme): Record<string, MantineColorsTuple> {
  const colors: Record<string, MantineColorsTuple> = {};
  const primary = tupleFor(theme, 'primary');
  const secondary = tupleFor(theme, 'secondary');
  const tertiary = tupleFor(theme, 'tertiary');

  if (primary) {
    colors[BRAND_PALETTES.primary] = primary;
    colors.blue = primary;
  }
  if (secondary) colors[BRAND_PALETTES.secondary] = secondary;
  if (tertiary) colors[BRAND_PALETTES.tertiary] = tertiary;

  if (theme.tint_mode === 'full') {
    if (secondary) colors.teal = secondary;
    if (tertiary) colors.orange = tertiary;
  }

  // Semantic overrides are opt-in and independent of tint mode: an instance
  // that wants its own "danger" red says so explicitly.
  const success = tupleFor(theme, 'success');
  const warning = tupleFor(theme, 'warning');
  const danger = tupleFor(theme, 'danger');
  if (success) colors.green = success;
  if (warning) colors.yellow = warning;
  if (danger) colors.red = danger;

  return colors;
}

export interface DepictioThemeOptions {
  /** Resolved brand theme; omit for the stock (unbranded) Depictio look. */
  brand?: BrandTheme | null;
}

const DEFAULT_FONT_FAMILY =
  '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, sans-serif';

/**
 * The Depictio Mantine theme, branded when a theme is supplied.
 *
 * Component defaults live here rather than at call sites so a brand decision
 * ("headings use the brand heading color") is made once. Surfaces are emitted
 * as CSS variables instead — see `brandCssVariablesResolver`, which needs the
 * light/dark split that `createTheme` has no slot for.
 */
export function buildDepictioTheme(options: DepictioThemeOptions = {}) {
  const brand = options.brand ?? null;
  const colors = brand ? paletteOverrides(brand) : {};
  const hasPrimary = !!colors[BRAND_PALETTES.primary];

  return createTheme({
    fontFamily: brand?.font_family || DEFAULT_FONT_FAMILY,
    fontFamilyMonospace: 'Menlo, Monaco, Consolas, "Courier New", monospace',
    defaultRadius: (brand?.default_radius as 'xs' | 'sm' | 'md' | 'lg' | 'xl') || 'md',
    primaryColor: hasPrimary
      ? BRAND_PALETTES.primary
      : isMantinePaletteName(brand?.primary)
        ? (brand!.primary as string)
        : 'blue',
    ...(Object.keys(colors).length ? { colors } : {}),
    // The resolved brand rides along on the theme so anything holding a
    // `MantineTheme` can reach it — the Plotly renderers in particular, which
    // are handed a theme but no context, and which must follow a nested
    // provider when a dashboard overrides the instance branding.
    other: { brand },
    headings: {
      // The Virgil hand-drawn face stays opt-in per place (e.g. AuthCard's
      // "Welcome to Depictio"); this is the brand's heading stack, if any.
      fontFamily: brand?.headings_font_family || brand?.font_family || DEFAULT_FONT_FAMILY,
    },
    components: {
      Title: {
        styles: {
          // `--depictio-heading-color` is unset on an unbranded instance, so
          // the fallback keeps Mantine's default heading color.
          root: { color: 'var(--depictio-heading-color, var(--mantine-color-text))' },
        },
      },
    },
  });
}

/** Back-compat alias: the unbranded theme. */
export const depictioTheme = buildDepictioTheme();

// ── Surface CSS variables ─────────────────────────────────────────────────────

/**
 * Surface tokens, per color scheme.
 *
 * Mantine's theme object has one value per token, but a brand needs a light
 * and a dark answer for every surface, so these go through
 * `MantineProvider`'s `cssVariablesResolver` instead. Everything lands in the
 * `--depictio-*` namespace except the two Mantine already owns
 * (`--mantine-color-body`, `--mantine-color-default`), which are overridden in
 * place so untouched components follow along.
 */
export function brandCssVariablesResolver(brand: BrandTheme | null | undefined) {
  const scheme = (surfaces: BrandSurfaces | null | undefined): Record<string, string> => {
    const vars: Record<string, string> = {};
    if (!surfaces) return vars;
    if (surfaces.app_bg) vars['--mantine-color-body'] = surfaces.app_bg;
    if (surfaces.section_bg) {
      vars['--depictio-section-bg'] = surfaces.section_bg;
      vars['--mantine-color-default'] = surfaces.section_bg;
    }
    if (surfaces.nav_bg) vars['--depictio-nav-bg'] = surfaces.nav_bg;
    if (surfaces.heading) vars['--depictio-heading-color'] = surfaces.heading;
    return vars;
  };

  // The filled token rather than the raw hex: it is what a Button actually
  // paints, it resolves per scheme, and it works whether the role was given as
  // a hex or as a Mantine palette name. Roles the brand left unset fall back to
  // the literals the chrome used before there was a brand at all.
  const role = (name: BrandRole, fallback: string): string =>
    brand?.[name]
      ? `var(--mantine-color-${BRAND_PALETTES[name]}-filled)`
      : `var(--mantine-color-${fallback}-filled)`;

  return (_theme: MantineTheme) => ({
    // Scheme-independent brand hues, so plain CSS can reach the palette
    // without hardcoding a shade index per rule.
    variables: {
      '--depictio-brand-primary': 'var(--mantine-primary-color-filled)',
      '--depictio-brand-secondary': role('secondary', 'teal'),
      '--depictio-brand-tertiary': role('tertiary', 'orange'),
    },
    light: scheme(brand?.surfaces_light),
    dark: scheme(brand?.surfaces_dark),
  });
}

// ── Consuming the brand from components ───────────────────────────────────────

/**
 * The active instance brand theme. The host app owns the provider (the viewer
 * fills it from `/utils/public-config`); this lives here so shared components
 * can read it too.
 */
export const BrandingContext = createContext<BrandTheme | null>(null);

export function useBranding(): BrandTheme | null {
  return useContext(BrandingContext);
}

export type BrandRole = 'primary' | 'secondary' | 'tertiary';

/**
 * The Mantine color name for a chrome accent role.
 *
 * App chrome has always named its accents literally (`color="teal"` for Edit,
 * `orange` for the parent tab pill…). Those keep working — `tint_mode: 'full'`
 * remaps the whole `teal`/`orange` families — but in the default `accent` mode
 * only the primary follows the brand. Chrome that matters visually asks for
 * the *role* instead and gets the brand palette whenever the instance defined
 * one, in either mode, falling back to the historical literal otherwise.
 */
export function brandAccent(
  brand: BrandTheme | null | undefined,
  role: BrandRole,
  fallback: string,
): string {
  return brand?.[role] ? BRAND_PALETTES[role] : fallback;
}

/** `brandAccent` bound to the active branding context. */
export function useBrandAccent(role: BrandRole, fallback: string): string {
  return brandAccent(useBranding(), role, fallback);
}

/**
 * All three brand roles at once, each falling back to the literal the
 * unbranded app has always drawn that role in.
 *
 * For chrome that has to be right in `accent` tint mode too. `full` mode
 * remaps `blue`/`teal`/`orange` wholesale, which catches the long tail of
 * color literals — but an instance on `accent` only remaps `blue`, so
 * anything a user reads as "this app's identity" has to name its role
 * explicitly instead of naming a hue.
 */
export function useBrandAccents(): Record<BrandRole, string> {
  const brand = useBranding();
  return {
    primary: brandAccent(brand, 'primary', 'blue'),
    secondary: brandAccent(brand, 'secondary', 'teal'),
    tertiary: brandAccent(brand, 'tertiary', 'orange'),
  };
}

// ── Layering one theme over another ───────────────────────────────────────────

const NESTED_KEYS = ['surfaces_light', 'surfaces_dark', 'plots'] as const;

/**
 * Lay `over` on top of `under`, field by field.
 *
 * Mirrors `merge_brand_themes` in `depictio/models/models/branding.py`: a
 * stated value wins, `null`/`undefined` means "inherit", and the nested blocks
 * merge per field rather than wholesale — a dashboard that names only a
 * `section_bg` keeps the instance's `nav_bg`.
 */
export function mergeBrandThemes(
  under: BrandTheme | null | undefined,
  over: BrandTheme | null | undefined,
): BrandTheme {
  const base: Record<string, unknown> = { ...(under ?? {}) };
  const palettes = { ...((base.palettes ?? {}) as Record<string, string[]>) };
  for (const [key, value] of Object.entries(over ?? {})) {
    if (value == null) continue;
    if ((NESTED_KEYS as readonly string[]).includes(key)) {
      // Only the sub-fields the overlay actually states, mirroring the
      // `exclude_none` in `_merge_pair`. `GET /dashboards/get` dumps the model
      // without `exclude_none`, so a dashboard that set one surface arrives
      // with explicit `null`s for its siblings — spreading those wholesale
      // would erase the instance's values for fields the dashboard never
      // touched.
      const stated = Object.fromEntries(
        Object.entries(value as Record<string, unknown>).filter(([, v]) => v != null),
      );
      base[key] = { ...((base[key] ?? {}) as object), ...stated };
      continue;
    }
    // A role the overlay restates invalidates the tuple derived for the one
    // underneath: better a `generateColors` approximation for the moment it
    // takes the server to resolve than confidently painting the wrong brand.
    if (key in palettes) delete palettes[key];
    base[key] = value;
  }
  base.palettes = Object.keys(palettes).length ? palettes : null;
  return base as BrandTheme;
}
