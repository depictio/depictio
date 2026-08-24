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
import React, { useEffect, useState } from 'react';
import {
  Accordion,
  ActionIcon,
  Alert,
  Badge,
  Box,
  Button,
  Card,
  Code,
  Collapse,
  Divider,
  Group,
  Image,
  Paper,
  SimpleGrid,
  Stack,
  Text,
  ThemeIcon,
  Title,
} from '@mantine/core';
import { AgGridReact } from 'ag-grid-react';
import { Icon } from '@iconify/react';
import { ComponentRenderer, bulkComputeCards } from 'depictio-react-core';
import type { StoredMetadata } from 'depictio-react-core';
import {
  CATALOG_ACCENT,
  CopyYaml,
  DEFAULT_HEIGHT,
  IdentityLink,
  InfoRow,
  TypeBadge,
  allRendersYaml,
  edamShort,
  lastSeg,
  logoFor,
  metaFor,
  nfCoreLabel,
} from './shared';
import type { FixturePreview, OutputEntry, OutputInfo } from './shared';

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

const OutputHeader: React.FC<{
  out: OutputInfo;
  count: number;
  rendersYaml: string;
  logoSrc: string;
  onBack?: () => void;
}> = ({ out, count, rendersYaml, logoSrc, onBack }) => (
  <>
    <Group justify="space-between" align="center">
      <Group gap="sm">
        {onBack ? (
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
          <Image src={logoSrc} h={32} w="auto" fit="contain" />
        )}
        <Divider orientation="vertical" />
        <Stack gap={0}>
          <Text size="xs" c="dimmed" fw={600} tt="uppercase">
            Catalog preview
          </Text>
          <Title order={3}>{out.id}</Title>
        </Stack>
      </Group>
      <Group gap="sm">
        {rendersYaml ? (
          <CopyYaml yaml={rendersYaml} label="Copy all renders_as" variant="button" />
        ) : null}
        <Badge variant="light" size="lg" color={CATALOG_ACCENT} radius="sm">
          {count} component{count === 1 ? '' : 's'}
        </Badge>
      </Group>
    </Group>
    {out.description ? (
      <Text size="sm" c="dimmed" mt={6}>
        {out.description}
      </Text>
    ) : null}
  </>
);

const OutputInfoPanel: React.FC<{ out: OutputInfo }> = ({ out }) => (
  <Paper withBorder radius="md" p="md" bg="var(--mantine-color-default-hover)">
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
                icon="mdi:github"
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

const FixturePreviewPanel: React.FC<{ fixture: FixturePreview; theme?: string }> = ({
  fixture,
  theme,
}) => (
  <Accordion variant="separated" chevronPosition="left" radius="md">
    <Accordion.Item value="fixture">
      <Accordion.Control
        icon={
          <Icon icon="mdi:table-large" width={18} color={`var(--mantine-color-${CATALOG_ACCENT}-5)`} />
        }
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
          <AgGridReact
            rowData={fixture.rows}
            columnDefs={fixture.columns.map((c) => ({
              field: c,
              headerName: c,
              sortable: true,
              filter: true,
              resizable: true,
            }))}
            defaultColDef={{ flex: 1, minWidth: 110, resizable: true }}
            suppressFieldDotNotation
          />
        </div>
      </Accordion.Panel>
    </Accordion.Item>
  </Accordion>
);

/** Header for one rendered component: a large type identity (icon + name · variant),
 *  the referenceable id, and a clean YAML toggle + copy — replaces the old accordion. */
const ComponentCard: React.FC<{
  m: StoredMetadata;
  height: number;
  children: React.ReactNode;
}> = ({ m, height, children }) => {
  const rec = m as Record<string, unknown>;
  const yaml = rec._yaml as string | undefined;
  const variant = (rec._variant as string) || '';
  const binds = rec._binds as Record<string, string> | undefined;
  const meta = metaFor(m.component_type);
  const [showYaml, setShowYaml] = useState(false);

  return (
    <Card withBorder radius="md" shadow="sm" padding="md">
      <Group justify="space-between" wrap="nowrap" align="center" mb="sm">
        <Group gap="sm" wrap="nowrap" align="center" style={{ minWidth: 0 }}>
          <ThemeIcon size={42} radius="md" variant="light" color={meta.color}>
            <Icon icon={meta.icon} width={24} />
          </ThemeIcon>
          <Stack gap={0} style={{ minWidth: 0 }}>
            <Text fz="lg" fw={700} style={{ lineHeight: 1.2 }}>
              {meta.name}
              {variant ? (
                <Text span c="dimmed" fw={500}>
                  {' '}
                  · {variant}
                </Text>
              ) : null}
            </Text>
            <Code fz="xs" c="dimmed" bg="transparent" p={0}>
              {m.index}
            </Code>
          </Stack>
        </Group>
        {yaml ? (
          <Group gap={4} wrap="nowrap">
            <Button
              size="xs"
              variant={showYaml ? 'light' : 'subtle'}
              color="gray"
              leftSection={<Icon icon="mdi:code-braces" width={14} />}
              onClick={() => setShowYaml((v) => !v)}
            >
              renders_as
            </Button>
            <CopyYaml yaml={yaml} label="Copy renders_as YAML" />
          </Group>
        ) : null}
      </Group>
      {binds && Object.keys(binds).length ? (
        <Group gap={6} wrap="wrap" mb="sm">
          <Text size="xs" fw={700} c="dimmed" tt="uppercase">
            Binds
          </Text>
          {Object.entries(binds).map(([role, col]) => (
            <Badge key={role} size="sm" variant="light" color="gray" radius="sm" tt="none">
              {role} → {col}
            </Badge>
          ))}
        </Group>
      ) : null}
      {yaml ? (
        <Collapse in={showYaml}>
          <Code block fz="xs" mb="sm">
            {yaml}
          </Code>
        </Collapse>
      ) : null}
      <Box style={{ height }}>{children}</Box>
    </Card>
  );
};

// ---------------------------------------------------------------------------
// Bare mode: slim collapsible header + full-height component
// ---------------------------------------------------------------------------

/** One collapsible header bar — shared by the two bare-mode bars. */
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
}> = ({ entry, onBack, theme, renderId, tileHeight }) => {
  const out = entry.output;
  const fixture = entry.fixturePreview;
  const renders = entry.renders as unknown as StoredMetadata[];
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
        <ComponentRenderer
          metadata={m}
          filters={[]}
          dashboardId={DASHBOARD_ID}
          cardValue={cardValues[m.index]}
          cardSecondaryValues={cardSecondary[m.index]}
          cardLoading={false}
        />
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

  const cards = renders.filter((m) => m.component_type === 'card');
  const rest = renders.filter((m) => m.component_type !== 'card');
  const rendersYaml = allRendersYaml(entry.renders);

  return (
    <Box p="lg" style={{ maxWidth: 1200, margin: '0 auto' }}>
      <OutputHeader
        out={out}
        count={renders.length}
        rendersYaml={rendersYaml}
        logoSrc={logoFor(theme)}
        onBack={onBack}
      />
      <Box mt="md">
        <OutputInfoPanel out={out} />
      </Box>
      <Divider my="lg" />

      <Stack gap="xl">
        {cards.length > 0 ? (
          <Stack gap="xs">
            <Text size="sm" fw={700} c="dimmed" tt="uppercase">
              Metrics
            </Text>
            <SimpleGrid cols={{ base: 1, xs: 2, sm: 3, md: 4 }} spacing="md">
              {cards.map((m) => (
                <Stack key={m.index} gap={4}>
                  <Box>{renderOne(m)}</Box>
                  <Group gap={6} justify="center" wrap="nowrap">
                    <TypeBadge type={m.component_type} size="xs" />
                    <Code fz={10} c="dimmed">
                      {m.index}
                    </Code>
                  </Group>
                </Stack>
              ))}
            </SimpleGrid>
          </Stack>
        ) : null}

        {rest.map((m) => {
          const h =
            ((m as Record<string, unknown>)._preview_height as number) ||
            DEFAULT_HEIGHT[m.component_type] ||
            480;
          return (
            <ComponentCard key={m.index} m={m} height={h}>
              {renderOne(m)}
            </ComponentCard>
          );
        })}

        {fixture ? <FixturePreviewPanel fixture={fixture} theme={theme} /> : null}
      </Stack>
    </Box>
  );
};

export default OutputView;
