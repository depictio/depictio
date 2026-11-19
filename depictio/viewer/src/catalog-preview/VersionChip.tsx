/**
 * Which revision of the catalog a reader is looking at, in one place.
 *
 * The module is what the locks version (`module.yaml` `version`); an output or
 * a render may say which module revision it last changed in, and a module may
 * keep a changelog (SCHEMA.md "Versions"). The chip names the module revision,
 * marked when the output changed in it; its popover lays out the three levels
 * and the history, the entries that touch this output first in line.
 */
import React from 'react';
import { Badge, Box, Code, Group, Popover, Stack, Text, UnstyledButton } from '@mantine/core';
import { History } from 'lucide-react';

import type { OutputInfo } from './shared';

export interface ChangelogEntry {
  version: string;
  date?: string;
  changes: string[];
}

/** A changelog line concerns an output when it names it (`agat_statistics: …`). */
const mentions = (line: string, outputId: string) => line.includes(outputId);

function Level({
  label,
  version,
  note,
}: {
  label: string;
  version?: string | null;
  note?: string;
}) {
  return (
    <Group gap={8} wrap="nowrap" justify="space-between" className="cp-ver-level">
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      {version ? (
        <Code fz={11} className="cp-out-id">
          {version}
        </Code>
      ) : (
        <Text size="xs" c="dimmed" fs="italic">
          {note ?? 'not said'}
        </Text>
      )}
    </Group>
  );
}

export default function VersionChip({
  out,
  renderVersion,
  renderLabel,
}: {
  out: OutputInfo;
  /** The version of the render shown below, when it declares one. */
  renderVersion?: string | null;
  renderLabel?: string;
}) {
  const module = out.module_version;
  if (!module) return null;
  const changelog = (out.changelog ?? []) as ChangelogEntry[];
  // The output changed in the module's current revision: say so on the chip.
  const fresh = out.output_version === module;
  const tool = out.tool_name || out.tool_id || 'module';

  return (
    <Popover position="bottom-start" withArrow shadow="md" width={380}>
      <Popover.Target>
        <UnstyledButton
          className="cp-ver"
          data-fresh={fresh || undefined}
          aria-label={`Version: ${out.tool_id} ${module}${fresh ? ', this output changed in it' : ''}`}
          data-testid="version-chip"
        >
          <History size={12} strokeWidth={2} aria-hidden />
          <span>
            {out.tool_id}@{module}
          </span>
          {fresh ? <span className="cp-ver-dot" aria-hidden /> : null}
        </UnstyledButton>
      </Popover.Target>
      <Popover.Dropdown p="md" className="cp-ver-pop">
        <Stack gap={10}>
          <Box>
            <Text size="sm" fw={700}>
              {tool} {module}
            </Text>
            <Text size="xs" c="dimmed">
              The catalog keeps one revision of each module. Templates record the revision
              they were built against.
            </Text>
          </Box>
          <Stack gap={4}>
            <Level label="Module" version={module} />
            <Level
              label="This output, last changed in"
              version={out.output_version}
              note={`not said (covered by ${module})`}
            />
            <Level
              label={renderLabel ? `${renderLabel}, last changed in` : 'This render, last changed in'}
              version={renderVersion}
              note="not said"
            />
          </Stack>
          {changelog.length ? (
            <Box>
              <Text size="xs" fw={700} tt="uppercase" c="dimmed" mb={6} style={{ letterSpacing: 0.4 }}>
                Changelog
              </Text>
              <Stack gap={8} className="cp-ver-log">
                {changelog.map((e) => (
                  <Box key={e.version}>
                    <Group gap={6} mb={2}>
                      <Code fz={11} className="cp-out-id">
                        {e.version}
                      </Code>
                      {e.version === module ? (
                        <Badge size="xs" variant="light" color="gray" className="gp-tag-plain">
                          current
                        </Badge>
                      ) : null}
                      {e.date ? (
                        <Text size="xs" c="dimmed">
                          {e.date}
                        </Text>
                      ) : null}
                    </Group>
                    <Box component="ul" className="cp-ver-changes">
                      {[...e.changes]
                        .sort((a, b) => Number(mentions(b, out.id)) - Number(mentions(a, out.id)))
                        .map((c) => (
                          <li key={c} data-mine={mentions(c, out.id) || undefined}>
                            {c}
                          </li>
                        ))}
                    </Box>
                  </Box>
                ))}
              </Stack>
            </Box>
          ) : (
            <Text size="xs" c="dimmed">
              No changelog in this module's <Code fz={10}>module.yaml</Code>.
            </Text>
          )}
        </Stack>
      </Popover.Dropdown>
    </Popover>
  );
}
