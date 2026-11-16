// Bundled copies of public/logos/multiqc_icon_{dark,white,color}.svg. A static bundle
// opens from file://, where the server-served `/dashboard/logos/...` path
// resolves to `file:///dashboard/logos/...` and fails: the dashboard title then
// renders the browser's broken-image glyph next to it. Importing the assets lets
// Vite inline them as data: URIs in the single-file build. Only the static
// runtime entry imports this module, so server builds keep the absolute path
// (react-core's `themedIconSrc` default) and the SVGs stay separately cacheable.
import { setMultiqcLogoSources } from 'depictio-react-core';

import multiqcIconDark from '../assets/multiqc_icon_dark.svg';
import multiqcIconWhite from '../assets/multiqc_icon_white.svg';
import multiqcIconColor from '../assets/multiqc_icon_color.svg';

/** Point every MultiQC logo at the inlined copies: tab icons and tab links
 *  (`themedIconSrc`), the MultiQC tile's corner mark, the search palette's
 *  row icon and the data-collection type icon (`multiqcLogoSrc`). */
export function installInlineMultiqcLogos(): void {
  setMultiqcLogoSources({
    dark: multiqcIconDark,
    white: multiqcIconWhite,
    color: multiqcIconColor,
  });
}
