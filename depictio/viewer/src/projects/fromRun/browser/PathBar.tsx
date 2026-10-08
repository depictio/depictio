/**
 * The browser's editable path bar. While the reader types it suggests the
 * sub-folders of the folder typed so far (listed on demand, through the same
 * cache as the tree), and the allowed roots that start with the text. Enter,
 * or picking a suggestion, opens the tree on that folder and selects it.
 */
import React, { useEffect, useMemo } from 'react';
import { Combobox, Group, Loader, ScrollArea, Stack, Text, TextInput, useCombobox } from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { Icon } from '@iconify/react';

import { isS3Location, pathBarQuery, shortenHome, Z_LAYERS } from 'depictio-react-core';

import { FlowBadge } from '../FlowBadge';
import type { FolderNode, FolderTreeState } from './useFolderTree';

const MAX_SUGGESTIONS = 50;

interface PathBarProps {
  folderTree: FolderTreeState;
  value: string;
  onChange: (value: string) => void;
  /** Open the tree on `location` and select it. */
  onGo: (location: string) => void;
  error: string | null;
  busy: boolean;
  placeholder: string;
}

export const PathBar: React.FC<PathBarProps> = ({
  folderTree,
  value,
  onChange,
  onGo,
  error,
  busy,
  placeholder,
}) => {
  const combobox = useCombobox({
    onDropdownClose: () => combobox.resetSelectedOption(),
  });
  const [typed] = useDebouncedValue(value, 200);
  const query = useMemo(() => pathBarQuery(typed), [typed]);
  const { load, children, nodes, roots } = folderTree;

  // List the folder being typed into, so its sub-folders can be suggested.
  // A parent the server refuses simply suggests nothing from it.
  useEffect(() => {
    if (!combobox.dropdownOpened || !query.parent) return;
    if (!query.parent.startsWith('/') && !query.parent.startsWith('~') && !isS3Location(query.parent)) {
      return;
    }
    void load(query.parent);
  }, [combobox.dropdownOpened, query.parent, load]);

  const suggestions = useMemo<FolderNode[]>(() => {
    const out: FolderNode[] = [];
    const seen = new Set<string>();
    const partial = query.partial.toLowerCase();
    const state = query.parent ? children[query.parent] : undefined;
    if (state?.status === 'loaded') {
      for (const path of state.paths) {
        const node = nodes[path];
        if (node && node.name.toLowerCase().startsWith(partial) && !seen.has(path)) {
          seen.add(path);
          out.push(node);
        }
      }
    }
    const text = typed.trim().toLowerCase();
    for (const root of roots) {
      const shown = shortenHome(root.path).toLowerCase();
      if (
        !seen.has(root.path) &&
        (!text || root.path.toLowerCase().startsWith(text) || shown.startsWith(text))
      ) {
        seen.add(root.path);
        out.push(root);
      }
    }
    return out.slice(0, MAX_SUGGESTIONS);
  }, [query, children, nodes, roots, typed]);

  const listing = query.parent ? children[query.parent]?.status === 'loading' : false;

  return (
    <Combobox
      store={combobox}
      withinPortal
      zIndex={Z_LAYERS.tooltip}
      onOptionSubmit={(path) => {
        onChange(path);
        onGo(path);
        combobox.closeDropdown();
      }}
    >
      <Combobox.Target>
        <TextInput
          value={value}
          onChange={(event) => {
            onChange(event.currentTarget.value);
            combobox.openDropdown();
            combobox.resetSelectedOption();
          }}
          onFocus={() => combobox.openDropdown()}
          onClick={() => combobox.openDropdown()}
          onBlur={() => combobox.closeDropdown()}
          onKeyDown={(event) => {
            if (event.key !== 'Enter') return;
            // A highlighted suggestion is submitted by the combobox itself.
            if (combobox.dropdownOpened && combobox.getSelectedOptionIndex() !== -1) return;
            event.preventDefault();
            combobox.closeDropdown();
            onGo(value);
          }}
          placeholder={placeholder}
          aria-label="Folder path"
          leftSection={
            <Icon
              icon={isS3Location(value) ? 'mdi:cloud-outline' : 'mdi:folder-outline'}
              width={16}
            />
          }
          rightSection={busy || listing ? <Loader size="xs" /> : null}
          error={error ?? undefined}
          spellCheck={false}
          autoComplete="off"
          styles={{ input: { fontFamily: 'var(--mantine-font-family-monospace)' } }}
          data-testid="browse-path-input"
        />
      </Combobox.Target>
      <Combobox.Dropdown hidden={suggestions.length === 0}>
        <Combobox.Options data-testid="browse-path-suggestions">
          <ScrollArea.Autosize mah={260} type="scroll">
            {suggestions.map((node) => (
              <Combobox.Option
                key={node.path}
                value={node.path}
                data-testid="browse-path-suggestion"
                data-path={node.path}
              >
                <Group gap="xs" wrap="nowrap" justify="space-between">
                  <Group gap="xs" wrap="nowrap" style={{ minWidth: 0 }}>
                    <Icon
                      icon={node.looksLikeRun ? 'mdi:folder-check-outline' : 'mdi:folder-outline'}
                      width={16}
                      style={{ flexShrink: 0 }}
                    />
                    <Stack gap={0} style={{ minWidth: 0 }}>
                      <Text size="sm" truncate>
                        {node.isRoot && node.source === 'local' ? shortenHome(node.path) : node.name}
                      </Text>
                      {!node.isRoot && (
                        <Text size="xs" c="dimmed" truncate>
                          {shortenHome(node.path)}
                        </Text>
                      )}
                    </Stack>
                  </Group>
                  {node.looksLikeRun && <FlowBadge status="run-folder" />}
                </Group>
              </Combobox.Option>
            ))}
          </ScrollArea.Autosize>
        </Combobox.Options>
      </Combobox.Dropdown>
    </Combobox>
  );
};
