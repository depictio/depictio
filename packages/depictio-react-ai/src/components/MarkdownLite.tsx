import React from 'react';
import { List, Stack, Text } from '@mantine/core';
import { renderInlineMarkdown } from 'depictio-react-core';

type Size = 'xs' | 'sm' | 'md';

type Block =
  | { kind: 'p'; text: string }
  | { kind: 'h'; text: string }
  | { kind: 'ul'; items: string[] }
  | { kind: 'ol'; items: string[] };

const BULLET = /^\s*[-*\u2022]\s+(.*)$/;
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/;
const HEADING = /^\s*#{1,6}\s+(.*)$/;

/** Group lines into paragraphs, headings and (un)ordered lists. One block
 *  per non-empty line for prose: the prompts ask for short paragraphs and
 *  the models emit one per line, so a hard break is the right reading. */
export const splitBlocks = (text: string): Block[] => {
  const blocks: Block[] = [];
  for (const raw of text.split('\n')) {
    const line = raw.trimEnd();
    if (!line.trim()) continue;
    const bullet = BULLET.exec(line);
    const numbered = bullet ? null : NUMBERED.exec(line);
    const heading = bullet || numbered ? null : HEADING.exec(line);
    const last = blocks[blocks.length - 1];
    if (bullet) {
      if (last?.kind === 'ul') last.items.push(bullet[1]);
      else blocks.push({ kind: 'ul', items: [bullet[1]] });
    } else if (numbered) {
      if (last?.kind === 'ol') last.items.push(numbered[1]);
      else blocks.push({ kind: 'ol', items: [numbered[1]] });
    } else if (heading) {
      blocks.push({ kind: 'h', text: heading[1] });
    } else {
      blocks.push({ kind: 'p', text: line.trim() });
    }
  }
  return blocks;
};

/**
 * Renders the small Markdown subset the AI prompts allow: paragraphs,
 * `- ` bullets, `1. ` items, `#` headings, plus the inline bold / italic /
 * code the text component already understands. Same reasoning as
 * `renderInlineMarkdown`: a few regexes instead of a Markdown dependency the
 * viewer does not otherwise carry. Anything the subset does not cover is
 * shown verbatim rather than dropped.
 */
const MarkdownLite: React.FC<{ text: string; size?: Size }> = ({ text, size = 'sm' }) => {
  const blocks = splitBlocks(text);
  if (blocks.length === 0) return null;
  return (
    <Stack gap={4}>
      {blocks.map((b, i) => {
        if (b.kind === 'ul' || b.kind === 'ol') {
          return (
            <List key={i} size={size} spacing={2} type={b.kind === 'ol' ? 'ordered' : 'unordered'}>
              {b.items.map((item, j) => (
                <List.Item key={j}>{renderInlineMarkdown(item)}</List.Item>
              ))}
            </List>
          );
        }
        if (b.kind === 'h') {
          return (
            <Text key={i} size={size} fw={600}>
              {renderInlineMarkdown(b.text)}
            </Text>
          );
        }
        return (
          <Text key={i} size={size} style={{ wordBreak: 'break-word' }}>
            {renderInlineMarkdown(b.text)}
          </Text>
        );
      })}
    </Stack>
  );
};

export default MarkdownLite;
