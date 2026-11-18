import { brandCssVariablesResolver, buildDepictioTheme, setChromeStyle } from 'depictio-react-core';
import paper from 'depictio-chrome/variants/glass/glass';

/**
 * Tool Studio wears depictio's own look, not one of its own.
 *
 * - The theme is `buildDepictioTheme`, the one the viewer and the serverless
 *   bundles build (system font stack, `md` radius, Mantine's stock blue as the
 *   primary, depictio's logo palettes registered), with the active chrome
 *   style's overrides laid over it, exactly as `depictio/viewer/src/main.tsx`
 *   does. No brand theme: the Studio is an unbranded depictio surface.
 * - The chrome style is Paper (id `glass`), depictio's default and the one a
 *   static bundle forces (`static-runtime/chromeVariantShim.ts`). Setting it
 *   writes `data-chrome="glass"` on <html>, which is what every `--gl-*` token
 *   and every Paper rule (glass.css, the pages' and the builder's sheets) keys on.
 */
setChromeStyle(paper);

export const studioTheme = buildDepictioTheme({ chrome: paper.themeOverrides });

/** The surface tokens (`--depictio-*`) of an unbranded instance. */
export const studioCssVariablesResolver = brandCssVariablesResolver(null);

/**
 * The Studio's section tone.
 *
 * depictio gives a section its own hue where the section has an identity of its
 * own (Dashboards wear the logo's orange, Projects its teal: `useSectionPalettes`
 * in chrome/variants/glass/pages/GlassPage.tsx). The hue is carried by the
 * page's icon tile and by its primary controls; the theme underneath keeps the
 * instance primary. The Tools Catalog already has a hue in depictio: the
 * component builder's "Pick from catalog" path is `violet`
 * (builder/componentSource.ts), the family of the catalog's own
 * pinwheel-and-hammer mark. The Studio is where that catalog is written, so it
 * wears that hue (see `useStudioTone` in components/StudioShell.tsx).
 */
export const STUDIO_TONE = 'violet';
