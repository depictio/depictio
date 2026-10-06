/**
 * The body's markdown, one copyable example per syntax, folded under the body
 * field. The examples come from `MARKDOWN_CHEATSHEET` in depictio-react-core,
 * whose test holds each one to what the renderer parses, so this can only
 * offer syntax that renders.
 */
import React from 'react';
import {
  ActionIcon,
  Button,
  Code,
  Collapse,
  CopyButton,
  Group,
  ScrollArea,
  Stack,
  Text,
  Tooltip,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { Icon } from '@iconify/react';
import { MARKDOWN_CHEATSHEET } from 'depictio-react-core';

/** A note with its `code` spans set as code, the rest as text. */
const Note: React.FC<{ text: string }> = ({ text }) => (
  <Text size="xs" c="dimmed">
    {text.split('`').map((part, i) => (i % 2 ? <Code key={i}>{part}</Code> : part))}
  </Text>
);

const MarkdownHelp: React.FC = () => {
  const [opened, { toggle }] = useDisclosure(false);
  return (
    <Stack gap={4}>
      <Group>
        <Button
          variant="subtle"
          size="compact-xs"
          color="gray"
          onClick={toggle}
          leftSection={<Icon icon="mdi:language-markdown-outline" width={14} />}
          rightSection={<Icon icon={opened ? 'mdi:chevron-up' : 'mdi:chevron-down'} width={14} />}
          aria-expanded={opened}
        >
          Markdown help
        </Button>
      </Group>
      <Collapse in={opened}>
        {/* Bounded so the help never pushes the rest of the form out of reach. */}
        <ScrollArea.Autosize mah={380} type="auto" offsetScrollbars>
          <Stack gap="sm" pr={4}>
            {MARKDOWN_CHEATSHEET.map((group) => (
              <Stack key={group.group} gap={8}>
                <Text size="xs" fw={700} tt="uppercase" c="dimmed">
                  {group.group}
                </Text>
                {group.examples.map((ex) => (
                  <Group key={ex.label} gap="xs" wrap="nowrap" align="flex-start">
                    <Stack gap={2} style={{ flex: 1, minWidth: 0 }}>
                      <Text size="xs" fw={600}>
                        {ex.label}
                      </Text>
                      <Code block style={{ whiteSpace: 'pre-wrap', fontSize: 11 }}>
                        {ex.example}
                      </Code>
                      {ex.note ? <Note text={ex.note} /> : null}
                    </Stack>
                    <CopyButton value={ex.example} timeout={1500}>
                      {({ copied, copy }) => (
                        <Tooltip label={copied ? 'Copied' : 'Copy'} withArrow>
                          <ActionIcon
                            size="sm"
                            variant="subtle"
                            color={copied ? 'teal' : 'gray'}
                            onClick={copy}
                            aria-label={`Copy the ${ex.label.toLowerCase()} example`}
                            mt={18}
                          >
                            <Icon icon={copied ? 'mdi:check' : 'mdi:content-copy'} width={14} />
                          </ActionIcon>
                        </Tooltip>
                      )}
                    </CopyButton>
                  </Group>
                ))}
              </Stack>
            ))}
          </Stack>
        </ScrollArea.Autosize>
      </Collapse>
    </Stack>
  );
};

export default MarkdownHelp;
