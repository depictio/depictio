/**
 * Scope a stylesheet to the roots of a runtime hosted by someone else's page.
 *
 * The report runtime (`vite.report.config.ts`) lands in a Quarto report: the
 * page, its Bootstrap theme, its fonts and its layout belong to Quarto, and the
 * runtime must draw its tiles without restyling any of it. Mantine's and the
 * app's stylesheets were written for a page the app owns, so their few global
 * rules (`:root` tokens, `body` type and colour, element resets) are moved onto
 * the runtime's own roots here, at build time:
 *
 *   - `:root…`, `html…`, `body…` at the head of a selector become the root
 *     class (`:root[data-chrome='glass'] .x` → `.root[data-chrome='glass'] .x`);
 *   - a selector that starts on an element or `*` gets the root class in front
 *     (`*, *::before` → `.root *, .root *::before`; `a` → `.root a`);
 *   - everything that starts on a class, an id, an attribute or a pseudo-class
 *     (`.mantine-Button-root`, `[data-mantine-color-scheme]`, `:where(…)`) is
 *     left alone: it only ever matches the runtime's own markup.
 *
 * Rules inside `@keyframes` are left alone (their selectors are percentages).
 *
 * `dropFontFaces` removes `@font-face` blocks by family: faces the host already
 * provides (or that only the app's own pages use) need not ride along twice.
 */
import type { Plugin as PostcssPlugin, Rule } from 'postcss';

import { scopeSelector } from '../../../packages/depictio-static-core/src/combined';

// One implementation for the build (the report runtime) and the page (the
// combined runtime scopes the App's stylesheet in the report it is hosted by).
export { scopeSelector } from '../../../packages/depictio-static-core/src/combined';

function insideKeyframes(rule: Rule): boolean {
  let node = rule.parent;
  while (node) {
    if (node.type === 'atrule' && /keyframes$/i.test((node as { name: string }).name)) return true;
    node = node.parent as typeof node;
  }
  return false;
}

export function scopeCss(
  rootSelector: string,
  options: { dropFontFaces?: string[] } = {},
): PostcssPlugin {
  const drop = new Set((options.dropFontFaces ?? []).map((f) => f.toLowerCase()));
  return {
    postcssPlugin: 'depictio-scope-css',
    AtRule: {
      'font-face'(atRule) {
        if (drop.size === 0) return;
        let family = '';
        atRule.walkDecls('font-family', (decl) => {
          family = decl.value.replace(/["']/g, '').trim().toLowerCase();
        });
        if (drop.has(family)) atRule.remove();
      },
    },
    Rule(rule) {
      if (insideKeyframes(rule)) return;
      const next = rule.selectors.map((sel) => scopeSelector(sel, rootSelector));
      // De-duplicated: `html, body` would otherwise become the root twice.
      const unique = Array.from(new Set(next));
      if (unique.join(',') !== rule.selectors.join(',')) rule.selectors = unique;
    },
  };
}
