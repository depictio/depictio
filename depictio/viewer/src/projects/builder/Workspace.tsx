/**
 * The "Data collections" step: the root's files on the left, the picked
 * file and the collection being edited in the middle (under the selected
 * workflow's settings), the workflows and their collections on the right.
 *
 * Picking a file previews it and starts a collection from the server's
 * suggestion; ticking sibling files generalises the suggested pattern. A
 * store (`*.zarr`) is picked the same way but never previewed. The
 * collection's matches are asked for live and tinted in the tree.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ActionIcon, Badge, Box, Button, Group, ScrollArea, Stack, Text, Tooltip } from '@mantine/core';
import { useMediaQuery } from '@mantine/hooks';
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';

import {
  builderSuggest,
  findBuilderDc,
  isStorePath,
  isTrackFilePath,
  shortenFolder,
  useBrandAccents,
} from 'depictio-react-core';
import type { BuilderAction, BuilderRootSpec, BuilderState, BuilderSuggestion } from 'depictio-react-core';

import { RunFileScope, useRunFilePreview } from '../fromRun/FilePreview';
import { useBuilderCapabilities } from './BuilderCapabilitiesContext';
import { CollectionEditor } from './collections/CollectionEditor';
import { applySuggestion, dcFormFromExisting, newDcForm, withManifest } from './collections/dcForm';
import { dcTypeUnavailableReason } from './collections/dcTypes';
import type { DcFormState } from './collections/dcForm';
import { matchResultOf, useBuilderMatch } from './collections/useBuilderMatch';
import { FilePane } from './files/FilePane';
import { FileTree } from './files/FileTree';
import type { TreePickKind } from './files/FileTree';
import { clampPanel, ResizeHandle } from './layout/ResizeHandle';
import { joinRoot } from './paths';
import { WorkflowEditor } from './workflows/WorkflowEditor';
import { WorkflowTree } from './workflows/WorkflowTree';

interface WorkspaceProps {
  root: BuilderRootSpec;
  remote: boolean;
  state: BuilderState;
  dispatch: React.Dispatch<BuilderAction>;
  /** The root could not be listed (e.g. a private bucket's details). */
  onRootError?: (code: string | null) => void;
  /** To the review step. */
  onReview: () => void;
  /** Open this saved collection in the editor (from the review step). */
  editRequest?: { tag: string; nonce: number } | null;
}

const BORDER = '1px solid var(--mantine-color-default-border)';

const PanelHeader: React.FC<{ icon: string; title: string; children?: React.ReactNode }> = ({
  icon,
  title,
  children,
}) => (
  <Group gap={6} px="sm" py={8} justify="space-between" wrap="nowrap" style={{ borderBottom: BORDER }}>
    <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
      <Icon icon={icon} width={15} color="var(--mantine-color-dimmed)" style={{ flexShrink: 0 }} />
      <Text size="xs" fw={700} tt="uppercase" c="dimmed">
        {title}
      </Text>
    </Group>
    {children}
  </Group>
);

export const Workspace: React.FC<WorkspaceProps> = (props) => (
  <RunFileScope dataRoot={props.root.data_root} storage={props.root.storage ?? null} inferTypes>
    <WorkspaceInner {...props} />
  </RunFileScope>
);

const WorkspaceInner: React.FC<WorkspaceProps> = ({
  root,
  remote,
  state,
  dispatch,
  onRootError,
  onReview,
  editRequest = null,
}) => {
  const accent = useBrandAccents();
  const { capabilities } = useBuilderCapabilities();
  const capabilitiesRef = useRef(capabilities);
  capabilitiesRef.current = capabilities;
  const narrow = useMediaQuery('(max-width: 62em)') ?? false;
  const [treeWidth, setTreeWidth] = useState(320);
  const [asideWidth, setAsideWidth] = useState(340);
  const growTree = useCallback((dx: number) => setTreeWidth((w) => clampPanel(w + dx)), []);
  const growAside = useCallback((dx: number) => setAsideWidth((w) => clampPanel(w - dx)), []);

  const [activeFile, setActiveFile] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [form, setForm] = useState<DcFormState | null>(null);
  const [suggestion, setSuggestion] = useState<BuilderSuggestion | null>(null);
  const [suggesting, setSuggesting] = useState(false);
  const [treeRefresh, setTreeRefresh] = useState(0);
  const [matchRefresh, setMatchRefresh] = useState(0);

  const stateRef = useRef(state);
  stateRef.current = state;
  /** Entries the tree said are stores (`*.zarr` folders). */
  const storePaths = useRef<Set<string>>(new Set());
  const isStore = useCallback((path: string) => storePaths.current.has(path) || isStorePath(path), []);
  const activeWorkflow = state.workflows.find((w) => w.id === state.activeWorkflowId) ?? state.workflows[0];

  // The form follows the selected workflow while it is a new collection, and
  // never points at a workflow that is gone.
  useEffect(() => {
    setForm((f) => {
      if (!f) return f;
      const exists = state.workflows.some((w) => w.id === f.workflowId);
      if (f.originalTag === null && f.workflowId !== state.activeWorkflowId) {
        return { ...f, workflowId: state.activeWorkflowId };
      }
      return exists ? f : { ...f, workflowId: state.activeWorkflowId };
    });
  }, [state.activeWorkflowId, state.workflows]);

  // The collection being edited was removed (from the workflows panel).
  useEffect(() => {
    if (form?.originalTag && !findBuilderDc(state, form.originalTag)) setForm(null);
  }, [state, form?.originalTag]);

  // What the server suggests for the picked file, generalised over the
  // ticked examples; filled into what the reader has not set by hand.
  const pickedKey = [...picked].sort().join('\n');
  const rootKey = `${root.data_root}\n${JSON.stringify(root.storage ?? null)}`;
  useEffect(() => {
    if (!activeFile) {
      setSuggestion(null);
      setSuggesting(false);
      return undefined;
    }
    const examples = [...picked].filter((p) => p !== activeFile);
    const controller = new AbortController();
    setSuggesting(true);
    builderSuggest(root, activeFile, examples, { signal: controller.signal })
      .then((s) => {
        if (controller.signal.aborted) return;
        setSuggestion(s);
        setForm((f) => (f ? applySuggestion(stateRef.current, f, s, capabilitiesRef.current) : f));
      })
      .catch(() => {
        if (!controller.signal.aborted) setSuggestion(null);
      })
      .finally(() => {
        if (!controller.signal.aborted) setSuggesting(false);
      });
    return () => controller.abort();
    // `picked` is read through its key; `root` through its key.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeFile, pickedKey, rootKey]);

  // A store is never previewed: `/suggest` describes it instead.
  const activeIsStore = activeFile ? isStore(activeFile) : false;
  const preview = useRunFilePreview(activeFile && !activeIsStore ? joinRoot(root.data_root, activeFile) : null);
  const columns =
    preview.status === 'ready' && preview.preview.format === 'table' ? preview.preview.columns : [];

  const formWorkflow = form
    ? state.workflows.find((w) => w.id === form.workflowId) ?? activeWorkflow
    : null;
  // A type the server does not build, or this root cannot hold, is never
  // sent, not even to be matched.
  const matchable = form && !dcTypeUnavailableReason(form.dc.type, remote, capabilities) ? form.dc : null;
  const match = useBuilderMatch(
    root,
    formWorkflow ? { structure: formWorkflow.structure, runs_regex: formWorkflow.runs_regex } : null,
    matchable,
    { remote, refresh: matchRefresh, capabilities },
  );
  const matchResult = matchResultOf(match);
  const matched = useMemo(() => new Set(matchResult?.files ?? []), [matchResult]);
  const claimed = useMemo(() => {
    const m = new Map<string, string>();
    for (const [tag, files] of Object.entries(state.claimed)) {
      for (const f of files) if (!m.has(f)) m.set(f, tag);
    }
    return m;
  }, [state.claimed]);

  const clearForm = useCallback(() => {
    setForm(null);
    setActiveFile(null);
    setPicked(new Set());
    setSuggestion(null);
  }, []);

  const activeFileRef = useRef<string | null>(null);
  activeFileRef.current = activeFile;

  const activate = useCallback(
    (path: string, kind: TreePickKind = 'file') => {
      if (kind === 'store') storePaths.current.add(path);
      // Clicking the file already open keeps the collection being edited.
      if (path === activeFileRef.current) return;
      setActiveFile(path);
      setPicked(new Set([path]));
      setSuggestion(null);
      // A genomic tracks collection waiting for its downloaded manifest
      // takes the picked file as it. Editing a saved collection: the file is
      // only previewed (its path field offers to use it). Otherwise it starts
      // a new collection.
      setForm((f) => {
        if (f?.awaitingManifest) return withManifest(f, path);
        if (f && f.originalTag !== null) return f;
        return newDcForm(stateRef.current, path, stateRef.current.activeWorkflowId, capabilitiesRef.current);
      });
    },
    [],
  );

  const togglePick = useCallback(
    (path: string, kind: TreePickKind = 'file') => {
      if (kind === 'store') storePaths.current.add(path);
      if (!activeFile) {
        activate(path, kind);
        return;
      }
      setPicked((prev) => {
        const next = new Set(prev);
        // The picked file is the collection's first example: it stays.
        if (next.has(path)) {
          if (path !== activeFile) next.delete(path);
        } else {
          next.add(path);
        }
        return next;
      });
    },
    [activeFile, activate],
  );

  const editDc = useCallback(
    (tag: string) => {
      const located = findBuilderDc(stateRef.current, tag);
      if (!located) return;
      const file = located.dc.path || stateRef.current.claimed[tag]?.[0] || null;
      dispatch({ type: 'workflow/select', id: located.workflowId });
      setForm(dcFormFromExisting(located));
      setActiveFile(file);
      setPicked(new Set(file ? [file] : []));
      setSuggestion(null);
    },
    [dispatch],
  );

  const editNonce = editRequest?.nonce ?? null;
  useEffect(() => {
    if (editRequest) editDc(editRequest.tag);
    // A new request is a new nonce.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editNonce]);

  const save = useCallback(() => {
    if (!form) return;
    const result = match.status === 'ready' ? match.result : null;
    const files =
      result?.files ?? (form.dc.mode === 'single' && form.dc.path ? [form.dc.path] : undefined);
    const target = state.workflows.find((w) => w.id === form.workflowId);
    // The columns the link editor offers: the first file's schema, or a
    // genomic manifest's columns.
    const schema =
      result?.schema ??
      (result?.tracks?.columns.length ? Object.fromEntries(result.tracks.columns.map((c) => [c, ''])) : null);
    dispatch({
      type: 'dc/save',
      workflowId: form.workflowId,
      dc: form.dc,
      originalTag: form.originalTag,
      files,
      schema,
    });
    notifications.show({
      color: accent.secondary,
      title: form.originalTag ? 'Data collection updated' : 'Data collection added',
      message: `${form.dc.tag.trim()} → ${target?.name ?? 'workflow'}`,
      autoClose: 1800,
    });
    clearForm();
  }, [form, match, state.workflows, dispatch, accent.secondary, clearForm]);

  const removeDc = useCallback(
    (tag: string) => dispatch({ type: 'dc/remove', tag }),
    [dispatch],
  );

  const totalDcs = state.workflows.reduce((n, w) => n + w.data_collections.length, 0);

  const tree = (
    <FileTree
      root={root}
      refreshKey={treeRefresh}
      activeFile={activeFile}
      picked={picked}
      matched={matched}
      claimed={claimed}
      onActivate={activate}
      onTogglePick={togglePick}
      onError={onRootError}
    />
  );

  const treeHeader = (
    <PanelHeader icon="mdi:file-tree" title="Files">
      <Group gap={4} wrap="nowrap" style={{ minWidth: 0 }}>
        <Tooltip label={root.data_root} withArrow>
          <Text size="xs" c="dimmed" ff="monospace" truncate maw={180}>
            {shortenFolder(root.data_root, { maxLength: 28 })}
          </Text>
        </Tooltip>
        <Tooltip label="Read the folders again" withArrow>
          <ActionIcon
            variant="subtle"
            color="gray"
            size="sm"
            onClick={() => setTreeRefresh((n) => n + 1)}
            aria-label="Read the folders again"
            data-testid="builder-tree-refresh"
          >
            <Icon icon="mdi:refresh" width={15} />
          </ActionIcon>
        </Tooltip>
      </Group>
    </PanelHeader>
  );

  const center = (
    <Stack gap="md" p="md" maw={960} mx="auto">
      {activeWorkflow && (
        <WorkflowEditor
          key={activeWorkflow.id}
          state={state}
          workflow={activeWorkflow}
          onChange={(patch) => dispatch({ type: 'workflow/patch', id: activeWorkflow.id, patch })}
        />
      )}
      <FilePane
        activeFile={activeFile}
        store={activeIsStore}
        preview={preview}
        suggestion={suggestion}
        suggesting={suggesting}
        examples={picked.size}
        workflowName={activeWorkflow?.name || 'the workflow'}
      />
      {form && (
        <CollectionEditor
          key={form.originalTag ?? 'new'}
          state={state}
          form={form}
          onChange={setForm}
          onSave={save}
          onCancel={clearForm}
          activeFile={activeFile}
          suggestion={suggestion}
          suggesting={suggesting}
          match={match}
          onRefreshMatch={remote ? () => setMatchRefresh((n) => n + 1) : undefined}
          remote={remote}
          columns={columns}
          manifest={{
            root,
            trackFiles: [...picked].filter(isTrackFilePath).sort(),
            onUseManifest: (path) => {
              setForm((f) => (f ? withManifest(f, path) : f));
              setActiveFile(path);
              setPicked(new Set([path]));
              setSuggestion(null);
            },
            onAwaitManifest: () => setForm((f) => (f ? { ...f, awaitingManifest: true } : f)),
            onFilesChanged: () => setTreeRefresh((n) => n + 1),
          }}
        />
      )}
    </Stack>
  );

  const aside = (
    <>
      <PanelHeader icon="mdi:sitemap-outline" title="Workflows">
        <Badge size="sm" variant="light" color={accent.secondary}>
          {state.workflows.length}
        </Badge>
      </PanelHeader>
      <ScrollArea style={{ flex: 1 }} type="auto">
        <Box p="sm">
          <WorkflowTree
            state={state}
            editingTag={form?.originalTag ?? null}
            onSelect={(id) => dispatch({ type: 'workflow/select', id })}
            onRemove={(id) => dispatch({ type: 'workflow/remove', id })}
            onEditDc={editDc}
            onRemoveDc={removeDc}
            onMoveDc={(tag, workflowId) => dispatch({ type: 'dc/move', tag, workflowId })}
          />
        </Box>
      </ScrollArea>
      <Stack gap={8} p="sm" style={{ borderTop: BORDER }}>
        <Button
          fullWidth
          variant="default"
          leftSection={<Icon icon="mdi:plus" width={16} />}
          onClick={() => dispatch({ type: 'workflow/add' })}
          data-testid="builder-add-workflow"
        >
          Add workflow
        </Button>
        <Button
          fullWidth
          variant="light"
          color={accent.secondary}
          leftSection={<Icon icon="mdi:clipboard-check-outline" width={16} />}
          onClick={onReview}
          disabled={totalDcs === 0}
          data-testid="builder-to-review"
        >
          Review &amp; create
        </Button>
      </Stack>
    </>
  );

  if (narrow) {
    return (
      <ScrollArea h="100%" type="auto">
        <Stack gap={0}>
          <Box style={{ borderBottom: BORDER }}>
            {treeHeader}
            <ScrollArea h={280} scrollbars="xy" type="auto">
              {tree}
            </ScrollArea>
          </Box>
          {center}
          <Box style={{ borderTop: BORDER, display: 'flex', flexDirection: 'column', minHeight: 320 }}>
            {aside}
          </Box>
        </Stack>
      </ScrollArea>
    );
  }

  return (
    <Box style={{ display: 'flex', height: '100%', minHeight: 0 }} data-testid="builder-workspace">
      <Box
        style={{
          width: treeWidth,
          flexShrink: 0,
          position: 'relative',
          borderRight: BORDER,
          display: 'flex',
          flexDirection: 'column',
          minHeight: 0,
        }}
      >
        {treeHeader}
        <ScrollArea style={{ flex: 1 }} scrollbars="xy" type="auto">
          {tree}
        </ScrollArea>
        <ResizeHandle side="right" onResize={growTree} label="Resize the files panel" />
      </Box>
      <ScrollArea style={{ flex: 1, minWidth: 0 }} type="auto">
        {center}
      </ScrollArea>
      <Box
        style={{
          width: asideWidth,
          flexShrink: 0,
          position: 'relative',
          borderLeft: BORDER,
          display: 'flex',
          flexDirection: 'column',
          minHeight: 0,
        }}
      >
        <ResizeHandle side="left" onResize={growAside} label="Resize the workflows panel" />
        {aside}
      </Box>
    </Box>
  );
};
