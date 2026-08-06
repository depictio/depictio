// Bundled copies of public/logos/multiqc_icon_{dark,white}.svg. A static bundle
// opens from file://, where the server-served `/dashboard/logos/...` path
// resolves to `file:///dashboard/logos/...` and fails: the dashboard title then
// renders the browser's broken-image glyph next to it. Importing the assets lets
// Vite inline them as data: URIs in the single-file build. Only the static
// runtime entry imports this module, so server builds keep the absolute path
// (react-core's `themedIconSrc` default) and the SVGs stay separately cacheable.
import { setMultiqcLogoSources } from 'depictio-react-core';

import multiqcIconDark from '../assets/multiqc_icon_dark.svg';
import multiqcIconWhite from '../assets/multiqc_icon_white.svg';

/** Point every MultiQC logo `themedIconSrc` resolves at the inlined copies. */
export function installInlineMultiqcLogos(): void {
  setMultiqcLogoSources({ dark: multiqcIconDark, white: multiqcIconWhite });
}
