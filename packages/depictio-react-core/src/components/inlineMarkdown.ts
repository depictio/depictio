/**
 * Inline-markdown tokenizer for the `text` component's body.
 *
 * Handles the four formats dashboard authors reach for in section prose:
 *   `**bold**`            -> bold
 *   `*italic*`            -> italic
 *   \`code\`              -> code
 *   `[label](https://…)`  -> link
 *   `[label](tab:Name)`   -> link to the sibling tab called Name (see tabLinks.ts)
 *   `![](icon:mdi:dna)`   -> an Iconify icon, inline (image syntax, icon scheme)
 *
 * We deliberately do NOT pull in react-markdown / remark / rehype — the body
 * is a single paragraph, and a regex pass is ~40 lines vs ~30 KB of deps.
 * Anything more complex (lists, images, tables) should use a proper component.
 *
 * Tokenizing here rather than in the renderer keeps this testable under the
 * node-only vitest setup: no DOM, no React.
 */

export type InlineToken =
  | { type: 'text'; value: string }
  | { type: 'bold'; value: string }
  | { type: 'italic'; value: string }
  | { type: 'code'; value: string }
  | { type: 'link'; value: string; href: string; external: boolean }
  | { type: 'icon'; name: string };

// The href half is a scheme allowlist, not a catch-all: dashboard bodies are
// authored content, and a permissive matcher would accept `javascript:`. Only
// absolute http(s) URLs, site-relative paths, `tab:` names and `params:`
// (the run's parameters, optionally searched: `params:dada2`) become anchors;
// anything else stays literal text, visibly wrong rather than silently
// dangerous. A tab name may hold spaces and one level of parentheses
// ("Environment (CTD)"), since that is how tabs get named.
const TAB_TARGET = String.raw`tab:(?:[^()\n]|\([^()\n]*\))+`;
const PARAMS_TARGET = String.raw`params:[A-Za-z0-9_.-]*`;
const LINK_HREF = String.raw`(?:https?:\/\/[^)\s]+|\/[^)\s]*|${TAB_TARGET}|${PARAMS_TARGET})`;
// An Iconify id: `prefix:name`, lower-case letters, digits and dashes only.
const ICON_NAME = String.raw`[a-z0-9-]+:[a-z0-9-]+`;
const ICON = new RegExp(String.raw`^!\[[^\]\n]*\]\(icon:(${ICON_NAME})\)$`);
const PATTERN = new RegExp(
  [
    String.raw`!\[[^\]\n]*\]\(icon:${ICON_NAME}\)`, // ![](icon:mdi:dna)
    '`[^`\\n]+`', // `code`
    '\\*\\*[^*\\n]+\\*\\*', // **bold**
    '\\*[^*\\n]+\\*', // *italic*
    `\\[[^\\]\\n]+\\]\\(${LINK_HREF}\\)`, // [label](href)
  ].join('|'),
  'g',
);

const LINK_PARTS = new RegExp(String.raw`^\[([^\]\n]+)\]\((${LINK_HREF})\)$`);

export const parseInlineMarkdown = (input: string): InlineToken[] => {
  // Wrapping the alternation in one capture group makes split() interleave the
  // delimiters with the plain text around them; the inner groups above are all
  // non-capturing so the chunks stay in lockstep.
  const parts = input.split(new RegExp(`(${PATTERN.source})`, 'g'));
  const tokens: InlineToken[] = [];
  for (const part of parts) {
    if (!part) continue;
    if (part.startsWith('**') && part.endsWith('**') && part.length >= 4) {
      tokens.push({ type: 'bold', value: part.slice(2, -2) });
      continue;
    }
    if (part.startsWith('*') && part.endsWith('*') && part.length >= 3) {
      tokens.push({ type: 'italic', value: part.slice(1, -1) });
      continue;
    }
    if (part.startsWith('`') && part.endsWith('`') && part.length >= 3) {
      tokens.push({ type: 'code', value: part.slice(1, -1) });
      continue;
    }
    const icon = part.startsWith('![') ? ICON.exec(part) : null;
    if (icon) {
      tokens.push({ type: 'icon', name: icon[1] });
      continue;
    }
    const link = part.startsWith('[') ? LINK_PARTS.exec(part) : null;
    if (link) {
      const href = link[2];
      tokens.push({
        type: 'link',
        value: link[1],
        href,
        external: /^https?:\/\//.test(href),
      });
      continue;
    }
    tokens.push({ type: 'text', value: part });
  }
  return tokens;
};
