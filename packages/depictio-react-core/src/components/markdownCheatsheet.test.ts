import { describe, expect, it } from 'vitest';

import { Block, parseBlocks, parseFact, parseLinkRow, parseStatRow } from './blockMarkdown';
import { InlineToken, parseInlineMarkdown } from './inlineMarkdown';
import { MARKDOWN_CHEATSHEET, MarkdownExample } from './markdownCheatsheet';
import { parseTabTile } from './tabLinks';
import { splitPlaceholders } from './textValues';

const examples: MarkdownExample[] = MARKDOWN_CHEATSHEET.flatMap((g) => g.examples);

const inline = (text: string): InlineToken[] => parseInlineMarkdown(text);
const links = (text: string) =>
  inline(text).filter((t): t is Extract<InlineToken, { type: 'link' }> => t.type === 'link');

/** The single list an example parses to, checked in the renderer's order:
 *  result rows win over facts, facts over tab tiles. */
function onlyList(blocks: Block[]): Extract<Block, { type: 'list' }> {
  expect(blocks).toHaveLength(1);
  expect(blocks[0].type).toBe('list');
  return blocks[0] as Extract<Block, { type: 'list' }>;
}
const allRead = <T>(items: string[], parse: (s: string) => T | null) =>
  items.length > 0 && items.every((item) => parse(item) !== null);
/** The placeholders an example holds, by what the braces hold. */
const placeholders = (text: string) =>
  splitPlaceholders(text).flatMap((s) => (s.type === 'value' ? [s.key] : []));

describe('MARKDOWN_CHEATSHEET', () => {
  it.each(examples.map((e) => [e.label, e] as const))('%s renders as it says', (_, ex) => {
    const blocks = parseBlocks(ex.example);
    switch (ex.renders) {
      case 'heading':
        expect(blocks.every((b) => b.type === 'heading')).toBe(true);
        break;
      case 'emphasis':
        expect(inline(ex.example).map((t) => t.type)).toEqual(
          expect.arrayContaining(['bold', 'italic']),
        );
        break;
      case 'code':
        expect(inline(ex.example).some((t) => t.type === 'code')).toBe(true);
        break;
      case 'link':
        expect(blocks).toEqual([{ type: 'paragraph', text: ex.example }]);
        expect(links(ex.example).every((l) => l.external)).toBe(true);
        break;
      case 'tab-link':
        expect(parseLinkRow(ex.example)).toBeNull();
        expect(links(ex.example)[0]?.href.startsWith('tab:')).toBe(true);
        break;
      case 'params-link':
        // Prose with links in it, not a row of links.
        expect(parseLinkRow(ex.example)).toBeNull();
        expect(links(ex.example).map((l) => l.href)).toEqual(['params:', 'params:primer']);
        break;
      case 'icon':
        expect(inline(ex.example)[0]).toEqual({ type: 'icon', name: 'mdi:dna' });
        break;
      case 'list': {
        const list = onlyList(blocks);
        expect(allRead(list.items, parseFact)).toBe(false);
        expect(allRead(list.items, parseTabTile)).toBe(false);
        break;
      }
      case 'table':
        expect(blocks.map((b) => b.type)).toEqual(['table']);
        break;
      case 'rule':
        expect(blocks).toEqual([{ type: 'rule' }]);
        break;
      case 'facts': {
        const list = onlyList(blocks);
        expect(list.ordered).toBe(false);
        expect(allRead(list.items, parseStatRow)).toBe(false);
        expect(allRead(list.items, parseFact)).toBe(true);
        expect(list.items.every((item) => parseFact(item)?.icon)).toBe(true);
        break;
      }
      case 'steps': {
        expect(blocks).toHaveLength(1);
        const div = blocks[0] as Extract<Block, { type: 'div' }>;
        expect(div.type).toBe('div');
        expect(div.name).toBe('steps');
        expect(onlyList(div.blocks).ordered).toBe(true);
        break;
      }
      case 'results':
        expect(allRead(onlyList(blocks).items, parseStatRow)).toBe(true);
        break;
      case 'tab-tiles': {
        const list = onlyList(blocks);
        expect(list.ordered).toBe(/^\d/.test(ex.example));
        expect(allRead(list.items, parseStatRow)).toBe(false);
        expect(allRead(list.items, parseFact)).toBe(false);
        expect(allRead(list.items, parseTabTile)).toBe(true);
        break;
      }
      case 'link-row':
        expect(blocks).toHaveLength(1);
        expect(parseLinkRow(ex.example)).not.toBeNull();
        break;
      case 'figure': {
        expect(blocks.map((b) => b.type)).toEqual(['heading', 'paragraph']);
        const head = blocks[0] as Extract<Block, { type: 'heading' }>;
        // TextRenderer's `isFigure`: a short heading holding a digit.
        expect(/\d/.test(head.text) && head.text.trim().length <= 12).toBe(true);
        break;
      }
      case 'live-value':
        expect(blocks.map((b) => b.type)).toEqual(['paragraph']);
        expect(placeholders(ex.example)).toEqual(['param:dada_ref_taxonomy']);
        break;
      case 'values-yaml':
        // Every value the YAML declares has a name `values:` accepts.
        expect(ex.example.startsWith('values:\n')).toBe(true);
        for (const line of ex.example.split('\n').slice(1)) {
          expect(line).toMatch(/^ {2}[a-z][a-z0-9_]{0,11}: \{dc: \w+, column: \w+, aggregation: \w+/);
        }
        break;
    }
  });

  it('declares, in its YAML example, the values the live-value examples cite', () => {
    const yaml = examples.find((e) => e.renders === 'values-yaml')!.example;
    const declared = [...yaml.matchAll(/^ {2}([a-z][a-z0-9_]*):/gm)].map((m) => m[1]);
    const cited = examples
      .filter((e) => e.renders === 'results' && placeholders(e.example).length > 0)
      .flatMap((e) => placeholders(e.example));
    expect(cited.length).toBeGreaterThan(0);
    expect(new Set(cited)).toEqual(new Set(declared));
  });

  it('covers every rendering at least once', () => {
    const covered = new Set(examples.map((e) => e.renders));
    expect(covered.size).toBe(18);
  });
});
