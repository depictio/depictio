/**
 * Depictio Studio — a folder → project authoring wizard.
 *
 * Reuses the depictio look: an `AppShell` (files in the navbar, wizard in the
 * main area, a workflow → data-collection tree in the aside) and a teal `Stepper`
 * styled like `projects/CreateProjectModal`. Scope stops at the data setup — group
 * files into data collections under one or several workflows (each with its own
 * folder + engine), then write a validated `depictio_project.yaml` importable via
 * `depictio run`. Dashboards are authored later, in the editor of a real deployment.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Anchor,
  AppShell,
  Badge,
  Box,
  Button,
  Code,
  Collapse,
  Group,
  NumberInput,
  Paper,
  ScrollArea,
  Select,
  Stack,
  Stepper,
  TagsInput,
  Text,
  TextInput,
  Title,
  Tooltip,
  UnstyledButton,
  useComputedColorScheme,
  useMantineColorScheme,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { notifications } from '@mantine/notifications';
import * as api from './backend';
import type {
  DcDraft,
  ExportResult,
  PreviewData,
  RecognizeResult,
  ScanPreview,
  TreeNode,
  WorkflowDraft,
  WorkflowMetadata,
} from './backend';
import FileTree from './FileTree';
import DataPanel, { PreviewGrid, SchemaList } from './DataPanel';
import YamlBlock from './YamlBlock';
// depictio's own engine/catalog logos, inlined into the single-file bundle.
import nextflowLogo from '../../public/logos/workflows/nextflow.png';
import snakemakeLogo from '../../public/logos/workflows/snakemake.png';
import galaxyLogo from '../../public/logos/workflows/galaxy.png';
import nfcoreLogo from '../../public/logos/workflows/nf-core.png';
import iwcLogo from '../../public/logos/workflows/iwc.png';

const ENGINE_LOGOS: Record<string, string> = {
  nextflow: nextflowLogo,
  snakemake: snakemakeLogo,
  galaxy: galaxyLogo,
};
const CATALOG_LOGOS: Record<string, string> = {
  'nf-core': nfcoreLogo,
  iwc: iwcLogo,
};

/** A workflow being assembled, plus local-only fields (stripped before export):
 *  a stable id for selection, and the last fetched repo metadata for display. */
interface WfState extends WorkflowDraft {
  _id: string;
  _meta?: WorkflowMetadata;
}

/** Brand logo for a workflow — the catalog logo (nf-core/iwc) wins over the engine
 *  logo (nextflow/snakemake/galaxy); falls back to a generic icon. */
const WorkflowLogo: React.FC<{ engine?: string; catalog?: string; size?: number }> = ({
  engine,
  catalog,
  size = 16,
}) => {
  const src =
    (catalog && CATALOG_LOGOS[catalog]) || (engine && ENGINE_LOGOS[engine.toLowerCase()]);
  if (src) {
    return (
      <img
        src={src}
        alt={catalog || engine || 'workflow'}
        width={size}
        height={size}
        style={{ objectFit: 'contain', display: 'block', flexShrink: 0 }}
      />
    );
  }
  return <Icon icon="mdi:sitemap-outline" width={size} color="var(--mantine-color-teal-6)" />;
};

/** Workflow engines depictio actually supports (those with brand logos +
 *  handling, per viewer/dashboards/lib/workflowIcons.ts) plus `python`, the
 *  studio's default for plain data folders. nf-core / iwc are *catalogs*
 *  (auto-detected from the repo), not engines. */
const ENGINE_SUGGESTIONS = ['nextflow', 'snakemake', 'galaxy', 'python'];

const makeWorkflow = (id: string, name: string): WfState => ({
  _id: id,
  name,
  engine: 'python',
  folder: '',
  structure: 'flat',
  data_collections: [],
});

/** Copy the generated project.yaml to the clipboard. */
function copyYaml(yaml: string): void {
  navigator.clipboard
    .writeText(yaml)
    .then(() =>
      notifications.show({ color: 'teal', title: 'Copied', message: 'project.yaml', autoClose: 1500 }),
    )
    .catch(() =>
      notifications.show({ color: 'red', title: 'Copy failed', message: 'Clipboard blocked' }),
    );
}

/** Trigger a client-side download of the generated project.yaml. */
function downloadYaml(yaml: string): void {
  const blob = new Blob([yaml], { type: 'text/yaml;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'depictio_project.yaml';
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** filename stem → sanitized snake_case data-collection tag. */
function dcTagForFile(path: string): string {
  const base = path.split('/').pop() || path;
  const stem = base.replace(/\.[^.]+$/, '');
  return (
    stem
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '') || 'data_collection'
  );
}

const ThemeToggle: React.FC = () => {
  const { setColorScheme } = useMantineColorScheme();
  const scheme = useComputedColorScheme('light');
  return (
    <Tooltip label={scheme === 'dark' ? 'Light mode' : 'Dark mode'}>
      <ActionIcon
        variant="default"
        size="lg"
        onClick={() => setColorScheme(scheme === 'dark' ? 'light' : 'dark')}
        aria-label="Toggle color scheme"
      >
        <Icon icon={scheme === 'dark' ? 'mdi:weather-sunny' : 'mdi:weather-night'} width={18} />
      </ActionIcon>
    </Tooltip>
  );
};

const PANEL_MIN = 220;
const PANEL_MAX = 640;
const clampPanel = (w: number) => Math.max(PANEL_MIN, Math.min(PANEL_MAX, w));

/** A drag handle on the inner edge of a side panel. `side` is the edge it sits on
 *  (right edge of the navbar, left edge of the aside); `onResize` receives the raw
 *  pointer delta, and the parent applies the sign for its panel. */
const ResizeHandle: React.FC<{ side: 'left' | 'right'; onResize: (dx: number) => void }> = ({
  side,
  onResize,
}) => {
  const dragging = useRef(false);
  useEffect(() => {
    const move = (e: MouseEvent) => {
      if (dragging.current) onResize(e.movementX);
    };
    const stop = () => {
      if (!dragging.current) return;
      dragging.current = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', stop);
    return () => {
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseup', stop);
    };
  }, [onResize]);
  return (
    <Box
      onMouseDown={() => {
        dragging.current = true;
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
      }}
      style={{
        position: 'absolute',
        top: 0,
        bottom: 0,
        [side]: -3,
        width: 6,
        cursor: 'col-resize',
        zIndex: 200,
      }}
    />
  );
};

const StudioApp: React.FC = () => {
  const scheme = useComputedColorScheme('light');

  // Resizable side panels (drag the inner edge); roomier than the Mantine default.
  const [navWidth, setNavWidth] = useState(360);
  const [asideWidth, setAsideWidth] = useState(400);
  const growNav = useCallback((dx: number) => setNavWidth((w) => clampPanel(w + dx)), []);
  const growAside = useCallback((dx: number) => setAsideWidth((w) => clampPanel(w - dx)), []);

  const [tree, setTree] = useState<TreeNode | null>(null);
  const [activeFile, setActiveFile] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [preview, setPreview] = useState<PreviewData | null>(null);
  const [recognize, setRecognize] = useState<RecognizeResult | null>(null);

  // DC form (for the currently active file).
  const [dcTag, setDcTag] = useState('');
  const [mode, setMode] = useState<'single' | 'recursive'>('single');
  const [glob, setGlob] = useState('');
  const [regex, setRegex] = useState('');
  // The regex is reseeded from the glob until the user hand-edits it. A ref keeps
  // that flag out of the scan-preview effect's dependencies.
  const regexEditedRef = useRef(false);
  const [maxDepth, setMaxDepth] = useState<number | ''>('');
  const [ignore, setIgnore] = useState<string[]>([]);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [scan, setScan] = useState<ScanPreview | null>(null);
  const [scanning, setScanning] = useState(false);

  // Workflows: DCs are grouped under workflows. A default one is seeded so
  // single-workflow projects never have to think about the layer.
  const wfCounter = useRef(1);
  const [workflows, setWorkflows] = useState<WfState[]>(() => [makeWorkflow('wf-0', 'main')]);
  const [activeWfId, setActiveWfId] = useState('wf-0');
  const activeWf = workflows.find((w) => w._id === activeWfId) ?? workflows[0];
  const activeFolder = activeWf?.folder ?? '';
  const activeStructure = activeWf?.structure ?? 'flat';
  const activeRunsRegex = activeWf?.runs_regex;
  const allDcs = useMemo(() => workflows.flatMap((w) => w.data_collections), [workflows]);

  // The DC currently being edited (vs. added), keyed by its workflow + tag.
  const [editingDc, setEditingDc] = useState<{ wfId: string; tag: string } | null>(null);

  const [step, setStep] = useState(0);
  const [projectName, setProjectName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ExportResult | null>(null);

  // localStorage persistence: survive an accidental refresh. Keyed by the launch
  // folder so a different folder starts fresh. Hydration is gated so we never
  // overwrite saved work with the initial defaults before restoring.
  const hydratedRef = useRef(false);
  const storageKeyRef = useRef<string | null>(null);

  useEffect(() => {
    api
      .getTree()
      .then(setTree)
      .catch(() => setTree({ name: '', path: '', type: 'dir', children: [] }));
  }, []);

  useEffect(() => {
    let cancelled = false;
    api
      .getContext()
      .then(({ root }) => {
        if (cancelled) return;
        const key = `depictio-studio:${root}`;
        storageKeyRef.current = key;
        try {
          const raw = localStorage.getItem(key);
          const saved = raw ? JSON.parse(raw) : null;
          if (saved && Array.isArray(saved.workflows) && saved.workflows.length) {
            setWorkflows(saved.workflows);
            setActiveWfId(saved.activeWfId ?? saved.workflows[0]._id);
            const maxN = Math.max(
              0,
              ...saved.workflows.map((w: WfState) => {
                const m = /^wf-(\d+)$/.exec(w._id);
                return m ? Number(m[1]) : 0;
              }),
            );
            wfCounter.current = maxN + 1;
            if (typeof saved.projectName === 'string') setProjectName(saved.projectName);
            if (typeof saved.step === 'number') setStep(saved.step);
          }
        } catch {
          /* corrupt / oversized / disabled storage — start fresh */
        }
      })
      .catch(() => {
        /* no context → no persistence */
      })
      .finally(() => {
        hydratedRef.current = true;
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Persist the assembled project (not the transient file-picker state) on change.
  useEffect(() => {
    if (!hydratedRef.current || !storageKeyRef.current) return;
    try {
      localStorage.setItem(
        storageKeyRef.current,
        JSON.stringify({ workflows, projectName, step, activeWfId }),
      );
    } catch {
      /* quota exceeded / disabled — best effort */
    }
  }, [workflows, projectName, step, activeWfId]);

  // Re-run recognition whenever the active file or the example set changes, so
  // the config-by-example glob generalises across sibling picks.
  useEffect(() => {
    if (!activeFile) {
      setRecognize(null);
      return;
    }
    const examples = [...picked].filter((p) => p !== activeFile);
    let cancelled = false;
    api
      .recognize(activeFile, examples)
      .then((r) => {
        if (cancelled) return;
        setRecognize(r);
        // Default the scan mode + glob from the recognition result; the regex is
        // then derived by the scan-preview effect below.
        const many = r.config_by_example.match_count > 1;
        setMode(many ? 'recursive' : 'single');
        setGlob(r.config_by_example.path_glob);
      })
      .catch(() => !cancelled && setRecognize(null));
    return () => {
      cancelled = true;
    };
  }, [activeFile, picked]);

  // Preview the recursive scan: which files the glob matches (scoped to the active
  // workflow's data_location folder), the regex it becomes, and whether those files
  // agree on schema. Debounced so typing doesn't hammer the backend.
  useEffect(() => {
    if (mode !== 'recursive' || !glob.trim()) {
      setScan(null);
      return;
    }
    let cancelled = false;
    setScanning(true);
    // Once hand-edited, the regex is authoritative — match on it so the preview
    // reflects exactly what `depictio run` will ingest. Otherwise let the backend
    // derive it from the glob and seed the field. max_depth/ignore + the workflow
    // subroot are applied by the backend so the preview mirrors ingestion.
    const override = regexEditedRef.current ? regex.trim() : undefined;
    const depth = maxDepth === '' ? null : Number(maxDepth);
    const ignoreTokens = ignore.length ? ignore : undefined;
    const t = setTimeout(() => {
      api
        .scanPreview(
          glob.trim(),
          override,
          depth,
          ignoreTokens,
          activeFolder || undefined,
          activeStructure,
          activeRunsRegex,
        )
        .then((res) => {
          if (cancelled) return;
          setScan(res);
          if (!regexEditedRef.current) setRegex(res.regex);
        })
        .catch(() => !cancelled && setScan(null))
        .finally(() => !cancelled && setScanning(false));
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [glob, mode, regex, maxDepth, ignore.join(' '), activeFolder, activeStructure, activeRunsRegex]);

  // Clear the recursive scan-config fields (glob-derived regex, advanced options,
  // live scan preview).
  const resetScanForm = useCallback(() => {
    regexEditedRef.current = false;
    setRegex('');
    setMaxDepth('');
    setIgnore([]);
    setAdvancedOpen(false);
    setScan(null);
  }, []);

  // Clear the whole in-progress DC selection (on add, or when switching workflow).
  const clearDcForm = useCallback(() => {
    setActiveFile(null);
    setPicked(new Set());
    setPreview(null);
    setRecognize(null);
    setDcTag('');
    setGlob('');
    setMode('single');
    setEditingDc(null);
    resetScanForm();
  }, [resetScanForm]);

  const activate = useCallback(
    (path: string) => {
      setActiveFile(path);
      setPicked(new Set([path]));
      setDcTag(dcTagForFile(path));
      setPreview(null);
      setEditingDc(null); // picking a new file starts a fresh (add) form
      resetScanForm();
      api.previewData(path).then(setPreview).catch(() => setPreview(null));
    },
    [resetScanForm],
  );

  // Load an existing DC back into the form for editing (Save replaces it).
  const editDc = useCallback((wfId: string, dc: DcDraft) => {
    setActiveWfId(wfId);
    setActiveFile(dc.path);
    setPicked(new Set([dc.path]));
    setDcTag(dc.dc_tag);
    setMode(dc.mode);
    setGlob(dc.glob ?? '');
    regexEditedRef.current = !!dc.pattern; // reuse the stored regex verbatim
    setRegex(dc.pattern ?? '');
    setMaxDepth(dc.max_depth ?? '');
    setIgnore(dc.ignore ?? []);
    setAdvancedOpen(dc.max_depth != null || !!dc.ignore?.length);
    setScan(null);
    setPreview(null);
    api.previewData(dc.path).then(setPreview).catch(() => setPreview(null));
    setEditingDc({ wfId, tag: dc.dc_tag });
    setStep(1);
  }, []);

  const togglePick = useCallback(
    (path: string) => {
      setPicked((prev) => {
        const next = new Set(prev);
        if (next.has(path)) {
          // Never un-pick the active file — it is the DC's primary example.
          if (path !== activeFile) next.delete(path);
        } else {
          next.add(path);
        }
        return next;
      });
    },
    [activeFile],
  );

  // ---- workflow management ----
  const patchActiveWf = useCallback(
    (patch: Partial<WfState>) =>
      setWorkflows((prev) => prev.map((w) => (w._id === activeWfId ? { ...w, ...patch } : w))),
    [activeWfId],
  );

  const addWorkflow = useCallback(() => {
    const id = `wf-${wfCounter.current++}`;
    setWorkflows((prev) => {
      const names = new Set(prev.map((w) => w.name));
      let n = prev.length + 1;
      let name = `workflow_${n}`;
      while (names.has(name)) name = `workflow_${++n}`;
      return [...prev, makeWorkflow(id, name)];
    });
    setActiveWfId(id);
    clearDcForm();
  }, [clearDcForm]);

  const removeWorkflow = useCallback(
    (id: string) => {
      if (workflows.length <= 1) return; // always keep one workflow
      // Move selection off the doomed workflow first, then drop it (pure updaters).
      setActiveWfId((cur) =>
        cur === id ? (workflows.find((w) => w._id !== id)?._id ?? cur) : cur,
      );
      setWorkflows((prev) => prev.filter((w) => w._id !== id));
    },
    [workflows],
  );

  const selectWorkflow = useCallback(
    (id: string) => {
      setActiveWfId(id);
      clearDcForm();
    },
    [clearDcForm],
  );

  // ---- data collections (scoped to the active workflow) ----
  // Tags in use elsewhere — the DC being edited may keep its own tag.
  const existingTags = useMemo(
    () => new Set(allDcs.filter((d) => d.dc_tag !== editingDc?.tag).map((d) => d.dc_tag)),
    [allDcs, editingDc],
  );
  const trimmedTag = dcTag.trim();
  const tagInUse = existingTags.has(trimmedTag);
  const canAddDc = !!activeFile && !!preview && !!activeWf && trimmedTag.length > 0 && !tagInUse;

  // Files the in-progress scan resolves to — highlighted live in the file tree.
  const matchedInTree = useMemo(() => {
    if (mode === 'recursive') return new Set(scan?.matched ?? []);
    return new Set(activeFile ? [activeFile] : []);
  }, [mode, scan, activeFile]);

  // path → dc_tag, for every file already claimed by a created DC (across all
  // workflows). A recursive DC claims its matched files; a single DC its one file.
  const assigned = useMemo(() => {
    const m = new Map<string, string>();
    for (const dc of allDcs) {
      const paths = dc.matched && dc.matched.length ? dc.matched : [dc.path];
      for (const p of paths) if (!m.has(p)) m.set(p, dc.dc_tag);
    }
    return m;
  }, [allDcs]);

  const addDc = useCallback(() => {
    if (!activeFile || !preview || !activeWf) return;
    const draft: DcDraft =
      mode === 'recursive'
        ? {
            dc_tag: trimmedTag,
            path: activeFile,
            mode,
            format: preview.format,
            glob,
            pattern: regex.trim() || undefined,
            max_depth: maxDepth === '' ? null : Number(maxDepth),
            ignore: ignore.length ? ignore : undefined,
            matched: scan?.matched?.length ? scan.matched : [activeFile],
          }
        : {
            dc_tag: trimmedTag,
            path: activeFile,
            mode,
            format: preview.format,
            matched: [activeFile],
          };
    const targetWf = activeWf.name;
    const editing = editingDc;
    setWorkflows((prev) =>
      prev.map((w) => {
        if (w._id !== activeWfId) return w;
        if (editing && editing.wfId === activeWfId) {
          // Replace the edited DC in place (preserve order).
          return {
            ...w,
            data_collections: w.data_collections.map((d) =>
              d.dc_tag === editing.tag ? draft : d,
            ),
          };
        }
        return { ...w, data_collections: [...w.data_collections, draft] };
      }),
    );
    clearDcForm();
    notifications.show({
      color: 'teal',
      title: editing ? 'Data collection updated' : 'Data collection added',
      message: `${draft.dc_tag} → ${targetWf}`,
      autoClose: 1800,
    });
  }, [
    activeFile,
    preview,
    activeWf,
    trimmedTag,
    mode,
    glob,
    regex,
    maxDepth,
    ignore,
    scan,
    activeWfId,
    editingDc,
    clearDcForm,
  ]);

  const removeDc = useCallback(
    (tag: string) =>
      setWorkflows((prev) =>
        prev.map((w) => ({
          ...w,
          data_collections: w.data_collections.filter((d) => d.dc_tag !== tag),
        })),
      ),
    [],
  );

  // ---- folder choices for the workflow editor ----
  const folderOptions = useMemo(() => {
    const opts: { value: string; label: string }[] = [{ value: '', label: '· (launch dir)' }];
    const walk = (node: TreeNode) => {
      for (const c of node.children ?? []) {
        if (c.type === 'dir') {
          opts.push({ value: c.path, label: c.path });
          walk(c);
        }
      }
    };
    if (tree) walk(tree);
    return opts;
  }, [tree]);

  // A name clashes if any other workflow already uses it (shown inline on the editor).
  const nameClash = workflows.some((w) => w._id !== activeWfId && w.name === activeWf?.name);
  // Project-wide gates for the Create button.
  const hasDuplicateNames = new Set(workflows.map((w) => w.name)).size !== workflows.length;
  const hasEmptyName = workflows.some((w) => !w.name.trim());
  const emptyWorkflows = workflows.filter((w) => w.data_collections.length === 0);
  const canCreate =
    !!projectName.trim() &&
    allDcs.length > 0 &&
    emptyWorkflows.length === 0 &&
    !hasDuplicateNames &&
    !hasEmptyName;

  const create = useCallback(async () => {
    if (!canCreate) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await api.exportProject({
        name: projectName.trim(),
        // Strip local-only fields (_id, _meta) — only WorkflowDraft is exported.
        workflows: workflows.map(({ _id, _meta, ...w }) => w),
      });
      setResult(res);
      notifications.show({
        color: 'teal',
        title: 'Project created',
        message: res.written_path,
        autoClose: 4000,
      });
    } catch (err) {
      setError((err as Error).message || 'Failed to create project.');
    } finally {
      setSubmitting(false);
    }
  }, [canCreate, projectName, workflows]);

  return (
    <AppShell
      header={{ height: 56 }}
      navbar={{ width: navWidth, breakpoint: 'sm' }}
      aside={{ width: asideWidth, breakpoint: 'md' }}
      padding="md"
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group gap="xs">
            <Icon icon="mdi:palette-swatch" width={24} color="var(--mantine-color-teal-6)" />
            <Title order={3} c="teal" style={{ fontFamily: 'Virgil', fontWeight: 400 }}>
              Studio
            </Title>
            <Text size="xs" c="dimmed">
              local · service-free authoring
            </Text>
          </Group>
          <ThemeToggle />
        </Group>
      </AppShell.Header>

      <AppShell.Navbar>
        <Group
          gap={6}
          px="sm"
          py={8}
          style={{ borderBottom: '1px solid var(--mantine-color-default-border)' }}
        >
          <Icon icon="mdi:file-tree" width={15} color="var(--mantine-color-dimmed)" />
          <Text size="xs" fw={700} tt="uppercase" c="dimmed">
            Files
          </Text>
        </Group>
        <ScrollArea style={{ flex: 1 }} scrollbars="xy" type="auto">
          <FileTree
            tree={tree}
            activeFile={activeFile}
            picked={picked}
            matched={matchedInTree}
            assigned={assigned}
            onActivate={activate}
            onTogglePick={togglePick}
          />
        </ScrollArea>
        <ResizeHandle side="right" onResize={growNav} />
      </AppShell.Navbar>

      <AppShell.Main>
        <Box maw={880} mx="auto">
          <Stepper
            active={step}
            // Navigating away from a created project returns to edit mode, so the
            // user can tweak workflows/DCs and re-create (overwriting the yaml).
            onStepClick={(s) => {
              if (result) setResult(null);
              setStep(s);
            }}
            color="teal"
            size="sm"
            allowNextStepsSelect={false}
          >
            {/* ---- Step 1: Source & preview ---- */}
            <Stepper.Step label="Source" description="Explore the folder">
              <Stack gap="md" pt="md">
                <Alert
                  variant="light"
                  color="teal"
                  icon={<Icon icon="mdi:folder-search-outline" width={18} />}
                >
                  Depictio Studio is browsing the folder it was launched in. Click a file in the{' '}
                  <b>Files</b> panel to preview its data and schema, then move on to group files
                  into data collections under workflows.
                </Alert>
                <DataPanel preview={preview} recognize={recognize} theme={scheme} />
              </Stack>
            </Stepper.Step>

            {/* ---- Step 2: Workflows & data collections ---- */}
            <Stepper.Step label="Data collections" description="Group under workflows">
              <Stack gap="md" pt="md">
                {activeWf && (
                  <WorkflowEditor
                    key={activeWf._id}
                    wf={activeWf}
                    folderOptions={folderOptions}
                    nameClash={nameClash}
                    onChange={patchActiveWf}
                  />
                )}

                {!activeFile ? (
                  <Alert
                    variant="light"
                    color="gray"
                    icon={<Icon icon="mdi:cursor-default-click-outline" width={18} />}
                  >
                    Pick a file in the <b>Files</b> panel to add a data collection to{' '}
                    <b>{activeWf?.name}</b>. Tick sibling files (checkboxes) to cover many samples
                    with one recursive scan.
                  </Alert>
                ) : (
                  <Paper withBorder radius="md" p="md">
                    <Stack gap="sm">
                      <Group gap="xs">
                        <Icon icon="mdi:table" width={18} color="var(--mantine-color-blue-5)" />
                        <Text fw={600} size="sm">
                          {activeFile}
                        </Text>
                        {preview && (
                          <Badge variant="light" size="sm">
                            {preview.format.toUpperCase()} · {preview.columns.length} cols
                          </Badge>
                        )}
                        <Badge variant="light" size="sm" color="grape" ml="auto">
                          {editingDc ? `editing · ${activeWf?.name}` : `→ ${activeWf?.name}`}
                        </Badge>
                      </Group>

                      {recognize && (
                        <Group gap="xs" wrap="wrap">
                          <Icon
                            icon={
                              recognize.recognized
                                ? 'mdi:check-circle'
                                : 'mdi:help-circle-outline'
                            }
                            width={16}
                            color={
                              recognize.recognized
                                ? 'var(--mantine-color-teal-6)'
                                : 'var(--mantine-color-dimmed)'
                            }
                          />
                          <Text size="xs" c="dimmed">
                            {recognize.recognized
                              ? `Recognized: ${recognize.matches.map((m) => m.tool_id).join(', ')}`
                              : 'Unknown tool — using config-by-example'}
                          </Text>
                        </Group>
                      )}

                      <TextInput
                        label="Data collection tag"
                        description="Unique across the whole project"
                        value={dcTag}
                        onChange={(e) => setDcTag(e.currentTarget.value)}
                        leftSection={<Icon icon="mdi:tag-outline" width={16} />}
                        error={
                          tagInUse ? 'A data collection with this tag already exists.' : undefined
                        }
                      />

                      <Select
                        label="Scan mode"
                        description="How files are matched at ingestion"
                        value={mode}
                        onChange={(v) => setMode((v as 'single' | 'recursive') || 'single')}
                        data={[
                          { value: 'single', label: 'Single file' },
                          { value: 'recursive', label: 'Recursive (glob → regex)' },
                        ]}
                        allowDeselect={false}
                        w={260}
                      />

                      {mode === 'recursive' && (
                        <>
                          <TextInput
                            label="Scan glob"
                            description="Files to include (config-by-example). Edits reshape the regex + matches below."
                            value={glob}
                            onChange={(e) => setGlob(e.currentTarget.value)}
                            leftSection={<Icon icon="mdi:file-search-outline" width={16} />}
                            styles={{
                              input: { fontFamily: 'var(--mantine-font-family-monospace)' },
                            }}
                          />
                          <TextInput
                            label="Scan regex"
                            description="Written to regex_config.pattern. Matches each file's name; overrides the glob-derived default."
                            value={regex}
                            onChange={(e) => {
                              regexEditedRef.current = true;
                              setRegex(e.currentTarget.value);
                            }}
                            leftSection={<Icon icon="mdi:regex" width={16} />}
                            rightSection={
                              regexEditedRef.current ? (
                                <Tooltip label="Reset to glob-derived regex">
                                  <ActionIcon
                                    variant="subtle"
                                    color="gray"
                                    onClick={() => {
                                      regexEditedRef.current = false;
                                      if (scan) setRegex(scan.regex);
                                    }}
                                    aria-label="Reset regex"
                                  >
                                    <Icon icon="mdi:restore" width={15} />
                                  </ActionIcon>
                                </Tooltip>
                              ) : undefined
                            }
                            styles={{
                              input: { fontFamily: 'var(--mantine-font-family-monospace)' },
                            }}
                          />

                          <Box>
                            <Button
                              variant="subtle"
                              size="compact-sm"
                              color="gray"
                              leftSection={
                                <Icon
                                  icon={advancedOpen ? 'mdi:chevron-down' : 'mdi:chevron-right'}
                                  width={16}
                                />
                              }
                              onClick={() => setAdvancedOpen((v) => !v)}
                            >
                              Advanced scan options
                            </Button>
                            <Collapse in={advancedOpen}>
                              <Group grow align="flex-start" pt="xs">
                                <NumberInput
                                  label="Max depth"
                                  description="Directory levels to descend (blank = unlimited)"
                                  value={maxDepth}
                                  onChange={(v) => setMaxDepth(v === '' ? '' : (v as number))}
                                  min={0}
                                  allowDecimal={false}
                                />
                                <TagsInput
                                  label="Ignore"
                                  description="Path substrings to skip (press Enter)"
                                  value={ignore}
                                  onChange={setIgnore}
                                  placeholder=".snakemake, tmp"
                                />
                              </Group>
                            </Collapse>
                          </Box>

                          <MatchesPanel scan={scan} scanning={scanning} />
                        </>
                      )}

                      {preview && <SchemaList schema={preview.schema} columns={preview.columns} />}

                      <Group justify="flex-end">
                        {editingDc && (
                          <Button variant="default" onClick={clearDcForm}>
                            Cancel
                          </Button>
                        )}
                        <Button
                          color="teal"
                          leftSection={
                            <Icon icon={editingDc ? 'mdi:content-save' : 'mdi:plus'} width={16} />
                          }
                          onClick={addDc}
                          disabled={!canAddDc}
                        >
                          {editingDc ? 'Save changes' : `Add to ${activeWf?.name}`}
                        </Button>
                      </Group>
                    </Stack>
                  </Paper>
                )}
              </Stack>
            </Stepper.Step>

            {/* ---- Step 3: Review & create ---- */}
            <Stepper.Step label="Create" description="Review & write project.yaml">
              <Stack gap="md" pt="md">
                {result ? (
                  <Stack gap="sm">
                    <Alert
                      color="teal"
                      variant="light"
                      icon={<Icon icon="mdi:check-circle" width={18} />}
                    >
                      Project written to <Code>{result.written_path}</Code>
                    </Alert>
                    <Text size="sm">Import it into a running deployment with:</Text>
                    <Code block>{`depictio run --project ${result.written_path}`}</Code>
                    <Text size="xs" c="dimmed">
                      Then author dashboards in the editor of that deployment.
                    </Text>
                    <Group justify="space-between" align="center">
                      <Text size="xs" fw={700} tt="uppercase" c="dimmed">
                        depictio_project.yaml
                      </Text>
                      <Group gap="xs">
                        <Button
                          size="compact-sm"
                          variant="default"
                          leftSection={<Icon icon="mdi:pencil-outline" width={15} />}
                          onClick={() => {
                            setResult(null);
                            setStep(1);
                          }}
                        >
                          Edit project
                        </Button>
                        <Button
                          size="compact-sm"
                          variant="default"
                          leftSection={<Icon icon="mdi:content-copy" width={15} />}
                          onClick={() => copyYaml(result.project_yaml)}
                        >
                          Copy
                        </Button>
                        <Button
                          size="compact-sm"
                          variant="light"
                          color="teal"
                          leftSection={<Icon icon="mdi:download" width={15} />}
                          onClick={() => downloadYaml(result.project_yaml)}
                        >
                          Download
                        </Button>
                      </Group>
                    </Group>
                    <ScrollArea.Autosize mah={560}>
                      <YamlBlock code={result.project_yaml} />
                    </ScrollArea.Autosize>
                  </Stack>
                ) : (
                  <>
                    <TextInput
                      label="Project name"
                      description="Give the project a descriptive name"
                      required
                      value={projectName}
                      onChange={(e) => setProjectName(e.currentTarget.value)}
                      leftSection={<Icon icon="mdi:folder-outline" width={16} />}
                    />
                    <Text size="sm" fw={600}>
                      {workflows.length} workflow{workflows.length === 1 ? '' : 's'} ·{' '}
                      {allDcs.length} data collection{allDcs.length === 1 ? '' : 's'}
                    </Text>
                    {workflows.map((w) => (
                      <Paper key={w._id} withBorder radius="md" p="sm">
                        <Group gap="xs" mb={6}>
                          <WorkflowLogo engine={w.engine} catalog={w.catalog?.name} size={16} />
                          <Text size="sm" fw={600}>
                            {w.name}
                          </Text>
                          <Badge size="xs" variant="light" color="gray">
                            {w.engine}
                          </Badge>
                          <Badge size="xs" variant="light">
                            {w.structure}
                          </Badge>
                          <Code fz="xs">./{w.folder || '.'}</Code>
                        </Group>
                        <DcList
                          dcs={w.data_collections}
                          onRemove={removeDc}
                          onEdit={(dc) => editDc(w._id, dc)}
                          previewTheme={scheme}
                        />
                      </Paper>
                    ))}
                    {emptyWorkflows.length > 0 && (
                      <Alert color="yellow" variant="light">
                        Every workflow needs at least one data collection:{' '}
                        {emptyWorkflows.map((w) => w.name).join(', ')}.
                      </Alert>
                    )}
                    {error && (
                      <Alert color="red" variant="light">
                        {error}
                      </Alert>
                    )}
                  </>
                )}
              </Stack>
            </Stepper.Step>
          </Stepper>

          {!result && (
            <Group justify="space-between" mt="xl">
              <Button
                variant="default"
                onClick={() => setStep((s) => Math.max(0, s - 1))}
                disabled={step === 0 || submitting}
              >
                Previous
              </Button>
              {step < 2 ? (
                <Button
                  color="teal"
                  onClick={() => setStep((s) => s + 1)}
                  disabled={step === 1 && allDcs.length === 0}
                >
                  Next
                </Button>
              ) : (
                <Button
                  color="teal"
                  onClick={create}
                  loading={submitting}
                  disabled={!canCreate}
                  leftSection={<Icon icon="mdi:check" width={16} />}
                >
                  Create project
                </Button>
              )}
            </Group>
          )}
        </Box>
      </AppShell.Main>

      <AppShell.Aside>
        <ResizeHandle side="left" onResize={growAside} />
        <Group
          gap={6}
          px="sm"
          py={8}
          justify="space-between"
          style={{ borderBottom: '1px solid var(--mantine-color-default-border)' }}
        >
          <Group gap={6}>
            <Icon icon="mdi:sitemap-outline" width={15} color="var(--mantine-color-teal-6)" />
            <Text size="xs" fw={700} tt="uppercase" c="dimmed">
              Workflows
            </Text>
          </Group>
          <Badge size="sm" variant="light" color="teal">
            {workflows.length}
          </Badge>
        </Group>
        <ScrollArea style={{ flex: 1 }} p="sm">
          <WorkflowTree
            workflows={workflows}
            activeWfId={activeWfId}
            onSelect={selectWorkflow}
            onRemove={removeWorkflow}
            onRemoveDc={removeDc}
            onEditDc={editDc}
          />
        </ScrollArea>
        <Box p="sm" style={{ borderTop: '1px solid var(--mantine-color-default-border)' }}>
          <Stack gap={8}>
            <Button
              fullWidth
              variant="default"
              leftSection={<Icon icon="mdi:plus" width={16} />}
              onClick={addWorkflow}
            >
              Add workflow
            </Button>
            {!result && (
              <Button
                fullWidth
                color="teal"
                variant="light"
                leftSection={<Icon icon="mdi:clipboard-check-outline" width={16} />}
                onClick={() => setStep(2)}
                disabled={allDcs.length === 0}
              >
                Review &amp; create
              </Button>
            )}
          </Stack>
        </Box>
      </AppShell.Aside>
    </AppShell>
  );
};

/** Editor for the active workflow: name, engine, repo URL (with metadata fetch),
 *  data_location folder + structure. */
const WorkflowEditor: React.FC<{
  wf: WfState;
  folderOptions: { value: string; label: string }[];
  nameClash: boolean;
  onChange: (patch: Partial<WfState>) => void;
}> = ({ wf, folderOptions, nameClash, onChange }) => {
  const scheme = useComputedColorScheme('light');
  const [fetching, setFetching] = useState(false);
  const repoUrl = (wf.repository_url ?? '').trim();
  // Prefer the fetched pipeline logo (theme-matched) for the header banner.
  const bannerLogo =
    scheme === 'dark'
      ? (wf._meta?.logo_dark ?? wf._meta?.logo)
      : (wf._meta?.logo ?? wf._meta?.logo_dark);

  const fetchMeta = useCallback(async () => {
    if (!repoUrl) return;
    setFetching(true);
    try {
      const meta = await api.fetchWorkflowMetadata(repoUrl);
      const patch: Partial<WfState> = { repository_url: meta.repository_url, _meta: meta };
      if (meta.name) patch.name = meta.name;
      if (meta.engine) patch.engine = meta.engine;
      if (meta.version) patch.version = meta.version;
      if (meta.catalog) patch.catalog = meta.catalog;
      onChange(patch);
      notifications.show(
        meta.sources.length
          ? {
              color: 'teal',
              title: 'Metadata fetched',
              message: `from ${meta.sources.join(', ')}`,
              autoClose: 2500,
            }
          : {
              color: 'yellow',
              title: 'No metadata found',
              message: 'Fill the workflow fields manually.',
              autoClose: 2500,
            },
      );
    } catch (err) {
      notifications.show({
        color: 'red',
        title: 'Metadata fetch failed',
        message: (err as Error).message,
        autoClose: 3000,
      });
    } finally {
      setFetching(false);
    }
  }, [repoUrl, onChange]);

  return (
    <Paper withBorder radius="md" p="md" bg="var(--mantine-color-default-hover)">
      <Stack gap="sm">
        <Group gap="xs">
          <WorkflowLogo engine={wf.engine} catalog={wf.catalog?.name} size={18} />
          <Text fw={600} size="sm">
            Workflow
          </Text>
          {wf.version && (
            <Badge size="xs" variant="light" color="gray">
              v{wf.version}
            </Badge>
          )}
          {wf.catalog && (
            <Badge size="xs" variant="light" color="teal">
              {wf.catalog.name}
            </Badge>
          )}
          {bannerLogo && (
            <img
              src={bannerLogo}
              alt={`${wf.name} logo`}
              style={{ height: 30, maxWidth: 220, objectFit: 'contain', marginLeft: 'auto' }}
            />
          )}
        </Group>
        <Group grow align="flex-start">
          <TextInput
            label="Name"
            description="Unique within the project"
            value={wf.name}
            onChange={(e) => onChange({ name: e.currentTarget.value })}
            error={nameClash ? 'Another workflow already uses this name.' : undefined}
          />
          <Select
            label="Engine"
            description="Process that produced the data"
            value={wf.engine}
            // Keep a fetched/custom engine selectable even if it's not in the list.
            data={
              ENGINE_SUGGESTIONS.includes(wf.engine)
                ? ENGINE_SUGGESTIONS
                : [wf.engine, ...ENGINE_SUGGESTIONS]
            }
            onChange={(v) => onChange({ engine: v || 'python' })}
            searchable
            allowDeselect={false}
          />
        </Group>
        <TextInput
          label="Repository URL"
          description="Optional — fetch name / engine / version from the repo (RO-Crate, Nextflow, GitHub)"
          value={wf.repository_url ?? ''}
          onChange={(e) => onChange({ repository_url: e.currentTarget.value })}
          leftSection={<Icon icon="mdi:git" width={16} />}
          rightSectionWidth={96}
          rightSection={
            <Button
              size="compact-xs"
              variant="light"
              color="teal"
              loading={fetching}
              disabled={!repoUrl}
              onClick={fetchMeta}
              leftSection={<Icon icon="mdi:cloud-download-outline" width={14} />}
            >
              Fetch
            </Button>
          }
        />
        <Group grow align="flex-start">
          <Select
            label="Data folder"
            description="Root of this workflow's data (relative to the launch dir)"
            value={wf.folder}
            data={folderOptions}
            onChange={(v) => onChange({ folder: v ?? '' })}
            searchable
            allowDeselect={false}
            leftSection={<Icon icon="mdi:folder-outline" width={16} />}
          />
          <Select
            label="Structure"
            description="flat, or one level of run_* sub-folders"
            value={wf.structure}
            data={[
              { value: 'flat', label: 'Flat' },
              { value: 'sequencing-runs', label: 'Sequencing runs' },
            ]}
            allowDeselect={false}
            onChange={(v) => {
              const structure = (v as WfState['structure']) || 'flat';
              onChange({
                structure,
                runs_regex: structure === 'sequencing-runs' ? wf.runs_regex || 'run_*' : undefined,
              });
            }}
          />
        </Group>
        {wf.structure === 'sequencing-runs' && (
          <TextInput
            label="Runs glob"
            description="Sub-folders to treat as runs"
            value={wf.runs_regex ?? 'run_*'}
            onChange={(e) => onChange({ runs_regex: e.currentTarget.value })}
            styles={{ input: { fontFamily: 'var(--mantine-font-family-monospace)' } }}
            w={260}
          />
        )}
        {wf._meta && <FetchedMetadata meta={wf._meta} />}
      </Stack>
    </Paper>
  );
};

/** Read-only summary of the metadata pulled from the repo — including fields the
 *  project.yaml doesn't store (description / author / license / homepage), so the
 *  user can see everything that was found and which sources contributed. */
const FetchedMetadata: React.FC<{ meta: WorkflowMetadata }> = ({ meta }) => {
  const rows: [string, React.ReactNode][] = [];
  if (meta.description) rows.push(['Description', meta.description]);
  if (meta.author) rows.push(['Author', meta.author]);
  if (meta.license) rows.push(['License', meta.license]);
  if (meta.homepage)
    rows.push([
      'Homepage',
      <Anchor key="hp" href={meta.homepage} target="_blank" rel="noreferrer" size="xs">
        {meta.homepage}
      </Anchor>,
    ]);
  return (
    <Paper withBorder radius="sm" p="sm" bg="var(--mantine-color-body)">
      <Stack gap={6}>
        <Group gap={6} wrap="wrap">
          <Icon icon="mdi:information-outline" width={15} color="var(--mantine-color-teal-6)" />
          <Text size="xs" fw={700} tt="uppercase" c="dimmed">
            Fetched metadata
          </Text>
          {meta.sources.length ? (
            meta.sources.map((s) => (
              <Badge key={s} size="xs" variant="light" color="teal">
                {s}
              </Badge>
            ))
          ) : (
            <Text size="xs" c="dimmed">
              nothing found — fill fields manually
            </Text>
          )}
        </Group>
        {rows.map(([label, value]) => (
          <Group key={label} gap="xs" wrap="nowrap" align="flex-start">
            <Text size="xs" c="dimmed" fw={600} style={{ minWidth: 76, flexShrink: 0 }}>
              {label}
            </Text>
            {/* Some sources (e.g. nf-core RO-Crate) put the whole README in
                description — clamp so it can't flood the editor. */}
            <Text size="xs" lineClamp={4} style={{ minWidth: 0 }}>
              {value}
            </Text>
          </Group>
        ))}
      </Stack>
    </Paper>
  );
};

/** Aside: workflows, each selectable/removable and listing its DCs. */
const WorkflowTree: React.FC<{
  workflows: WfState[];
  activeWfId: string;
  onSelect: (id: string) => void;
  onRemove: (id: string) => void;
  onRemoveDc: (tag: string) => void;
  onEditDc: (wfId: string, dc: DcDraft) => void;
}> = ({ workflows, activeWfId, onSelect, onRemove, onRemoveDc, onEditDc }) => (
  <Stack gap={10}>
    {workflows.map((w) => {
      const active = w._id === activeWfId;
      return (
        <Paper
          key={w._id}
          withBorder
          radius="sm"
          p={6}
          style={{
            borderColor: active ? 'var(--mantine-color-teal-5)' : undefined,
            background: active ? 'var(--mantine-color-teal-light)' : undefined,
          }}
        >
          <Group justify="space-between" wrap="nowrap" gap={4}>
            <UnstyledButton onClick={() => onSelect(w._id)} style={{ flex: 1, minWidth: 0 }}>
              <Group gap={6} wrap="nowrap">
                <WorkflowLogo engine={w.engine} catalog={w.catalog?.name} size={16} />
                <Text size="sm" fw={600} lineClamp={1}>
                  {w.name || '(unnamed)'}
                </Text>
                <Badge size="xs" variant="light" color="gray">
                  {w.engine}
                </Badge>
                <Badge size="xs" variant="light" color="teal">
                  {w.data_collections.length}
                </Badge>
              </Group>
            </UnstyledButton>
            <Tooltip
              label={workflows.length <= 1 ? 'Keep at least one workflow' : 'Remove workflow'}
            >
              <ActionIcon
                variant="subtle"
                color="red"
                size="sm"
                disabled={workflows.length <= 1}
                onClick={() => onRemove(w._id)}
                aria-label="Remove workflow"
                style={{ flexShrink: 0 }}
              >
                <Icon icon="mdi:close" width={14} />
              </ActionIcon>
            </Tooltip>
          </Group>
          {w.folder && (
            <Text size="xs" c="dimmed" pl={20} lineClamp={1}>
              ./{w.folder}
            </Text>
          )}
          {w.data_collections.length > 0 && (
            <Stack gap={4} pt={6}>
              {w.data_collections.map((dc) => (
                <DcCard
                  key={dc.dc_tag}
                  dc={dc}
                  onRemove={onRemoveDc}
                  onEdit={() => onEditDc(w._id, dc)}
                />
              ))}
            </Stack>
          )}
        </Paper>
      );
    })}
  </Stack>
);

/** Positive schema-agreement message for a consistent scan. */
function schemaAgreementMessage(scan: ScanPreview): string {
  if (scan.match_count === 1) return 'Schema verified for the matched file.';
  if (scan.truncated) {
    return `Identical schema across the sampled matches (${scan.match_count} files total).`;
  }
  return `All ${scan.match_count} matched files share an identical schema.`;
}

/** The files a recursive scan resolves to, with a schema-agreement check. */
const MatchesPanel: React.FC<{ scan: ScanPreview | null; scanning: boolean }> = ({
  scan,
  scanning,
}) => {
  if (scanning && !scan)
    return (
      <Text size="xs" c="dimmed">
        Scanning…
      </Text>
    );
  if (!scan) return null;
  const issues = new Map(scan.mismatches.map((m) => [m.path, m.issue]));
  return (
    <Stack gap={6}>
      <Group gap="xs">
        <Text size="xs" fw={700} tt="uppercase" c="dimmed">
          Matches
        </Text>
        <Badge size="xs" variant="light" color={scan.consistent ? 'teal' : 'yellow'}>
          {scan.match_count} file{scan.match_count === 1 ? '' : 's'}
        </Badge>
        {scan.truncated && (
          <Text size="xs" c="dimmed">
            (schema checked on a sample)
          </Text>
        )}
      </Group>
      {scan.match_count === 0 ? (
        <Text size="xs" c="dimmed">
          No files match this glob.
        </Text>
      ) : (
        <Paper withBorder radius="sm">
          <ScrollArea.Autosize mah={160} type="auto">
            <Stack gap={0}>
              {scan.matched.map((p, i) => {
                const issue = issues.get(p);
                return (
                  <Group
                    key={p}
                    gap={6}
                    wrap="nowrap"
                    px="sm"
                    py={3}
                    style={{
                      borderTop:
                        i === 0 ? undefined : '1px solid var(--mantine-color-default-border)',
                    }}
                  >
                    <Icon
                      icon={issue ? 'mdi:alert' : 'mdi:check'}
                      width={13}
                      color={
                        issue ? 'var(--mantine-color-yellow-6)' : 'var(--mantine-color-teal-6)'
                      }
                    />
                    <Text
                      size="xs"
                      style={{ fontFamily: 'var(--mantine-font-family-monospace)' }}
                      lineClamp={1}
                    >
                      {p}
                    </Text>
                  </Group>
                );
              })}
            </Stack>
          </ScrollArea.Autosize>
        </Paper>
      )}
      {scan.consistent && scan.match_count > 0 && (
        <Group gap={6} wrap="nowrap">
          <Icon icon="mdi:check-circle" width={15} color="var(--mantine-color-teal-6)" />
          <Text size="xs" fw={600} c="teal.7">
            {schemaAgreementMessage(scan)}
          </Text>
        </Group>
      )}
      {!scan.consistent && scan.mismatches.length > 0 && (
        <Alert color="yellow" variant="light" icon={<Icon icon="mdi:alert" width={16} />} p="xs">
          <Text size="xs" fw={600} mb={2}>
            Schemas differ across matches — the collection will still be created.
          </Text>
          <Stack gap={0}>
            {scan.mismatches.map((m) => (
              <Text key={m.path} size="xs" c="dimmed">
                <b>{m.path}</b>: {m.issue}
              </Text>
            ))}
          </Stack>
        </Alert>
      )}
    </Stack>
  );
};

const DcList: React.FC<{
  dcs: DcDraft[];
  onRemove: (tag: string) => void;
  onEdit?: (dc: DcDraft) => void;
  /** When set, each card gets a collapsible first-file preview (review step). */
  previewTheme?: 'light' | 'dark';
}> = ({ dcs, onRemove, onEdit, previewTheme }) => {
  if (dcs.length === 0) {
    return (
      <Text size="sm" c="dimmed">
        No data collections yet.
      </Text>
    );
  }
  return (
    <Stack gap={8}>
      {dcs.map((dc) => (
        <DcCard
          key={dc.dc_tag}
          dc={dc}
          onRemove={onRemove}
          onEdit={onEdit ? () => onEdit(dc) : undefined}
          previewTheme={previewTheme}
        />
      ))}
    </Stack>
  );
};

/** Collapsed-by-default preview of a DC's first matched file. Lazy-loads the data
 *  the first time it is opened so building a project doesn't fetch every file. */
const DcPreview: React.FC<{ file: string; theme: 'light' | 'dark' }> = ({ file, theme }) => {
  const [open, setOpen] = useState(false);
  const [preview, setPreview] = useState<PreviewData | null>(null);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);

  const toggle = useCallback(() => {
    setOpen((wasOpen) => {
      if (!wasOpen && !preview && !loading) {
        setLoading(true);
        setFailed(false);
        api
          .previewData(file)
          .then(setPreview)
          .catch(() => setFailed(true))
          .finally(() => setLoading(false));
      }
      return !wasOpen;
    });
  }, [file, preview, loading]);

  return (
    <Box>
      <Button
        variant="subtle"
        size="compact-xs"
        color="gray"
        leftSection={<Icon icon={open ? 'mdi:chevron-down' : 'mdi:chevron-right'} width={14} />}
        onClick={toggle}
      >
        Preview first file
      </Button>
      <Collapse in={open}>
        <Stack gap={4} pt={4}>
          <Text size="xs" c="dimmed" style={{ fontFamily: 'var(--mantine-font-family-monospace)' }}>
            {file}
          </Text>
          {loading && (
            <Text size="xs" c="dimmed">
              Loading…
            </Text>
          )}
          {failed && (
            <Text size="xs" c="red">
              Could not preview this file.
            </Text>
          )}
          {preview && <PreviewGrid preview={preview} theme={theme} height={200} />}
        </Stack>
      </Collapse>
    </Box>
  );
};

/** One DC as a multi-row card: tag + remove on top, mode/count badges next, then
 *  the glob/path — each truncatable field carries a tooltip since the aside is
 *  narrow. A summary tooltip on the body surfaces the full scan config. In the
 *  review step (`previewTheme` set) a collapsible first-file preview is appended. */
const DcCard: React.FC<{
  dc: DcDraft;
  onRemove: (tag: string) => void;
  onEdit?: () => void;
  previewTheme?: 'light' | 'dark';
}> = ({ dc, onRemove, onEdit, previewTheme }) => {
  const target = dc.mode === 'recursive' ? dc.glob : dc.path;
  const firstFile = dc.matched?.[0] ?? dc.path;
  const summary = (
    <Stack gap={1}>
      <Text size="xs">tag: {dc.dc_tag}</Text>
      <Text size="xs">mode: {dc.mode}</Text>
      <Text size="xs">{dc.mode === 'recursive' ? `glob: ${dc.glob}` : `path: ${dc.path}`}</Text>
      {dc.pattern && <Text size="xs">regex: {dc.pattern}</Text>}
      {dc.max_depth != null && <Text size="xs">max_depth: {dc.max_depth}</Text>}
      {dc.ignore?.length ? <Text size="xs">ignore: {dc.ignore.join(', ')}</Text> : null}
      {dc.matched && <Text size="xs">{dc.matched.length} file(s) matched</Text>}
    </Stack>
  );
  return (
    <Paper withBorder radius="sm" px="sm" py={8}>
      <Stack gap={6}>
        <Group justify="space-between" wrap="nowrap" gap={4}>
          <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
            <Icon icon="mdi:database-outline" width={16} color="var(--mantine-color-teal-6)" />
            <Tooltip label={dc.dc_tag} withArrow openDelay={300}>
              <Text size="sm" fw={600} lineClamp={1}>
                {dc.dc_tag}
              </Text>
            </Tooltip>
          </Group>
          <Group gap={2} wrap="nowrap" style={{ flexShrink: 0 }}>
            {onEdit && (
              <ActionIcon
                variant="subtle"
                color="gray"
                size="sm"
                onClick={onEdit}
                aria-label="Edit data collection"
              >
                <Icon icon="mdi:pencil-outline" width={15} />
              </ActionIcon>
            )}
            <ActionIcon
              variant="subtle"
              color="red"
              size="sm"
              onClick={() => onRemove(dc.dc_tag)}
              aria-label="Remove"
            >
              <Icon icon="mdi:close" width={15} />
            </ActionIcon>
          </Group>
        </Group>
        <Group gap={6}>
          <Badge size="xs" variant="light" color={dc.mode === 'recursive' ? 'grape' : 'blue'}>
            {dc.mode}
          </Badge>
          {dc.matched && dc.mode === 'recursive' && (
            <Badge size="xs" variant="default" radius="sm">
              {dc.matched.length} file{dc.matched.length === 1 ? '' : 's'}
            </Badge>
          )}
        </Group>
        <Tooltip label={summary} withArrow multiline position="left" openDelay={200}>
          <Code
            fz="xs"
            block
            style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
          >
            {target}
          </Code>
        </Tooltip>
        {previewTheme && <DcPreview file={firstFile} theme={previewTheme} />}
      </Stack>
    </Paper>
  );
};

export default StudioApp;
