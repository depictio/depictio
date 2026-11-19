/**
 * A module's history across the site's releases (site build only), from
 * `../modules/<tool>.json`. It completes the VersionChip: the chip says which
 * revision this release ships (module, output, render, changelog); this says
 * which revisions earlier releases shipped, with an "Open in vX.Y.Z" link per
 * version and a line diff of the output's render YAML against the version shown.
 *
 * It opens from the chip's popover ("History across releases") in a modal: the
 * popover is too narrow for a YAML diff, and one entry point keeps the output's
 * header to a single display of its version.
 *
 * Nothing is shown, with no message, when the history cannot be loaded (a bare
 * export, a 404, a network error): `useModuleHistory` then returns no history and
 * the chip offers no link.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { Anchor, Badge, Box, Button, Code, Group, Modal, Stack, Text } from '@mantine/core';
import { FileDiff } from 'lucide-react';
import { useCatalogPaper } from './shared';
import type { CatalogGlobal, OutputEntry } from './shared';
import { diffRenders, foldUnchanged } from './lineDiff';
import type { RenderDiff, RenderLike } from './lineDiff';
import { BUMP_COLOR, fetchModule, fetchVersions } from './siteData';
import type { Bump, ModuleHistory, ModuleVersion } from './siteData';
import { currentSlot, knownSlots, openInSlotHref, pickSlot } from './siteTree';

export const BumpBadge: React.FC<{ bump?: Bump }> = ({ bump }) =>
  bump ? (
    <Badge size="xs" variant="light" color={BUMP_COLOR[bump] ?? 'gray'} radius="sm">
      {bump}
    </Badge>
  ) : null;

export interface ModuleHistoryState {
  history: ModuleHistory | null;
  order: string[];
}

/** The module's history, or null while loading / outside the site build. */
export function useModuleHistory(
  g: CatalogGlobal | undefined,
  toolId?: string | null,
): ModuleHistoryState | null {
  const [state, setState] = useState<ModuleHistoryState | null>(null);
  useEffect(() => {
    setState(null);
    if (!g?.lazyOutputs || !toolId) return;
    let cancelled = false;
    // versions.json first: a bare export has none of the site files, and probing
    // modules/ as well would only add a second 404 to the console.
    fetchVersions(g)
      .then(async (versions) => ({
        versions,
        history: versions ? await fetchModule(g, toolId) : null,
      }))
      .then(({ versions, history }) => {
        if (cancelled) return;
        setState({ history, order: versions ? knownSlots(versions) : [] });
      });
    return () => {
      cancelled = true;
    };
  }, [g, toolId]);
  return state;
}

const DIFF_BG: Record<string, string | undefined> = {
  add: 'var(--mantine-color-green-light)',
  del: 'var(--mantine-color-red-light)',
};

const DiffBlock: React.FC<{ diff: RenderDiff; from?: string; to?: string }> = ({
  diff,
  from,
  to,
}) => {
  const rows = useMemo(() => foldUnchanged(diff.ops, 3), [diff.ops]);
  const statusColor = { same: 'gray', changed: 'yellow', added: 'green', removed: 'red' }[diff.status];
  // The render's own revisions, when its `renders_as` entry says them.
  const versions = from || to ? `${from ? `v${from}` : 'not said'} → ${to ? `v${to}` : 'not said'}` : null;
  return (
    <Box data-render={diff.index} data-status={diff.status}>
      <Group gap={6} mb={4}>
        <Code fz={10} className="cp-out-id">
          {diff.index}
        </Code>
        <Badge size="xs" variant="light" color={statusColor} radius="sm">
          {diff.status === 'same' ? 'unchanged' : diff.status}
        </Badge>
        {versions && from !== to ? (
          <Text size="xs" c="dimmed" data-testid="render-versions">
            render {versions}
          </Text>
        ) : null}
      </Group>
      {diff.status === 'same' ? null : (
        <Code block fz={11} style={{ whiteSpace: 'pre', overflowX: 'auto', padding: 0 }}>
          {rows.map((r, i) =>
            r.t === 'fold' ? (
              <div key={i} style={{ padding: '0 8px', color: 'var(--mantine-color-dimmed)' }}>
                … {r.count} unchanged line{r.count === 1 ? '' : 's'}
              </div>
            ) : (
              <div key={i} data-diff={r.t} style={{ padding: '0 8px', background: DIFF_BG[r.t] }}>
                {r.t === 'add' ? '+ ' : r.t === 'del' ? '- ' : '  '}
                {r.text}
              </div>
            ),
          )}
        </Code>
      )}
    </Box>
  );
};

/** A changelog line concerns an output when it names it (as in VersionChip). */
const mentions = (line: string, outputId: string) => line.includes(outputId);

/** What a version says it changed in this output: the output itself, and which renders. */
function changedHere(v: ModuleVersion, outId: string): { output: boolean; renders: string[] } {
  const o = v.outputs.find((x) => x.id === outId);
  if (!o) return { output: false, renders: [] };
  return {
    output: o.version === v.version,
    renders: (o.renders ?? []).filter((r) => r.version === v.version).map((r) => r.index),
  };
}

const ModuleVersionsBody: React.FC<{
  g: CatalogGlobal;
  entry: OutputEntry;
  moduleVersion?: string | null;
  history: ModuleHistory;
  order: string[];
  theme?: string;
}> = ({ g, entry, moduleVersion, history, order, theme }) => {
  const { tone } = useCatalogPaper();
  const [compare, setCompare] = useState<string | null>(null);
  const outId = entry.output.id;
  const href = window.location.href;
  const dataBase = g.dataBase ?? 'data/';

  // The version on screen: the module's own when the index carries one; a migrated
  // slot may have none, so the entry whose `releases` lists this slot stands in.
  // Unknown when neither identifies it.
  const currentVersion: string | null = useMemo(() => {
    if (moduleVersion) return moduleVersion;
    const slotNow = currentSlot(window.location.pathname, order, g.version);
    if (!slotNow) return null;
    return history.versions.find((v) => v.releases.includes(slotNow))?.version ?? null;
  }, [moduleVersion, order, g.version, history.versions]);

  const compared: ModuleVersion | undefined = history.versions.find((v) => v.version === compare);
  const before = useMemo(
    () => (compared?.outputs.find((o) => o.id === outId)?.renders ?? []) as RenderLike[],
    [compared, outId],
  );
  const now = entry.renders as unknown as (RenderLike & { _version?: string })[];
  const diffs = useMemo(() => (compared ? diffRenders(before, now) : []), [compared, before, now]);
  const beforeVer = new Map(
    (compared?.outputs.find((o) => o.id === outId)?.renders ?? []).map((r) => [r.index, r.version]),
  );
  const nowVer = new Map(now.map((r) => [r.index, r._version]));
  const existed = Boolean(compared?.outputs.some((o) => o.id === outId));

  return (
    <Stack gap="md">
      {history.versions.map((v) => {
        const current = currentVersion !== null && v.version === currentVersion;
        const slot = pickSlot(v.releases, order);
        const has = v.outputs.some((o) => o.id === outId);
        const open = slot
          ? openInSlotHref(href, dataBase, slot, theme, has ? { output: outId } : { tool: history.id })
          : null;
        const changed = changedHere(v, outId);
        const log = v.changelog ?? [];
        return (
          <Box
            key={v.version}
            data-version={v.version}
            data-current={current || undefined}
            className="cp-hist-row"
          >
            <Group gap="sm" wrap="wrap" justify="space-between">
              <Group gap={8} wrap="wrap">
                <Code fz={12} fw={700} className="cp-out-id">
                  {v.version}
                </Code>
                {v.bump ? (
                  <BumpBadge bump={v.bump} />
                ) : (
                  <Badge size="xs" variant="outline" color="gray" radius="sm">
                    initial
                  </Badge>
                )}
                {current ? (
                  <Badge size="xs" variant="filled" color={tone} radius="sm">
                    viewing
                  </Badge>
                ) : null}
                <Text size="xs" c="dimmed">
                  {v.releases.length ? `shipped in ${v.releases.join(', ')}` : 'not shipped in a release'}
                  {v.date ? ` · ${v.date}` : ''}
                </Text>
              </Group>
              <Group gap={6} wrap="nowrap">
                {current || currentVersion === null ? null : (
                  <Button
                    size="compact-xs"
                    variant={compare === v.version ? 'filled' : 'light'}
                    color={compare === v.version ? tone : 'gray'}
                    leftSection={<FileDiff size={13} strokeWidth={1.8} aria-hidden />}
                    onClick={() => setCompare(compare === v.version ? null : v.version)}
                  >
                    Compare
                  </Button>
                )}
                {open && !current ? (
                  <Anchor href={open} size="xs">
                    Open in {slot}
                  </Anchor>
                ) : null}
              </Group>
            </Group>
            {!has ? (
              <Text size="xs" c="dimmed" mt={2}>
                No {outId} in this version.
              </Text>
            ) : changed.output || changed.renders.length ? (
              <Text size="xs" mt={2} data-testid="changed-here">
                Changed here: {changed.output ? 'this output' : ''}
                {changed.output && changed.renders.length ? ', ' : ''}
                {changed.renders.length
                  ? `render${changed.renders.length === 1 ? '' : 's'} ${changed.renders.join(', ')}`
                  : ''}
              </Text>
            ) : null}
            {log.length ? (
              <Box component="ul" className="cp-ver-changes" mt={4}>
                {[...log]
                  .sort((a, b) => Number(mentions(b, outId)) - Number(mentions(a, outId)))
                  .map((c) => (
                    <li key={c} data-mine={mentions(c, outId) || undefined}>
                      {c}
                    </li>
                  ))}
              </Box>
            ) : null}
          </Box>
        );
      })}

      {compared ? (
        <Box data-testid="yaml-diff">
          <Text size="xs" c="dimmed" mb={6}>
            {outId}: v{compared.version} (removed lines) →{' '}
            {currentVersion ? `v${currentVersion}` : 'this version'} (added lines)
            {existed ? '' : ` — the output did not exist in v${compared.version}`}
          </Text>
          <Stack gap="xs">
            {diffs.length ? (
              diffs.map((d) => (
                <DiffBlock
                  key={d.index}
                  diff={d}
                  from={beforeVer.get(d.index) ?? undefined}
                  to={nowVer.get(d.index) ?? undefined}
                />
              ))
            ) : (
              <Text size="xs" c="dimmed">
                No renders to compare.
              </Text>
            )}
          </Stack>
        </Box>
      ) : null}
    </Stack>
  );
};

/** The history in a modal, opened from the VersionChip. */
export const ModuleHistoryModal: React.FC<{
  opened: boolean;
  onClose: () => void;
  entry: OutputEntry;
  moduleVersion?: string | null;
  state: ModuleHistoryState;
  theme?: string;
}> = ({ opened, onClose, entry, moduleVersion, state, theme }) => {
  const g = window.__CATALOG_PREVIEW__ as unknown as CatalogGlobal | undefined;
  if (!g || !state.history) return null;
  const h = state.history;
  return (
    <Modal
      opened={opened}
      onClose={onClose}
      size="xl"
      title={
        <Stack gap={0}>
          <Text fw={700} size="sm">
            {h.name || h.id} — history across releases
          </Text>
          <Text size="xs" c="dimmed">
            {h.versions.length} version{h.versions.length === 1 ? '' : 's'} · seen from {entry.output.id}
          </Text>
        </Stack>
      }
    >
      <Box data-testid="module-history">
        <ModuleVersionsBody
          g={g}
          entry={entry}
          moduleVersion={moduleVersion}
          history={h}
          order={state.order}
          theme={theme}
        />
      </Box>
    </Modal>
  );
};
