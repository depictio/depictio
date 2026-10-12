/**
 * The data root as a tree, read one folder at a time (`POST
 * /projects/builder/tree`) as folders open. A click on a file previews it and
 * starts a collection from it; its checkbox adds it as another example of the
 * same collection, which generalises the suggested pattern.
 *
 * Two highlights: the files the collection being edited matches (live, a
 * tinted row) and the files saved collections claimed (their tag as a
 * badge). Rows never truncate: long names scroll sideways.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActionIcon,
  Badge,
  Box,
  Checkbox,
  Group,
  Loader,
  Text,
  Tooltip,
  UnstyledButton,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { apiErrorCode, builderTree, useBrandAccents } from 'depictio-react-core';
import type { BuilderRootSpec, BuilderTreeEntry, BuilderTreeListing } from 'depictio-react-core';

import { fileSize } from '../../fromRun/fileSize';
import { ancestorFolders } from '../paths';

type FolderState =
  | { status: 'loading' }
  | { status: 'error'; error: string; code: string | null }
  | { status: 'ready'; listing: BuilderTreeListing };

interface FileTreeProps {
  root: BuilderRootSpec;
  /** Bumped to read every open folder again. */
  refreshKey: number;
  activeFile: string | null;
  picked: Set<string>;
  /** Files the collection being edited matches. */
  matched: Set<string>;
  /** File → tag of the saved collection that claimed it. */
  claimed: Map<string, string>;
  onActivate: (path: string) => void;
  onTogglePick: (path: string) => void;
  /** A refusal the page can act on (a private bucket's details). */
  onError?: (code: string | null) => void;
}

const ROW: React.CSSProperties = { minWidth: '100%', width: 'max-content' };
const NOWRAP: React.CSSProperties = { whiteSpace: 'nowrap' };

export const FileTree: React.FC<FileTreeProps> = ({
  root,
  refreshKey,
  activeFile,
  picked,
  matched,
  claimed,
  onActivate,
  onTogglePick,
  onError,
}) => {
  const accent = useBrandAccents();
  const [folders, setFolders] = useState<Record<string, FolderState>>({});
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const controllers = useRef<Map<string, AbortController>>(new Map());
  const onErrorRef = useRef(onError);
  onErrorRef.current = onError;
  // Read through a ref: a re-render handing a new but equal root object must
  // not read the whole tree again (the effect below keys on `rootKey`).
  const rootRef = useRef(root);
  rootRef.current = root;

  const load = useCallback(
    (path: string) => {
      controllers.current.get(path)?.abort();
      const controller = new AbortController();
      controllers.current.set(path, controller);
      setFolders((prev) => ({ ...prev, [path]: { status: 'loading' } }));
      builderTree(rootRef.current, path, { signal: controller.signal })
        .then((listing) => {
          if (controller.signal.aborted) return;
          setFolders((prev) => ({ ...prev, [path]: { status: 'ready', listing } }));
        })
        .catch((err: Error) => {
          if (controller.signal.aborted) return;
          const code = apiErrorCode(err);
          setFolders((prev) => ({
            ...prev,
            [path]: { status: 'error', error: err.message || 'This folder could not be read.', code },
          }));
          if (path === '') onErrorRef.current?.(code);
        });
    },
    [],
  );

  // A new root starts a fresh tree; a refresh reads the open folders again.
  const expandedRef = useRef(expanded);
  expandedRef.current = expanded;
  // In memory only: new connection details read the tree again.
  const rootKey = `${root.data_root}\n${JSON.stringify(root.storage ?? null)}`;
  const lastRootKey = useRef<string | null>(null);
  useEffect(() => {
    const sameRoot = lastRootKey.current === rootKey;
    lastRootKey.current = rootKey;
    controllers.current.forEach((c) => c.abort());
    controllers.current.clear();
    if (!sameRoot) {
      setFolders({});
      setExpanded(new Set());
      load('');
      return;
    }
    load('');
    expandedRef.current.forEach((path) => load(path));
  }, [rootKey, refreshKey, load]);

  useEffect(
    () => () => {
      controllers.current.forEach((c) => c.abort());
    },
    [],
  );

  // A file opened from elsewhere (a saved collection) shows in the tree.
  const foldersRef = useRef(folders);
  foldersRef.current = folders;
  useEffect(() => {
    if (!activeFile) return;
    const missing = ancestorFolders(activeFile).filter((f) => !expandedRef.current.has(f));
    if (!missing.length) return;
    setExpanded((prev) => new Set([...prev, ...missing]));
    for (const f of missing) {
      if (!foldersRef.current[f]) load(f);
    }
  }, [activeFile, load]);

  const toggle = useCallback(
    (path: string) => {
      setExpanded((prev) => {
        const next = new Set(prev);
        if (next.has(path)) next.delete(path);
        else next.add(path);
        return next;
      });
      if (!folders[path] || folders[path].status === 'error') load(path);
    },
    [folders, load],
  );

  const renderFolder = (path: string, depth: number): React.ReactNode => {
    const folder = folders[path];
    if (!folder || folder.status === 'loading') {
      return (
        <Group gap={6} py={2} style={{ paddingLeft: depth * 14 + 6 }} wrap="nowrap">
          <Loader size={10} />
          <Text size="xs" c="dimmed">
            Reading...
          </Text>
        </Group>
      );
    }
    if (folder.status === 'error') {
      return (
        <Group gap={6} py={2} style={{ paddingLeft: depth * 14 + 6 }} wrap="nowrap">
          <Icon icon="mdi:alert-circle-outline" width={14} color="var(--mantine-color-red-6)" />
          <Text size="xs" c="red" style={NOWRAP}>
            {folder.error}
          </Text>
          <ActionIcon size="xs" variant="subtle" color="gray" onClick={() => load(path)} aria-label="Try again">
            <Icon icon="mdi:refresh" width={12} />
          </ActionIcon>
        </Group>
      );
    }
    const { entries, truncated } = folder.listing;
    if (entries.length === 0) {
      return (
        <Text size="xs" c="dimmed" py={2} style={{ paddingLeft: depth * 14 + 6 }}>
          Empty folder
        </Text>
      );
    }
    return (
      <>
        {entries.map((entry) =>
          entry.is_dir ? (
            <Box key={entry.path}>
              <DirRow entry={entry} depth={depth} open={expanded.has(entry.path)} onToggle={toggle} />
              {expanded.has(entry.path) && renderFolder(entry.path, depth + 1)}
            </Box>
          ) : (
            <FileRow
              key={entry.path}
              entry={entry}
              depth={depth}
              active={entry.path === activeFile}
              picked={picked.has(entry.path)}
              matched={matched.has(entry.path)}
              tag={claimed.get(entry.path) ?? null}
              accent={accent.secondary}
              onActivate={onActivate}
              onTogglePick={onTogglePick}
            />
          ),
        )}
        {truncated && (
          <Text size="xs" c="dimmed" fs="italic" py={2} style={{ paddingLeft: depth * 14 + 6 }}>
            More entries than the server lists.
          </Text>
        )}
      </>
    );
  };

  return (
    <Box p="xs" style={{ width: '100%', minWidth: 'max-content' }} data-testid="builder-file-tree">
      {renderFolder('', 0)}
    </Box>
  );
};

const DirRow: React.FC<{
  entry: BuilderTreeEntry;
  depth: number;
  open: boolean;
  onToggle: (path: string) => void;
}> = ({ entry, depth, open, onToggle }) => (
  <UnstyledButton
    onClick={() => onToggle(entry.path)}
    style={{ display: 'block', padding: '2px 0', paddingLeft: depth * 14, ...ROW }}
    aria-expanded={open}
    data-testid="builder-tree-item"
    data-kind="dir"
    data-path={entry.path}
  >
    <Group gap={4} wrap="nowrap">
      <Icon icon={open ? 'mdi:chevron-down' : 'mdi:chevron-right'} width={14} />
      <Icon icon={open ? 'mdi:folder-open-outline' : 'mdi:folder-outline'} width={14} color="var(--mantine-color-yellow-6)" />
      <Text size="sm" style={NOWRAP}>
        {entry.name}
      </Text>
    </Group>
  </UnstyledButton>
);

const FileRow: React.FC<{
  entry: BuilderTreeEntry;
  depth: number;
  active: boolean;
  picked: boolean;
  matched: boolean;
  tag: string | null;
  accent: string;
  onActivate: (path: string) => void;
  onTogglePick: (path: string) => void;
}> = ({ entry, depth, active, picked, matched, tag, accent, onActivate, onTogglePick }) => {
  const size = fileSize(entry.size);
  return (
    <Group
      gap={6}
      wrap="nowrap"
      style={{
        ...ROW,
        paddingLeft: depth * 14 + 4,
        paddingTop: 2,
        paddingBottom: 2,
        borderRadius: 4,
        // The border is always reserved so the text never shifts.
        borderLeft: `2px solid ${matched ? `var(--mantine-color-${accent}-5)` : 'transparent'}`,
        background: matched
          ? `var(--mantine-color-${accent}-light)`
          : active
            ? 'var(--mantine-color-default-hover)'
            : undefined,
      }}
      data-testid="builder-tree-item"
      data-kind="file"
      data-path={entry.path}
      data-active={active || undefined}
      data-matched={matched || undefined}
      data-claimed-tag={tag ?? undefined}
    >
      <Tooltip label="Another example of the same collection" withArrow openDelay={500}>
        <Checkbox
          size="xs"
          checked={picked}
          onChange={() => onTogglePick(entry.path)}
          aria-label={`Use ${entry.name} as an example`}
          data-testid="builder-tree-pick"
        />
      </Tooltip>
      <UnstyledButton onClick={() => onActivate(entry.path)} style={NOWRAP} data-testid="builder-tree-file">
        <Group gap={4} wrap="nowrap">
          <Icon
            icon={tag ? 'mdi:database-check' : 'mdi:file-outline'}
            width={14}
            color={tag ? `var(--mantine-color-${accent}-6)` : 'var(--mantine-color-dimmed)'}
          />
          <Text size="sm" fw={active ? 600 : undefined} style={NOWRAP}>
            {entry.name}
          </Text>
          {size && (
            <Text size="xs" c="dimmed" style={NOWRAP}>
              {size}
            </Text>
          )}
        </Group>
      </UnstyledButton>
      {tag && (
        <Tooltip label={`In data collection “${tag}”`} withArrow>
          <Badge size="xs" variant="light" color={accent} radius="sm" tt="none" style={{ flexShrink: 0 }}>
            {tag}
          </Badge>
        </Tooltip>
      )}
    </Group>
  );
};
