import { Box, Group, ScrollArea, Text } from '@mantine/core';

/**
 * Diff-style YAML preview for the append flow: renders the merged output YAML
 * and tints the lines that were just appended (the author's new renders) so the
 * change stands out against the existing entry. Mantine v7's CodeHighlight can't
 * highlight individual lines, so this renders a plain monospaced block with a
 * per-line background rather than token syntax colors.
 */
export default function AppendedYamlPreview({
  yaml,
  addedLines,
}: {
  yaml: string;
  addedLines: number[];
}) {
  const added = new Set(addedLines);
  const lines = yaml.replace(/\n$/, '').split('\n');

  return (
    <div>
      <Group gap={6} mb={6}>
        <Box
          w={12}
          h={12}
          style={{
            borderRadius: 2,
            background: 'var(--mantine-color-green-light)',
            borderLeft: '3px solid var(--mantine-color-green-filled)',
          }}
        />
        <Text size="xs" c="dimmed">
          Highlighted lines are the render(s) you're appending; the rest of the file is unchanged.
        </Text>
      </Group>
      <ScrollArea.Autosize
        mah={420}
        type="auto"
        style={{
          borderRadius: 'var(--mantine-radius-sm)',
          background: 'light-dark(var(--mantine-color-gray-0), var(--mantine-color-dark-8))',
        }}
      >
        <Box
          component="pre"
          m={0}
          py={8}
          style={{
            fontFamily: 'var(--mantine-font-family-monospace)',
            fontSize: 'var(--mantine-font-size-xs)',
            lineHeight: 1.55,
          }}
        >
          {lines.map((line, i) => {
            const isNew = added.has(i);
            return (
              <div
                key={i}
                style={{
                  background: isNew ? 'var(--mantine-color-green-light)' : 'transparent',
                  borderLeft: `3px solid ${isNew ? 'var(--mantine-color-green-filled)' : 'transparent'}`,
                  paddingLeft: 8,
                  paddingRight: 8,
                  whiteSpace: 'pre',
                }}
              >
                {line || ' '}
              </div>
            );
          })}
        </Box>
      </ScrollArea.Autosize>
    </div>
  );
}
