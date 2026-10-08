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
 * Rendered inside the create dialog's `Modal.Stack`, so it opens above that
 * dialog and Escape closes only this one.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Anchor,
  Box,
  Button,
  Grid,
  Group,
  Loader,
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

import { folderSource, shortenFolder, Z_LAYERS } from 'depictio-react-core';
import type { FolderInspection, FolderSource, TemplateInfo } from 'depictio-react-core';

import { DisabledReason, GatedButton } from '../../../components/settings/SettingsSections';
import { FlowBadge } from '../FlowBadge';
import { FolderPath } from '../FolderPath';
import { readRecentRunFolders, rememberRunFolder } from '../recentFolders';
import type { RecentRunFolders } from '../recentFolders';
import { FolderDetailPane } from './FolderDetailPane';
import { PathBar } from './PathBar';
import { GROUP_KEY, useFolderTree } from './useFolderTree';
import type { TreeNodeProps } from './useFolderTree';

const SOURCE_ICON: Record<FolderSource, string> = {
  local: 'mdi:laptop',
  s3: 'mdi:cloud-outline',
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
  s3Enabled: boolean;
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
  templates,
}) => {
  const folderTree = useFolderTree({ opened, localEnabled, s3Enabled });
  const tree = useTree({
    initialExpandedState: { [GROUP_KEY.local]: true, [GROUP_KEY.s3]: true },
  });
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
    tree.setExpandedState({ [GROUP_KEY.local]: true, [GROUP_KEY.s3]: true });
    setPathInput('');
    setPathError(null);
    setInspected({});
    setRecent(readRecentRunFolders());
    const start = (initialLocation ?? '').trim();
    if (start) {
      const source = folderSource(start);
      if ((source === 's3' && s3Enabled) || (source === 'local' && localEnabled)) {
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

  const selectedLooksLikeRun = selected
    ? (inspected[selected] ?? folderTree.nodes[selected]?.looksLikeRun ?? false)
    : false;
  const selectedInspected = selected ? selected in inspected : false;
  const selectReason = selected ? null : 'Select a folder first.';

  const confirm = () => {
    if (!selected) return;
    setRecent(rememberRunFolder(selected));
    onSelect(selected);
  };

  const recentEntries = [
    ...(localEnabled ? recent.local.map((path) => ({ path, source: 'local' as const })) : []),
    ...(s3Enabled ? recent.s3.map((path) => ({ path, source: 's3' as const })) : []),
  ];

  const renderNode = ({ node, expanded, hasChildren, elementProps, tree: controller }: RenderTreeNodePayload) => {
    const props = (node.nodeProps ?? {}) as TreeNodeProps;

    if (props.kind === 'placeholder') {
      return (
        <Group gap={6} wrap="nowrap" py={4} {...elementProps} style={{ ...elementProps.style, cursor: 'default' }}>
          <Box w={18} style={{ flexShrink: 0 }} />
          {props.placeholder === 'loading' && (
            <>
              <Loader size={12} />
              <Text size="xs" c="dimmed">
                Listing folders...
              </Text>
            </>
          )}
          {props.placeholder === 'empty' && (
            <Text size="xs" c="dimmed" data-testid="browse-tree-empty">
              No folder is available here.
            </Text>
          )}
          {props.placeholder === 'truncated' && (
            <Text size="xs" c="dimmed" data-testid="browse-tree-truncated">
              Only the first 500 folders are listed. Type a path above to reach the others.
            </Text>
          )}
          {props.placeholder === 'error' && (
            <Group gap={6} wrap="nowrap" data-testid="browse-tree-error">
              <Text size="xs" c="red">
                {String(node.label) || 'This folder could not be listed.'}
              </Text>
              {props.parent && (
                <Anchor
                  component="button"
                  type="button"
                  size="xs"
                  onClick={(event) => {
                    event.stopPropagation();
                    folderTree.retry(props.parent as string);
                  }}
                >
                  Try again
                </Anchor>
              )}
            </Group>
          )}
        </Group>
      );
    }

    const chevron = (
      <Box
        w={18}
        style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}
        onClick={(event) => {
          if (!hasChildren) return;
          event.stopPropagation();
          controller.toggleExpanded(node.value);
        }}
        aria-hidden
        data-testid={hasChildren ? 'browse-tree-chevron' : undefined}
      >
        {hasChildren && (
          <Icon icon={expanded ? 'mdi:chevron-down' : 'mdi:chevron-right'} width={16} />
        )}
      </Box>
    );

    if (props.kind === 'group') {
      const source = props.source ?? 'local';
      return (
        <Group
          gap={6}
          wrap="nowrap"
          py={6}
          {...elementProps}
          onClick={(event) => {
            elementProps.onClick(event);
            controller.toggleExpanded(node.value);
          }}
          data-testid={`browse-group-${source}`}
        >
          {chevron}
          <Icon icon={SOURCE_ICON[source]} width={16} />
          <Text size="xs" fw={700} c="dimmed" tt="uppercase">
            {node.label}
          </Text>
        </Group>
      );
    }

    const folder = folderTree.nodes[node.value];
    const isRun = inspected[node.value] ?? folder?.looksLikeRun ?? false;
    return (
      <Group
        gap={6}
        wrap="nowrap"
        py={4}
        pr="xs"
        {...elementProps}
        style={{ ...elementProps.style, borderRadius: 'var(--mantine-radius-sm)' }}
        onClick={(event) => {
          elementProps.onClick(event);
          selectFolder(node.value);
        }}
        onDoubleClick={() => hasChildren && controller.toggleExpanded(node.value)}
        data-testid="browse-tree-node"
        data-path={node.value}
        data-run-folder={isRun || undefined}
      >
        {chevron}
        <Icon
          icon={isRun ? 'mdi:folder-check-outline' : expanded ? 'mdi:folder-open-outline' : 'mdi:folder-outline'}
          width={16}
          style={{ flexShrink: 0 }}
        />
        <Text size="sm" truncate style={{ flex: 1, minWidth: 0 }}>
          {node.label}
        </Text>
        {isRun && <FlowBadge status="run-folder" />}
      </Group>
    );
  };

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
                  {recentEntries.length > 0 && (
                    <Stack gap={2} data-testid="browse-recent">
                      <Group gap={6} px={4}>
                        <Icon icon="mdi:history" width={14} />
                        <Text size="xs" fw={700} c="dimmed" tt="uppercase">
                          Recent
                        </Text>
                      </Group>
                      {recentEntries.map(({ path, source }) => (
                        <Tooltip key={path} label={path} withArrow zIndex={Z_LAYERS.tooltip} openDelay={400}>
                          <UnstyledButton
                            onClick={() => void goTo(path)}
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
                  )}
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
                  This folder does not look like a run folder (no pipeline_info or multiqc
                  folder in it). You can still select it.
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
