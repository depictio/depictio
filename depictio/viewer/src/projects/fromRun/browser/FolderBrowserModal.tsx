/**
 * Folder browser of the "From a run folder" tab.
 *
 * Left, a real tree of the folders the server may read, grouped by source
 * ("This computer" for the allowed local folders, "S3" for the allowed S3
 * locations, each only when the server enables it), loading each folder's
 * sub-folders when it is expanded, with the reader's recent run folders
 * above it. Right, the selected folder in detail. On top, an editable path
 * bar with suggestions. Keyboard: arrows move and expand, Enter selects.
 *
 * With a private bucket's connection details, that bucket is listed under
 * "S3" too and everything in it is read with them.
 *
 * Rendered inside the create dialog's `Modal.Stack`, so it opens above that
 * dialog and Escape closes only this one.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Button,
  Grid,
  Group,
  Modal,
  Paper,
  ScrollArea,
  Stack,
  Text,
  Tooltip,
  Tree,
  UnstyledButton,
  useTree,
} from '@mantine/core';
import type { RenderTreeNodePayload } from '@mantine/core';
import { Icon } from '@iconify/react';

import {
  folderSource,
  s3BucketOf,
  shortenFolder,
  storageForLocation,
  Z_LAYERS,
} from 'depictio-react-core';
import type {
  FolderInspection,
  FolderSource,
  RunStorageBinding,
  TemplateInfo,
} from 'depictio-react-core';

import { DisabledReason, GatedButton } from '../../../components/settings/SettingsSections';
import { FolderPath } from '../FolderPath';
import { readRecentRunFolders, rememberRunFolder } from '../recentFolders';
import type { RecentRunFolders } from '../recentFolders';
import { FolderDetailPane } from './FolderDetailPane';
import { FolderTreeNode, SOURCE_ICON } from './FolderTreeNode';
import { PathBar } from './PathBar';
import { GROUP_KEY, useFolderTree } from './useFolderTree';

/** Both source groups open, as every opening starts. */
const GROUPS_EXPANDED = { [GROUP_KEY.local]: true, [GROUP_KEY.s3]: true };

interface RecentEntry {
  path: string;
  source: FolderSource;
}

/** The reader's last run folders, above the tree; nothing when there are none. */
const RecentFolders: React.FC<{ entries: RecentEntry[]; onOpen: (path: string) => void }> = ({
  entries,
  onOpen,
}) => {
  if (entries.length === 0) return null;
  return (
    <Stack gap={2} data-testid="browse-recent">
      <Group gap={6} px={4}>
        <Icon icon="mdi:history" width={14} />
        <Text size="xs" fw={700} c="dimmed" tt="uppercase">
          Recent
        </Text>
      </Group>
      {entries.map(({ path, source }) => (
        <Tooltip key={path} label={path} withArrow zIndex={Z_LAYERS.tooltip} openDelay={400}>
          <UnstyledButton
            onClick={() => onOpen(path)}
            px={4}
            py={2}
            data-testid="browse-recent-item"
            data-path={path}
          >
            <Group gap={6} wrap="nowrap">
              <Icon icon={SOURCE_ICON[source]} width={14} style={{ flexShrink: 0 }} />
              <Text size="sm" ff="monospace" truncate>
                {shortenFolder(path, { maxLength: 40 })}
              </Text>
            </Group>
          </UnstyledButton>
        </Tooltip>
      ))}
    </Stack>
  );
};

interface FolderBrowserModalProps {
  opened: boolean;
  onClose: () => void;
  /** Called with the location of the folder the reader picked. */
  onSelect: (location: string) => void;
  /** Folder to open on (the run folder field's value); ignored when empty
   *  or not browsable. */
  initialLocation?: string | null;
  /** Id inside the enclosing `Modal.Stack`. */
  stackId?: string;
  localEnabled: boolean;
  /** The server may browse the S3 locations it lists. */
  s3Enabled: boolean;
  /** A private bucket and its connection details: listed under "S3" and
   *  read with them. */
  privateBucket?: RunStorageBinding | null;
  /** For the names of the templates recognised in folders. */
  templates: TemplateInfo[];
}

const FolderBrowserModal: React.FC<FolderBrowserModalProps> = ({
  opened,
  onClose,
  onSelect,
  initialLocation,
  stackId,
  localEnabled,
  s3Enabled,
  privateBucket = null,
  templates,
}) => {
  const folderTree = useFolderTree({ opened, localEnabled, s3Enabled, privateBucket });
  const s3Shown = s3Enabled || Boolean(privateBucket);
  const tree = useTree({ initialExpandedState: GROUPS_EXPANDED });
  const selected = tree.selectedState[0] ?? null;
  const [pathInput, setPathInput] = useState('');
  const [pathError, setPathError] = useState<string | null>(null);
  const [revealing, setRevealing] = useState(false);
  const [revealTarget, setRevealTarget] = useState<string | null>(null);
  const [recent, setRecent] = useState<RecentRunFolders>({ local: [], s3: [] });
  /** Run markers read by the detail pane, by location. */
  const [inspected, setInspected] = useState<Record<string, boolean>>({});
  const treeBoxRef = useRef<HTMLDivElement>(null);

  const templateTitles = useMemo(
    () => Object.fromEntries(templates.map((t) => [t.template_id, t.name])),
    [templates],
  );

  const selectFolder = useCallback(
    (path: string) => {
      tree.select(path);
      setPathInput(path);
      setPathError(null);
    },
    [tree],
  );

  const goTo = useCallback(
    async (location: string, quiet = false) => {
      setRevealing(true);
      setPathError(null);
      const result = await folderTree.reveal(location);
      setRevealing(false);
      if (!result.ok) {
        if (!quiet && result.error) setPathError(result.error);
        return;
      }
      tree.setExpandedState((prev) => {
        const next = { ...prev };
        for (const key of result.expand) next[key] = true;
        return next;
      });
      selectFolder(result.path);
      setRevealTarget(result.path);
    },
    [folderTree, tree, selectFolder],
  );

  // Every opening starts from the roots, on the field's folder when it can
  // be browsed (silently staying on the roots when it cannot).
  useEffect(() => {
    if (!opened) return;
    tree.clearSelected();
    tree.setExpandedState(GROUPS_EXPANDED);
    setPathInput('');
    setPathError(null);
    setInspected({});
    setRecent(readRecentRunFolders());
    const start = (initialLocation ?? '').trim();
    if (start) {
      const source = folderSource(start);
      if ((source === 's3' && s3Shown) || (source === 'local' && localEnabled)) {
        setPathInput(start);
        void goTo(start, true);
      }
    }
    // Only opening matters: the field cannot change while this modal is on top.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened]);

  // Expanding a folder lists its sub-folders, once.
  useEffect(() => {
    for (const [key, isOpen] of Object.entries(tree.expandedState)) {
      if (!isOpen) continue;
      const node = folderTree.nodes[key];
      if (node?.hasChildren && !folderTree.children[key]) void folderTree.load(key);
    }
  }, [tree.expandedState, folderTree.nodes, folderTree.children, folderTree.load]);

  // Scroll a folder opened from elsewhere (path bar, recent, search) into view
  // once its row exists.
  useEffect(() => {
    if (!revealTarget || !treeBoxRef.current) return;
    const row = treeBoxRef.current.querySelector<HTMLElement>(
      `[data-path="${CSS.escape(revealTarget)}"]`,
    );
    if (row) {
      row.scrollIntoView({ block: 'nearest' });
      setRevealTarget(null);
    }
  }, [revealTarget, folderTree.treeData, tree.expandedState]);

  const handleInspected = useCallback(
    (location: string, result: FolderInspection | null) => {
      if (!result) return;
      setInspected((prev) => ({ ...prev, [location]: result.looks_like_run }));
      folderTree.markRun(location, result.looks_like_run);
    },
    [folderTree],
  );

  /** What the detail pane read, else what the listing said. */
  const looksLikeRun = (path: string): boolean =>
    inspected[path] ?? folderTree.nodes[path]?.looksLikeRun ?? false;
  const selectedLooksLikeRun = selected ? looksLikeRun(selected) : false;
  const selectedInspected = selected ? selected in inspected : false;
  const selectReason = selected ? null : 'Select a folder first.';

  const confirm = () => {
    if (!selected) return;
    setRecent(rememberRunFolder(selected));
    onSelect(selected);
  };

  // Recent S3 folders the server can browse: any when it lists locations,
  // else only those in the private bucket.
  const recentS3 = s3Enabled
    ? recent.s3
    : recent.s3.filter((path) => privateBucket && s3BucketOf(path) === privateBucket.bucket);
  const recentEntries: RecentEntry[] = [
    ...(localEnabled ? recent.local.map((path) => ({ path, source: 'local' as const })) : []),
    ...recentS3.map((path) => ({ path, source: 's3' as const })),
  ];

  const renderNode = (payload: RenderTreeNodePayload) => (
    <FolderTreeNode
      payload={payload}
      isRun={looksLikeRun}
      onSelect={selectFolder}
      onRetry={folderTree.retry}
    />
  );

  return (
    <Modal
      stackId={stackId}
      opened={opened}
      onClose={onClose}
      centered
      size="75rem"
      zIndex={stackId ? undefined : Z_LAYERS.nestedOverlay}
      overlayProps={{ blur: 3, backgroundOpacity: 0.55 }}
      title={
        <Group gap="xs" wrap="nowrap">
          <Icon icon="mdi:folder-open-outline" width={20} />
          <Text fw={600}>Choose the run folder</Text>
        </Group>
      }
    >
      <Stack gap="sm" data-testid="browse-modal">
        <Text size="sm" c="dimmed">
          Pick the output folder of one pipeline run. Folders marked &ldquo;Run folder&rdquo;
          hold the run&rsquo;s own records.
        </Text>

        <PathBar
          folderTree={folderTree}
          value={pathInput}
          onChange={(value) => {
            setPathInput(value);
            setPathError(null);
          }}
          onGo={(location) => void goTo(location)}
          error={pathError}
          busy={revealing}
          placeholder={localEnabled ? '/path/to/results/run42 or s3://bucket/run42/' : 's3://bucket/results/run42/'}
        />

        <Grid gutter="md">
          <Grid.Col span={{ base: 12, md: 5 }}>
            <Paper withBorder radius="md" p="xs">
              <ScrollArea h={{ base: 260, md: 440 }} type="auto" offsetScrollbars>
                <Stack gap="xs" ref={treeBoxRef}>
                  <RecentFolders entries={recentEntries} onOpen={(path) => void goTo(path)} />
                  <Tree
                    data={folderTree.treeData}
                    tree={tree}
                    levelOffset="md"
                    expandOnClick={false}
                    expandOnSpace
                    renderNode={renderNode}
                    onKeyDown={(event) => {
                      if (event.key !== 'Enter') return;
                      const item = (event.target as HTMLElement).closest<HTMLElement>('[role="treeitem"]');
                      const value = item?.dataset.value;
                      if (value && folderTree.nodes[value]) {
                        event.preventDefault();
                        selectFolder(value);
                      }
                    }}
                    aria-label="Folders"
                    data-testid="browse-tree"
                  />
                </Stack>
              </ScrollArea>
            </Paper>
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 7 }}>
            <Paper withBorder radius="md" p="md">
              <ScrollArea h={{ base: 320, md: 440 }} type="auto" offsetScrollbars>
                <FolderDetailPane
                  location={selected}
                  templateTitles={templateTitles}
                  onReveal={(location) => void goTo(location)}
                  onInspected={handleInspected}
                  storageFor={(location) => storageForLocation(location, privateBucket)}
                />
              </ScrollArea>
            </Paper>
          </Grid.Col>
        </Grid>

        <Group justify="space-between" align="flex-start" wrap="wrap" gap="sm" pt="xs">
          <Stack gap={4} style={{ minWidth: 0, flex: 1 }}>
            {selected && <FolderPath location={selected} testId="browse-selected" />}
            {selected && selectedInspected && !selectedLooksLikeRun && (
              <Group gap={6} wrap="nowrap" align="flex-start" data-testid="browse-not-run-hint">
                <Icon icon="mdi:information-outline" width={14} style={{ flexShrink: 0, marginTop: 2 }} />
                <Text size="xs" c="dimmed">
                  This folder does not look like a run folder (no pipeline_info folder or
                  MultiQC report in it). You can still select it.
                </Text>
              </Group>
            )}
            <DisabledReason reason={selectReason} icon="mdi:information-outline" />
          </Stack>
          <Group gap="xs" wrap="nowrap">
            <Button variant="default" onClick={onClose} data-testid="browse-cancel">
              Cancel
            </Button>
            <GatedButton
              leftSection={<Icon icon="mdi:folder-check-outline" width={16} />}
              reason={selectReason}
              onClick={confirm}
              data-testid="browse-select"
            >
              Select this folder
            </GatedButton>
          </Group>
        </Group>
      </Stack>
    </Modal>
  );
};

export default FolderBrowserModal;
