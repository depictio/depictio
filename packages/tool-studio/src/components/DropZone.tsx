/**
 * A file drop zone with a visible loaded state.
 *
 * Empty, it is the dashed tile waiting to be filled. Once something is loaded
 * it switches to a solid border in the Studio's tone, a check icon and a one-line summary of
 * what it holds, so the author sees at a glance that the drop worked; clicking
 * or dropping again replaces it. `compact` is the slim variant used where the
 * zone is a secondary path (the expected output next to a recipe).
 */
import { useRef, useState } from 'react';
import { Center, Group, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';
import { STUDIO_TONE } from '../theme';

const TONE = `var(--mantine-color-${STUDIO_TONE}-6)`;
const TONE_LIGHT = `var(--mantine-color-${STUDIO_TONE}-light)`;

export interface DropZoneProps {
  /** Called with the dropped or picked files (already filtered to one unless `multiple`). */
  onFiles: (files: File[]) => void;
  multiple?: boolean;
  /** Text shown while empty. */
  emptyLabel: string;
  /** Smaller line under the label while empty. */
  emptyHint?: string;
  /** When set, the zone renders its loaded state: the name(s) and a summary. */
  loaded?: { label: string; summary?: string } | null;
  compact?: boolean;
  testId?: string;
}

export default function DropZone({
  onFiles,
  multiple = false,
  emptyLabel,
  emptyHint,
  loaded,
  compact = false,
  testId,
}: DropZoneProps) {
  const [dragActive, setDragActive] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const take = (list: FileList | null | undefined) => {
    const files = Array.from(list ?? []);
    if (files.length) onFiles(multiple ? files : files.slice(0, 1));
  };

  const borderColor = dragActive
    ? TONE
    : loaded
      ? TONE
      : 'var(--gp-input-line, var(--mantine-color-default-border))';
  const background = dragActive
    ? TONE_LIGHT
    : loaded
      ? TONE_LIGHT
      : 'var(--gp-card-bg, transparent)';

  return (
    <>
      <button
        type="button"
        data-testid={testId}
        data-loaded={loaded ? 'true' : 'false'}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragActive(true);
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragActive(false);
          take(e.dataTransfer.files);
        }}
        style={{
          width: '100%',
          borderWidth: loaded ? 1.5 : 2,
          borderStyle: loaded ? 'solid' : 'dashed',
          // The Paper tile radius and hairline (glass.css), so the zone reads as
          // one of the page's cards waiting to be filled.
          borderRadius: 'var(--gl-tile-radius, 8px)',
          borderColor,
          padding: compact ? '12px 16px' : loaded ? '20px' : '36px 20px',
          cursor: 'pointer',
          background,
          color: 'inherit',
          transition: 'border-color 120ms, background-color 120ms, padding 120ms',
        }}
      >
        {loaded ? (
          <Group gap="sm" wrap="nowrap" justify="center">
            <Icon icon="mdi:check-circle" width={compact ? 20 : 26} color={TONE} />
            <Stack gap={0} align="flex-start" style={{ minWidth: 0 }}>
              <Text fw={600} size={compact ? 'sm' : 'md'} truncate>
                {loaded.label}
              </Text>
              <Text size="xs" c="dimmed">
                {loaded.summary ? `${loaded.summary} · ` : ''}click or drop to replace
              </Text>
            </Stack>
          </Group>
        ) : compact ? (
          <Group gap="xs" justify="center" wrap="nowrap">
            <Icon icon="mdi:file-upload-outline" width={18} />
            <Text size="sm">{emptyLabel}</Text>
          </Group>
        ) : (
          <Center>
            <Stack align="center" gap={4}>
              <Icon icon="mdi:file-upload-outline" width={40} />
              <Text fw={600}>{emptyLabel}</Text>
              {emptyHint && (
                <Text size="xs" c="dimmed">
                  {emptyHint}
                </Text>
              )}
            </Stack>
          </Center>
        )}
      </button>
      <input
        ref={inputRef}
        type="file"
        multiple={multiple}
        style={{ display: 'none' }}
        onChange={(e) => {
          take(e.currentTarget.files);
          // Picking the same file again must still fire onChange.
          e.currentTarget.value = '';
        }}
      />
    </>
  );
}
