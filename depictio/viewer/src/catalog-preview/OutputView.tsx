/**
 * Detail view for one catalog output: renders its `renders_as` on the fixture
 * using the viewer's REAL `ComponentRenderer` (all component types), fed from the
 * merged `window.__CATALOG_PREVIEW__.data` via the offline api shim (mockApi.ts).
 *
 * Around the components it shows provenance so the page isn't "blind": the
 * output's identity (nf-core / bio.tools / EDAM), find rule, recipe and fixture,
 * each render's copyable `renders_as` YAML, and a collapsible fixture-data preview.
 * Styling mirrors the Depictio viewer (Card/ThemeIcon/Mantine tokens, no hex chrome).
 */
import React, { lazy, Suspense, useEffect, useState } from 'react';
import {
  Accordion,
  ActionIcon,
  Alert,
  Badge,
  Box,
  Button,
  Card,
  Center,
  Code,
  Collapse,
  Divider,
  Group,
  Image,
  Loader,
  Paper,
  Popover,
  Stack,
  Text,
  ThemeIcon,
  Title,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { ComponentRenderer, bulkComputeCards } from 'depictio-react-core';
import type { CatalogRender, StoredMetadata } from 'depictio-react-core';
import { buildTileSnippet } from '../catalog-shared/tileSnippet';
import {
  CATALOG_ACCENT,
  CopyYaml,
  DEFAULT_HEIGHT,
  PREVIEW_MAX_WIDTH,
  IdentityLink,
  InfoRow,
  TypeBadge,
  edamShort,
  lastSeg,
  logoFor,
  metaFor,
  nfCoreLabel,
  useCatalogPaper,
} from './shared';
import type { CatalogGlobal, FixturePreview, OutputEntry, OutputInfo } from './shared';
import ChunkErrorBoundary from './ChunkErrorBoundary';
import { ensureOutputLoaded, isLazy, isOutputLoaded } from './lazyOutput';
import CatalogHeader from './CatalogHeader';
import VersionChip from './VersionChip';

const DASHBOARD_ID = 'catalog-preview';

/** Keep one failing component from blanking the whole preview. */
class CellBoundary extends React.Component<
  { label: string; children: React.ReactNode },
  { error?: string }
> {
  state: { error?: string } = {};
  static getDerivedStateFromError(err: unknown) {
    return { error: err instanceof Error ? err.message : String(err) };
  }
  render() {
    if (this.state.error) {
      return (
        <Alert color="red" variant="light" title={`Render failed — ${this.props.label}`}>
          {this.state.error}
        </Alert>
      );
    }
    return this.props.children;
  }
}

const OutputInfoPanel: React.FC<{ out: OutputInfo }> = ({ out }) => (
  <Paper withBorder radius="md" p="md" bg="var(--mantine-color-default-hover)" className="cp-info">
    <Stack gap={6}>
      {out.fixture ? (
        <InfoRow label="Fixture">
          <Code>{out.fixture}</Code>{' '}
          <Text span size="xs" c="dimmed">
            ({out.n_rows} rows × {out.n_cols} cols)
          </Text>
        </InfoRow>
      ) : null}
      {out.recipe ? (
        <InfoRow label="Reshaped by">
          <Code>{out.recipe}</Code>
        </InfoRow>
      ) : null}
      {out.find && Object.keys(out.find).length ? (
        <InfoRow label="Recognised by">
          <Group gap={6} wrap="wrap">
            {Object.entries(out.find).map(([k, v]) => (
              <Code key={k}>
                {k}: {String(v)}
              </Code>
            ))}
          </Group>
        </InfoRow>
      ) : null}
      {out.nf_core_url || out.biotools_url || (out.edam && out.edam.length) ? (
        <InfoRow label="Identity" align="center">
          <Group gap="md" wrap="wrap">
            {out.nf_core_url ? (
              <IdentityLink
                href={out.nf_core_url}
                icon="simple-icons:nfcore"
                label={nfCoreLabel(out.nf_core_url)}
              />
            ) : null}
            {out.biotools_url ? (
              <IdentityLink
                href={out.biotools_url}
                icon="mdi:wrench-outline"
                label={`bio.tools: ${lastSeg(out.biotools_url)}`}
              />
            ) : null}
            {(out.edam || []).map((u) => (
              <IdentityLink key={u} href={u} icon="mdi:tag-outline" label={edamShort(u)} />
            ))}
          </Group>
        </InfoRow>
      ) : null}
    </Stack>
  </Paper>
);

// ag-grid is only needed once a fixture panel is shown — keep it off the first paint.
const FixtureGrid = lazy(() => import('./FixtureGrid'));

const FixturePreviewPanel: React.FC<{ fixture: FixturePreview; theme?: string }> = ({
  fixture,
  theme,
}) => {
  const { accentVar } = useCatalogPaper();
  return (
  <Accordion variant="separated" chevronPosition="left" radius="md" className="cp-fixture">
    <Accordion.Item value="fixture">
      <Accordion.Control
        icon={<Icon icon="mdi:table-large" width={18} color={accentVar} />}
      >
        <Text size="sm" fw={600}>
          Fixture data — first {fixture.rows.length} of {fixture.total} rows
        </Text>
      </Accordion.Control>
      <Accordion.Panel>
        <div
          className={theme === 'dark' ? 'ag-theme-alpine-dark' : 'ag-theme-alpine'}
          style={{ height: 360, width: '100%' }}
        >
          <ChunkErrorBoundary>
            <Suspense fallback={<Loader size="xs" m="md" />}>
              <FixtureGrid fixture={fixture} />
            </Suspense>
          </ChunkErrorBoundary>
        </div>
      </Accordion.Panel>
    </Accordion.Item>
  </Accordion>
  );
};

const CollapsibleBar: React.FC<{
  icon: string;
  label: React.ReactNode;
  chips?: React.ReactNode;
  children: React.ReactNode;
}> = ({ icon, label, chips, children }) => {
  const [open, setOpen] = useState(false);
  return (
    <Box
      style={{
        borderBottom: '1px solid var(--mantine-color-default-border)',
        flexShrink: 0,
        background: 'var(--mantine-color-default)',
      }}
    >
      <Group
        px="md"
        style={{ height: 34, cursor: 'pointer', userSelect: 'none' }}
        justify="space-between"
        wrap="nowrap"
        onClick={() => setOpen((v) => !v)}
      >
        <Group gap="xs" wrap="nowrap" style={{ minWidth: 0, overflow: 'hidden' }}>
          <Icon icon={icon} width={13} color="var(--mantine-color-dimmed)" style={{ flexShrink: 0 }} />
          <Text size="xs" fw={600} lineClamp={1} style={{ flexShrink: 0 }}>{label}</Text>
          {chips}
        </Group>
        <ActionIcon variant="subtle" color="gray" size="xs"
          onClick={(e) => { e.stopPropagation(); setOpen((v) => !v); }}
        >
          <Icon icon={open ? 'mdi:chevron-up' : 'mdi:chevron-down'} width={13} />
        </ActionIcon>
      </Group>
      <Collapse in={open}>
        <Box px="md" pb="sm" pt={2}>{children}</Box>
      </Collapse>
    </Box>
  );
};

const BareOutputView: React.FC<{
  target: StoredMetadata;
  renderOne: (m: StoredMetadata) => React.ReactNode;
  /** Pin the component to this pixel height instead of filling the viewport.
   *  The picker sends it for cards, whose iframe is taller than the tile so a
   *  metric tooltip has room; without the pin the card would simply grow into
   *  that room and the tooltip would be clipped again. */
  tileHeight?: number | null;
}> = ({ target, renderOne, tileHeight }) => {
  return (
    <Box
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100vh',
        boxSizing: 'border-box',
        background: tileHeight ? 'transparent' : undefined,
      }}
    >

      {/* No chrome. This view is what the builder's catalog picker embeds in an
        * iframe, and the panel around that iframe already names the output and
        * offers its provenance and binds behind a details popover. Two bars in
        * here restated it and cost ~70px of the preview the panel exists to show.
        * The full-page view (OutputView, used by `depictio catalog preview` and
        * the gallery) keeps its bars — nothing frames it there. */}

      {/* Component fills remaining height — same layout as a dashboard grid cell */}
      <Box
        style={{
          flex: tileHeight ? '0 0 auto' : 1,
          height: tileHeight ?? undefined,
          minHeight: 0,
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {renderOne(target)}
      </Box>

    </Box>
  );
};

// ---------------------------------------------------------------------------

const OutputView: React.FC<{
  entry: OutputEntry;
  onBack?: () => void;
  theme?: string;
  renderId?: string | null;
  tileHeight?: number | null;
  /** 'page' centres the detail in its own full-width document (the landing view
   *  of `catalog preview <id>`); 'pane' drops the centring and the branding for
   *  the split browser, where the chrome around it already supplies both. */
  variant?: 'page' | 'pane';
  /** Owning tool id — the first half of the `use:` handle. Not on OutputEntry
   *  (an output is listed under its tool), so the gallery passes it down. */
  toolId?: string;
}> = ({ entry, onBack, theme, renderId, tileHeight, variant = 'page', toolId }) => {
  const out = entry.output;
  const fixture = entry.fixturePreview;
  const renders = entry.renders as unknown as StoredMetadata[];
  const { paper, tone } = useCatalogPaper();
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [cardValues, setCardValues] = useState<Record<string, unknown>>({});
  const [cardSecondary, setCardSecondary] = useState<Record<string, Record<string, unknown>>>({});

  useEffect(() => {
    bulkComputeCards(DASHBOARD_ID, []).then((r) => {
      setCardValues(r.values as Record<string, unknown>);
      setCardSecondary((r.secondary_values || {}) as Record<string, Record<string, unknown>>);
    });
  }, []);

  const renderOne = (m: StoredMetadata) => {
    const rec = m as Record<string, unknown>;
    const note = rec._unsupported || rec._error;
    if (typeof note === 'string') {
      return (
        <Alert color="gray" variant="light" title={String(m.component_type)}>
          {note}
        </Alert>
      );
    }
    return (
      <CellBoundary label={String(m.component_type)}>
        <ChunkErrorBoundary>
          <ComponentRenderer
            metadata={m}
            filters={[]}
            dashboardId={DASHBOARD_ID}
            cardValue={cardValues[m.index]}
            cardSecondaryValues={cardSecondary[m.index]}
            cardLoading={false}
          />
        </ChunkErrorBoundary>
      </CellBoundary>
    );
  };

  // Bare mode: slim collapsible metadata header + full-height component.
  if (renderId) {
    const target = renders.find((m) => m.index === renderId) ?? renders[0];
    if (!target) return null;
    return (
      <BareOutputView target={target} renderOne={renderOne} tileHeight={tileHeight} />
    );
  }

  // Paper: a page of its own is one more Depictio page, the app's floating top
  // bar with a trail back to the catalogue, and the output in a paper pane.
  if (paper && variant === 'page') {
    return (
      <div className="gp-shell cp-shell" data-view="output">
        <CatalogHeader context={out.name || out.id} onHome={onBack} />
        <main className="gp-main cp-main">
          <div className="gp-page">
            <div className="cp-pane cp-page-pane">
              <OutputView entry={entry} theme={theme} variant="pane" toolId={toolId} />
            </div>
          </div>
        </main>
      </div>
    );
  }

  const cards = renders.filter((m) => m.component_type === 'card');
  const rest = renders.filter((m) => m.component_type !== 'card');

  const pane = variant === 'pane';

  // One render at a time, behind a switcher — the same shape as the builder's
  // "Pick from catalog" panel. The two surfaces render the SAME bundle (the
  // picker iframes this document with `#render_id=`), so showing every render
  // stacked here and one at a time there made one catalog look like two.
  const active = renders[selectedIdx] ?? renders[0];
  const activeHeight =
    ((active as Record<string, unknown> | undefined)?._preview_height as number) ||
    (active ? DEFAULT_HEIGHT[active.component_type] : 0) ||
    480;

  const snippetCtx = {
    toolId: toolId || out.id.split('_')[0],
    outputId: out.id,
    // No project here: the docs gallery is a catalogue, not a dashboard, so the
    // two binding lines are placeholders the reader fills in. Saying so beats
    // handing out a snippet that looks complete and resolves to nothing.
    dcTag: null,
    wfTag: null,
    title: out.name || out.id,
  };
  const activeRender = (active as Record<string, unknown> | undefined)?._render as
    | CatalogRender
    | undefined;
  const snippet = active && activeRender ? buildTileSnippet(snippetCtx, activeRender) : '';

  return (
    <Stack
      gap={0}
      h={pane ? '100%' : undefined}
      className="cp-out"
      data-variant={variant}
      style={{ minHeight: 0 }}
    >
      {/* Header — identity left, references right. Add / Edit are the builder's
          alone: there is no dashboard here to add to. */}
      <Group
        px={pane ? 'md' : 'lg'}
        py="xs"
        gap="sm"
        justify="space-between"
        wrap="nowrap"
        className="cp-out-head"
        style={{ borderBottom: '1px solid var(--mantine-color-default-border)', flexShrink: 0 }}
      >
        <Group gap="xs" wrap="nowrap" style={{ minWidth: 0 }}>
          {pane ? null : onBack ? (
            <Button
              size="xs"
              variant="subtle"
              color="gray"
              leftSection={<Icon icon="mdi:arrow-left" width={16} />}
              onClick={onBack}
            >
              Catalog
            </Button>
          ) : (
            <Image src={logoFor(theme)} h={24} w="auto" fit="contain" />
          )}
          <Text size="sm" fw={600} className="cp-out-title" style={{ flexShrink: 0 }}>
            {out.name || out.id}
          </Text>
          <Code fz={10} className="cp-out-id" style={{ flexShrink: 0 }}>
            {out.id}
          </Code>
          <VersionChip
            out={out}
            renderVersion={(active as Record<string, unknown> | undefined)?._version as
              | string
              | undefined}
            renderLabel={
              (active as Record<string, unknown> | undefined)?.title
                ? `“${String((active as Record<string, unknown>).title)}”`
                : undefined
            }
          />
          {out.description ? (
            <Text size="xs" c="dimmed" lineClamp={1} style={{ minWidth: 0 }}>
              {out.description}
            </Text>
          ) : null}
        </Group>

        <Group gap={6} wrap="nowrap" style={{ flexShrink: 0 }}>
          <Popover position="bottom-end" withArrow shadow="md" width={400}>
            <Popover.Target>
              <Tooltip label="Details" withArrow>
                <ActionIcon variant="subtle" color="gray" size="md" aria-label="Output details">
                  <Icon icon="mdi:information-outline" width={17} />
                </ActionIcon>
              </Tooltip>
            </Popover.Target>
            <Popover.Dropdown p="md">
              <Stack gap="sm">
                <Box>
                  <Text size="sm" fw={700} mb={4} style={{ lineHeight: 1.2 }}>
                    {out.name || out.id}
                  </Text>
                  {out.description ? (
                    <Text size="xs" c="dimmed" style={{ lineHeight: 1.45 }}>
                      {out.description}
                    </Text>
                  ) : null}
                  <Group gap={4} mt={6}>
                    {renders.map((m) => (
                      <TypeBadge key={m.index} type={m.component_type} size="xs" />
                    ))}
                  </Group>
                </Box>
                <OutputInfoPanel out={out} />
              </Stack>
            </Popover.Dropdown>
          </Popover>

          {snippet ? (
            <Popover position="bottom-end" withArrow shadow="md" width={430}>
              <Popover.Target>
                <Tooltip label="YAML reference" withArrow>
                  <ActionIcon
                    variant="subtle"
                    color={paper ? 'gray' : CATALOG_ACCENT}
                    size="md"
                    aria-label="Show use snippet"
                  >
                    <Icon icon="mdi:code-tags" width={17} />
                  </ActionIcon>
                </Tooltip>
              </Popover.Target>
              <Popover.Dropdown p="sm">
                <Stack gap={6}>
                  <Group justify="space-between" wrap="nowrap" gap="xs">
                    <Text size="xs" c="dimmed">
                      Paste under a dashboard&rsquo;s <Code fz={10}>components:</Code>
                    </Text>
                    <CopyYaml yaml={snippet} label="Copy" />
                  </Group>
                  <Code block fz={11} style={{ whiteSpace: 'pre', overflowX: 'auto' }}>
                    {snippet}
                  </Code>
                  <Text size="xs" c="dimmed">
                    Replace the bracketed tags with the workflow and data collection
                    this dashboard reads.
                  </Text>
                </Stack>
              </Popover.Dropdown>
            </Popover>
          ) : null}

          <Badge
            variant="light"
            size="sm"
            color={paper ? 'gray' : CATALOG_ACCENT}
            radius="sm"
            className="gp-tag-plain cp-count"
          >
            {renders.length} component{renders.length === 1 ? '' : 's'}
          </Badge>
        </Group>
      </Group>

      {/* Render switcher */}
      <Group
        px={pane ? 'md' : 'lg'}
        py={6}
        gap={4}
        wrap="wrap"
        className="cp-switch"
        style={{ borderBottom: '1px solid var(--mantine-color-default-border)', flexShrink: 0 }}
      >
        {renders.map((m, i) => {
          const meta = metaFor(m.component_type);
          const rec = m as Record<string, unknown>;
          const variantLabel = (rec._variant as string) || meta.name;
          const isActive = i === selectedIdx;
          return (
            <Button
              key={m.index}
              size="xs"
              variant={isActive ? 'light' : 'subtle'}
              // Paper: one neutral row of pills, the open render lit with the
              // accent; the type keeps its hue on its icon only.
              color={paper ? (isActive ? tone : 'gray') : meta.color}
              radius={paper ? 'xl' : undefined}
              data-active={isActive || undefined}
              leftSection={
                <Icon
                  icon={meta.icon}
                  width={13}
                  color={paper ? `var(--mantine-color-${meta.color}-6)` : undefined}
                />
              }
              onClick={() => setSelectedIdx(i)}
              styles={{
                root: { fontWeight: isActive ? 600 : 400, flexShrink: 0 },
                label: { lineHeight: 1.5, overflow: 'visible' },
              }}
            >
              {variantLabel}
            </Button>
          );
        })}
      </Group>

      {/* Preview */}
      <Box
        p={pane ? 'md' : 'lg'}
        className="cp-stage"
        style={pane ? { flex: 1, minHeight: 0, overflowY: 'auto' } : undefined}
      >
        {active ? (
          <>
            {/* Narrow types are centred in the pane rather than left against
                its edge: at a third of the width, hugging the left reads as a
                component that failed to fill its box. */}
            <Box
              h={activeHeight}
              maw={PREVIEW_MAX_WIDTH[active.component_type]}
              mx={PREVIEW_MAX_WIDTH[active.component_type] ? 'auto' : undefined}
              className="cp-frame"
            >
              {renderOne(active)}
            </Box>
            <Group gap={6} mt="xs" wrap="nowrap" className="cp-frame-foot">
              <Code fz={10} c="dimmed" className="cp-out-id">
                {active.index}
              </Code>
              <CopyYaml
                yaml={((active as Record<string, unknown>)._yaml as string) || ''}
                label="renders_as"
              />
            </Group>
          </>
        ) : null}
        {fixture ? (
          <Box mt="lg">
            <FixturePreviewPanel fixture={fixture} theme={theme} />
          </Box>
        ) : null}
      </Box>
    </Stack>
  );
};

/** Loads the output's payload first when running as the multi-file site
 *  (`g.lazyOutputs`); in the single-file bundle it is a pass-through. */
const LazyOutputView: React.FC<React.ComponentProps<typeof OutputView>> = (props) => {
  const g = window.__CATALOG_PREVIEW__ as unknown as CatalogGlobal | undefined;
  const id = props.entry.output.id;
  // ok:false outputs have no data file (the entry carries `error`): never fetch.
  const lazy = isLazy(g) && props.entry.ok !== false;
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<{ id: string; error?: string } | null>(
    !lazy || isOutputLoaded(id) ? { id } : null,
  );
  useEffect(() => {
    if (!lazy || !g || isOutputLoaded(id)) {
      setState({ id });
      return;
    }
    let cancelled = false;
    setState(null);
    ensureOutputLoaded(g, props.entry).then(
      () => !cancelled && setState({ id }),
      (e) => !cancelled && setState({ id, error: e instanceof Error ? e.message : String(e) }),
    );
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, lazy, attempt]);

  if (state === null || state.id !== id) {
    return (
      <Center h={props.variant === 'pane' ? '60%' : '100vh'} p="xl">
        <Stack align="center" gap="xs">
          <Loader size="sm" />
          <Text size="sm" c="dimmed">
            Loading {props.entry.output.name || id}…
          </Text>
        </Stack>
      </Center>
    );
  }
  if (state.error) {
    return (
      <Box p="lg">
        <Alert color="red" variant="light" title="Could not load this output">
          {state.error}
          <div>
            <Button size="xs" mt="xs" variant="light" color="red" onClick={() => setAttempt((n) => n + 1)}>
              Retry
            </Button>
          </div>
        </Alert>
      </Box>
    );
  }
  return <OutputView {...props} />;
};

export default LazyOutputView;
