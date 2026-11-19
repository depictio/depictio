/**
 * The App's stylesheet, scoped in the page onto the runtime's roots.
 *
 * A report that embeds the runtime carries ONE copy of its stylesheet,
 * unscoped, as inert text: the dashboard view of a combined file (its own
 * document, an iframe) takes it as written, exactly as the bundle does. The
 * report view cannot: the page is Quarto's, and Mantine's global rules
 * (`:root` tokens, `body`, element resets) would restyle it. So here, in the
 * report, the browser parses the text into a constructed stylesheet, every
 * selector is moved onto the runtime's roots (`scopeSelector`), and the
 * scoped rules are written into the page. Shipping a second, pre-scoped copy
 * would cost the file ~0.6 MB.
 */
import { scopeSelectorList } from 'depictio-static-core';

type GroupRule = CSSRule & { cssRules: CSSRuleList; deleteRule(i: number): void };

function isGroup(rule: CSSRule): rule is GroupRule {
  return 'cssRules' in rule && !(rule instanceof CSSStyleRule) && !isKeyframes(rule);
}

function isKeyframes(rule: CSSRule): boolean {
  return typeof CSSKeyframesRule !== 'undefined' && rule instanceof CSSKeyframesRule;
}

function fontFamily(rule: CSSRule): string {
  const style = (rule as CSSFontFaceRule).style;
  return (style?.getPropertyValue('font-family') ?? '').replace(/["']/g, '').trim().toLowerCase();
}

/** Scope every rule of `list` in place; drop the `@font-face`s of `drop`. */
function scopeRules(
  list: CSSRuleList,
  owner: { deleteRule(i: number): void },
  root: string,
  drop: Set<string>,
): void {
  for (let i = list.length - 1; i >= 0; i--) {
    const rule = list[i];
    if (rule instanceof CSSStyleRule) {
      const next = scopeSelectorList(rule.selectorText, root);
      if (next !== rule.selectorText) rule.selectorText = next;
    } else if (typeof CSSFontFaceRule !== 'undefined' && rule instanceof CSSFontFaceRule) {
      if (drop.size > 0 && drop.has(fontFamily(rule))) owner.deleteRule(i);
    } else if (isGroup(rule)) {
      scopeRules(rule.cssRules, rule, root, drop);
    }
  }
}

/** The stylesheet `css`, parsed and scoped onto `root`. */
export function scopedSheet(
  css: string,
  root: string,
  options: { dropFontFaces?: string[] } = {},
): CSSStyleSheet {
  const sheet = new CSSStyleSheet();
  sheet.replaceSync(css);
  const drop = new Set((options.dropFontFaces ?? []).map((f) => f.toLowerCase()));
  scopeRules(sheet.cssRules, sheet, root, drop);
  return sheet;
}

/**
 * Apply `css`, scoped onto `root`, to `doc`: a `<style>` at the end of its
 * body, written now, before the runtime mounts.
 *
 * Not an adopted sheet: adopted sheets cascade after every sheet of the
 * document, so the stylesheet's own `:root` tokens (moved onto the root) would
 * override the ones Mantine writes for the report's brand, which arrive later
 * in a `<style>` of the runtime's React tree. In document order those win.
 */
export function injectScopedStyles(
  doc: Document,
  css: string,
  root: string,
  options: { dropFontFaces?: string[] } = {},
): HTMLStyleElement {
  const sheet = scopedSheet(css, root, options);
  const style = doc.createElement('style');
  style.setAttribute('data-depictio-runtime', 'scoped-css');
  style.textContent = Array.from(sheet.cssRules)
    .map((r) => r.cssText)
    .join('\n');
  (doc.body ?? doc.head).appendChild(style);
  return style;
}
