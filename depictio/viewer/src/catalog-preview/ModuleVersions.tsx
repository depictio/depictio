/**
 * "Versions" section of an output (site build only): the history of the module
 * that owns it, from `../modules/<tool>.json`, with an "Open in vX.Y.Z" link per
 * version and a line diff of the output's render YAML against the version shown.
 *
 * The section is absent, with no message, when the history cannot be loaded (a
 * bare export, a 404, a network error).
 */
import React, { useEffect, useMemo, useState } from 'react';
import { Accordion, Anchor, Badge, Box, Button, Code, Group, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';
import { CATALOG_ACCENT } from './shared';
import type { CatalogGlobal, OutputEntry } from './shared';
import { diffRenders, foldUnchanged } from './lineDiff';
import type { RenderDiff, RenderLike } from './lineDiff';
import { fetchModule, fetchVersions } from './siteData';
import type { Bump, ModuleHistory, ModuleVersion } from './siteData';
import { openInSlotHref, pickSlot } from './siteTree';

export const BUMP_COLOR: Record<string, string> = { major: 'red', minor: 'blue', patch: 'gray' };

export const BumpBadge: React.FC<{ bump?: Bump }> = ({ bump }) =>
  bump ? (
    <Badge size="xs" variant="light" color={BUMP_COLOR[bump] ?? 'gray'} radius="sm">
      {bump}
    </Badge>
  ) : null;

/** The module's history, or null while loading / when unavailable. */
function useModuleHistory(g: CatalogGlobal | undefined, toolId?: string) {
  const [state, setState] = useState<{
    history: ModuleHistory | null;
    order: string[];
  } | null>(null);
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
        setState({
          history,
          order: versions ? [versions.latest || 'latest', ...versions.versions] : ['latest'],
        });
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

const DiffBlock: React.FC<{ diff: RenderDiff }> = ({ diff }) => {
  const rows = useMemo(() => foldUnchanged(diff.ops, 3), [diff.ops]);
  const statusColor = { same: 'gray', changed: 'yellow', added: 'green', removed: 'red' }[diff.status];
  return (
    <Box>
      <Group gap={6} mb={4}>
        <Code fz={10}>{diff.index}</Code>
        <Badge size="xs" variant="light" color={statusColor} radius="sm">
          {diff.status === 'same' ? 'unchanged' : diff.status}
        </Badge>
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

const ModuleVersionsBody: React.FC<{
  g: CatalogGlobal;
  entry: OutputEntry;
  toolVersion?: string;
  history: ModuleHistory;
  order: string[];
  theme?: string;
}> = ({ g, entry, toolVersion, history, order, theme }) => {
  const [compare, setCompare] = useState<string | null>(null);
  const outId = entry.output.id;
  const href = window.location.href;
  const dataBase = g.dataBase ?? 'data/';

  const compared: ModuleVersion | undefined = history.versions.find((v) => v.version === compare);
  const diffs = useMemo(() => {
    if (!compared) return [];
    const before = (compared.outputs.find((o) => o.id === outId)?.renders ?? []) as RenderLike[];
    const now = entry.renders as unknown as RenderLike[];
    return diffRenders(before, now);
  }, [compared, outId, entry.renders]);
  const existed = Boolean(compared?.outputs.some((o) => o.id === outId));

  return (
    <Stack gap="sm">
      {history.versions.map((v) => {
        const current = v.version === toolVersion;
        const slot = pickSlot(v.releases, order);
        const has = v.outputs.some((o) => o.id === outId);
        const open = slot
          ? openInSlotHref(href, dataBase, slot, theme, has ? { output: outId } : { tool: history.id })
          : null;
        return (
          <Group
            key={v.version}
            gap="sm"
            wrap="wrap"
            justify="space-between"
            data-version={v.version}
            style={{
              borderLeft: `3px solid ${current ? `var(--mantine-color-${CATALOG_ACCENT}-5)` : 'transparent'}`,
              paddingLeft: 8,
            }}
          >
            <Group gap={8} wrap="wrap">
              <Text size="sm" fw={600}>
                v{v.version}
              </Text>
              {v.bump ? <BumpBadge bump={v.bump} /> : (
                <Badge size="xs" variant="outline" color="gray" radius="sm">initial</Badge>
              )}
              {current ? (
                <Badge size="xs" variant="filled" color={CATALOG_ACCENT} radius="sm">
                  viewing
                </Badge>
              ) : null}
              <Text size="xs" c="dimmed">
                {v.releases.length ? `shipped in ${v.releases.join(', ')}` : 'not shipped in a release'}
              </Text>
              {!has ? (
                <Text size="xs" c="dimmed">
                  · no {outId} in this version
                </Text>
              ) : null}
            </Group>
            <Group gap={6} wrap="nowrap">
              {current ? null : (
                <Button
                  size="compact-xs"
                  variant={compare === v.version ? 'filled' : 'light'}
                  color="gray"
                  leftSection={<Icon icon="mdi:file-compare" width={13} />}
                  onClick={() => setCompare(compare === v.version ? null : v.version)}
                >
                  Compare with this version
                </Button>
              )}
              {open && !current ? (
                <Anchor href={open} size="xs">
                  Open in v{v.version}
                </Anchor>
              ) : null}
            </Group>
          </Group>
        );
      })}

      {compared ? (
        <Box data-testid="yaml-diff">
          <Text size="xs" c="dimmed" mb={6}>
            {outId}: v{compared.version} (removed lines) → {toolVersion ? `v${toolVersion}` : 'this version'}{' '}
            (added lines)
            {existed ? '' : ' — the output did not exist in v' + compared.version}
          </Text>
          <Stack gap="xs">
            {diffs.length ? (
              diffs.map((d) => <DiffBlock key={d.index} diff={d} />)
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

const ModuleVersions: React.FC<{
  entry: OutputEntry;
  toolId?: string;
  toolVersion?: string;
  theme?: string;
}> = ({ entry, toolId, toolVersion, theme }) => {
  const g = window.__CATALOG_PREVIEW__ as unknown as CatalogGlobal | undefined;
  const state = useModuleHistory(g, toolId);
  if (!g || !state?.history) return null;
  return (
    <Accordion variant="separated" chevronPosition="left" radius="md" mt="lg">
      <Accordion.Item value="versions">
        <Accordion.Control
          icon={
            <Icon icon="mdi:history" width={18} color={`var(--mantine-color-${CATALOG_ACCENT}-5)`} />
          }
        >
          <Text size="sm" fw={600}>
            Versions — {state.history.name || state.history.id} ({state.history.versions.length})
          </Text>
        </Accordion.Control>
        <Accordion.Panel>
          <ModuleVersionsBody
            g={g}
            entry={entry}
            toolVersion={toolVersion}
            history={state.history}
            order={state.order}
            theme={theme}
          />
        </Accordion.Panel>
      </Accordion.Item>
    </Accordion>
  );
};

export default ModuleVersions;
