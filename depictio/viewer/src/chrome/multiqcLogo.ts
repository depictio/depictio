// Bundled copies of public/logos/multiqc_icon_{dark,white}.svg. A static bundle
// opens from file://, where the server-served `/dashboard/logos/...` path
// resolves to `file:///dashboard/logos/...` and fails: the dashboard title then
// renders the browser's broken-image glyph next to it. Importing the assets lets
// Vite inline them as data: URIs in the single-file build, while server builds
// keep the absolute path so the SVGs stay separately cacheable. Same split as
// PoweredBy.tsx.
import multiqcIconDark from '../assets/multiqc_icon_dark.svg';
import multiqcIconWhite from '../assets/multiqc_icon_white.svg';

/** True for any MultiQC logo path a dashboard YAML or seed may carry — the
 *  legacy Dash PNG or one of the themed SVGs. */
export function isMultiqcIcon(path: string | null | undefined): boolean {
  if (!path) return false;
  return /\/assets\/images\/logos\/multiqc(\.png|_icon_(dark|white|color)\.svg)$/i.test(path);
}

/** Themed MultiQC logo URL. `inline` (static bundles) hands back the embedded
 *  copy; server builds get the SPA-served path. */
export function multiqcLogoSrc(variant: 'dark' | 'white', inline: boolean): string {
  if (variant === 'white') {
    return inline ? multiqcIconWhite : '/dashboard/logos/multiqc_icon_white.svg';
  }
  return inline ? multiqcIconDark : '/dashboard/logos/multiqc_icon_dark.svg';
}
