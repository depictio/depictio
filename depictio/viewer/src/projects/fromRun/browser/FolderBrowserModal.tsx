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
 * "S3" too and everything in it is read with them. A folder refused for want
 * of them opens the form that asks for them below the path bar; once a test
 * connects, the browser opens that folder.
 *
 * Rendered inside the create dialog's `Modal.Stack`, so it opens above that
 * dialog and Escape closes only this one.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActionIcon,
  Box,
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
  isPrivateBucketRefusal,
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
   *  read with them. A new object starts a fresh tree. */
  privateBucket?: RunStorageBinding | null;
  /** The connection details form for the bucket of `location`, shown below
   *  the path bar when reading it was refused for want of them. */
  credentialsForm?: (location: string) => React.ReactNode;
  /** Reading `location` was refused for want of its bucket's details. */
  onCredentialsNeeded?: (location: string) => void;
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
  credentialsForm,
  onCredentialsNeeded,
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
  /** A location refused for want of its bucket's connection details: the
   *  form for them shows, and the location opens once they are given. */
  const [credentialsFor, setCredentialsFor] = useState<string | null>(null);
  const [recent, setRecent] = useState<RecentRunFolders>({ local: [], s3: [] });
  /** Run markers read by the detail pane, by location. */
  const [inspected, setInspected] = useState<Record<string, boolean>>({});
  const treeRef = useRef<HTMLUListElement>(null);
  /** Bumped by every new selection, revealed or clicked: a reveal answering
   *  after a newer one is dropped, so the latest selection wins. */
  const selectionRun = useRef(0);

  const templatesById = useMemo(
    () => Object.fromEntries(templates.map((t) => [t.template_id, t])),
    [templates],
  );
  /** The dialog fills the window; remembered while it stays mounted. */
  const [expanded, setExpanded] = useState(false);

  const selectFolder = useCallback(
    (path: string) => {
      tree.select(path);
      setPathInput(path);
      setPathError(null);
    },
    [tree],
  );

  /** A folder picked in the tree itself: a reveal still in flight, or its
   *  pending scroll, no longer applies. */
  const pickFolder = useCallback(
    (path: string) => {
      selectionRun.current += 1;
      setRevealing(false);
      setRevealTarget(null);
      // The form stays while the reader stays in its bucket.
      setCredentialsFor((cur) => (cur && s3BucketOf(cur) !== s3BucketOf(path) ? null : cur));
      selectFolder(path);
    },
    [selectFolder],
  );

  const goTo = useCallback(
    async (location: string, quiet = false) => {
      selectionRun.current += 1;
      const run = selectionRun.current;
      setRevealing(true);
      setPathError(null);
      const result = await folderTree.reveal(location);
      if (run !== selectionRun.current) return;
      setRevealing(false);
      if (!result.ok) {
        const target = location.trim();
        const needsCredentials =
          Boolean(credentialsForm) && Boolean(s3BucketOf(target)) && isPrivateBucketRefusal(result.code);
        setCredentialsFor(needsCredentials ? target : null);
        if (needsCredentials) onCredentialsNeeded?.(target);
        // Said even on opening: the form below needs its reason.
        if ((!quiet || needsCredentials) && result.error) setPathError(result.error);
        return;
      }
      setCredentialsFor(null);
      tree.setExpandedState((prev) => {
        const next = { ...prev };
        for (const key of result.expand) next[key] = true;
        return next;
      });
      selectFolder(result.path);
      setRevealTarget(result.path);
    },
    [folderTree, tree, selectFolder, credentialsForm, onCredentialsNeeded],
  );

  // Every opening starts from the roots, on the field's folder when it can
  // be browsed (silently staying on the roots when it cannot).
  useEffect(() => {
    if (!opened) return;
    selectionRun.current += 1;
    tree.clearSelected();
    tree.setExpandedState(GROUPS_EXPANDED);
    setPathInput('');
    setPathError(null);
    setRevealing(false);
    setRevealTarget(null);
    setCredentialsFor(null);
    setInspected({});
    setRecent(readRecentRunFolders());
    const start = (initialLocation ?? '').trim();
    if (start) {
      const source = folderSource(start);
      // An S3 folder the server cannot list opens the form for its bucket.
      const s3Browsable = s3Shown || Boolean(credentialsForm);
      if ((source === 's3' && s3Browsable) || (source === 'local' && localEnabled)) {
        setPathInput(start);
        void goTo(start, true);
      }
    }
    // Only opening matters: the field cannot change while this modal is on top.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened]);

  // The details of the refused folder's bucket were given (a successful
  // test): open it, in the fresh tree they start.
  useEffect(() => {
    if (!opened || !credentialsFor || !storageForLocation(credentialsFor, privateBucket)) return;
    void goTo(credentialsFor);
    // Only new details matter; `goTo` clears the refused folder on success.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [privateBucket]);

  // Expanding a folder lists its sub-folders, once.
  useEffect(() => {
    for (const [key, isOpen] of Object.entries(tree.expandedState)) {
      if (!isOpen) continue;
      const node = folderTree.nodes[key];
      if (node?.hasChildren && !folderTree.children[key]) void folderTree.load(key);
    }
  }, [tree.expandedState, folderTree.nodes, folderTree.children, folderTree.load]);

  // Scroll a folder opened from elsewhere (path bar, recent, search) into view
  // once its row exists. Looked up in the tree only: a recent folder above it
  // carries the same `data-path`.
  useEffect(() => {
    if (!revealTarget || !treeRef.current) return;
    const row = treeRef.current.querySelector<HTMLElement>(
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

  // Both panes take the window's height, less the title, the hint, the path
  // bar, the footer and their padding (1rem more around the detail pane);
  // full screen gives them all of it.
  const paneHeight = expanded
    ? { tree: 'calc(100dvh - 17rem)', detail: 'calc(100dvh - 18rem)' }
    : {
        tree: { base: 260, md: 'calc(min(62dvh, 40rem) + 1rem)' },
        detail: { base: 360, md: 'min(62dvh, 40rem)' },
      };

  const renderNode = (payload: RenderTreeNodePayload) => (
    <FolderTreeNode
      payload={payload}
      isRun={looksLikeRun}
      onSelect={pickFolder}
      onRetry={folderTree.retry}
    />
  );

  return (
    <Modal
      stackId={stackId}
      opened={opened}
      onClose={onClose}
      centered
      size="min(96vw, 92rem)"
      fullScreen={expanded}
      zIndex={stackId ? undefined : Z_LAYERS.nestedOverlay}
      overlayProps={{ blur: 3, backgroundOpacity: 0.55 }}
      styles={{ title: { flex: 1 } }}
      title={
        <Group gap="xs" wrap="nowrap" justify="space-between">
          <Group gap="xs" wrap="nowrap">
            <Icon icon="mdi:folder-open-outline" width={20} />
            <Text fw={600}>Choose the run folder</Text>
          </Group>
          <Tooltip label={expanded ? 'Restore the size' : 'Fill the window'} withArrow zIndex={Z_LAYERS.tooltip}>
            <ActionIcon
              variant="subtle"
              color="gray"
              onClick={() => setExpanded((e) => !e)}
              aria-label={expanded ? 'Restore the size' : 'Fill the window'}
              aria-pressed={expanded}
              data-testid="browse-expand"
            >
              <Icon icon={expanded ? 'mdi:arrow-collapse' : 'mdi:arrow-expand'} width={18} />
            </ActionIcon>
          </Tooltip>
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

        {credentialsFor && credentialsForm && (
          <Box data-testid="browse-private-bucket">{credentialsForm(credentialsFor)}</Box>
        )}

        <Grid gutter="md">
          <Grid.Col span={{ base: 12, md: 4 }}>
            <Paper withBorder radius="md" p="xs">
              <ScrollArea h={paneHeight.tree} type="auto" offsetScrollbars>
                <Stack gap="xs">
                  <RecentFolders entries={recentEntries} onOpen={(path) => void goTo(path)} />
                  <Tree
                    ref={treeRef}
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
                        pickFolder(value);
                      }
                    }}
                    aria-label="Folders"
                    data-testid="browse-tree"
                  />
                </Stack>
              </ScrollArea>
            </Paper>
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 8 }}>
            <Paper withBorder radius="md" p="md">
              <ScrollArea h={paneHeight.detail} type="auto" offsetScrollbars>
                <FolderDetailPane
                  location={selected}
                  templatesById={templatesById}
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
