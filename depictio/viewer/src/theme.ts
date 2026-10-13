/**
 * Depictio Mantine theme.
 *
 * The implementation lives in `depictio-react-core/brandTheme` so every entry
 * point that mounts its own `MantineProvider` — the main SPA, the standalone
 * catalog-preview bundle, the dev harnesses — builds the same theme from the
 * same brand definition. This module is a thin re-export kept in place so the
 * existing `from './theme'` imports keep working.
 */

export {
  brandCssVariablesResolver,
  buildDepictioTheme,
  depictioTheme,
} from 'depictio-react-core';
export type { BrandTheme, DepictioThemeOptions } from 'depictio-react-core';
