/**
 * Standalone catalog-preview app: renders a catalog output's `renders_as` on its
 * fixture using the viewer's REAL `ComponentRenderer` (all component types), fed
 * from `window.__CATALOG_PREVIEW__` via the offline api shim (mockApi.ts).
 *
 * Around the components it shows provenance so the page isn't "blind": the
 * output's identity (nf-core / bio.tools / EDAM), find rule, recipe and fixture,
 * a per-component caption (what it's bound to), and a collapsible fixture-data
 * preview.
 */
import React, { useEffect, useState } from 'react';
import {
  Accordion,
  Alert,
  Anchor,
  Badge,
  Box,
  Code,
  Divider,
  Group,
  Image,
  Paper,
  SimpleGrid,
  Spoiler,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { AgGridReact } from 'ag-grid-react';
import { ComponentRenderer, bulkComputeCards } from 'depictio-react-core';
import type { StoredMetadata } from 'depictio-react-core';
import logoRaw from '../../public/logos/logo_black.svg?raw';

const LOGO_SRC = `data:image/svg+xml;utf8,${encodeURIComponent(logoRaw)}`;
const DASHBOARD_ID = 'catalog-preview';
const DEFAULT_HEIGHT: Record<string, number> = {
  figure: 540,
  map: 480,
  advanced_viz: 480,
  multiqc: 480,
  image: 480,
  table: 520,
};

interface OutputInfo {
  id: string;
  description?: string;
  mode?: string | null;
  find?: Record<string, unknown>;
  recipe?: string | null;
  fixture?: string | null;
  nf_core_url?: string | null;
  biotools_url?: string | null;
  edam?: string[];
  n_rows?: number;
  n_cols?: number;
  columns?: string[];
}
interface FixturePreview {
  columns: string[];
  rows: Record<string, unknown>[];
  total: number;
}

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

const OutputHeader: React.FC<{ out: OutputInfo; count: number }> = ({ out, count }) => (
  <>
    <Group justify="space-between" align="center">
      <Group gap="sm">
        <Image src={LOGO_SRC} h={32} w="auto" fit="contain" />
        <Divider orientation="vertical" />
        <Stack gap={0}>
          <Text size="xs" c="dimmed" fw={600}>
            Catalog preview
          </Text>
          <Title order={4}>{out.id}</Title>
        </Stack>
      </Group>
      <Badge variant="light" size="lg" color="blue">
        {count} component(s)
      </Badge>
    </Group>
    {out.description ? (
      <Text size="sm" c="dimmed" mt={6}>
        {out.description}
      </Text>
    ) : null}
  </>
);

const InfoRow: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <Group gap="xs" wrap="nowrap" align="baseline">
    <Text size="xs" fw={700} c="dimmed" style={{ minWidth: 92 }}>
      {label}
    </Text>
    <Box style={{ minWidth: 0 }}>{children}</Box>
  </Group>
);

const OutputInfoPanel: React.FC<{ out: OutputInfo }> = ({ out }) => {
  const edamShort = (url: string) => url.replace('http://edamontology.org/', '');
  return (
    <Paper withBorder radius="md" p="md" bg="var(--mantine-color-gray-0)">
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
          <InfoRow label="Recipe">
            <Code>{out.recipe}</Code>
          </InfoRow>
        ) : null}
        {out.find ? (
          <InfoRow label="Find">
            <Code>{JSON.stringify(out.find)}</Code>
          </InfoRow>
        ) : null}
        {out.nf_core_url || out.biotools_url || (out.edam && out.edam.length) ? (
          <InfoRow label="Identity">
            <Group gap="xs">
              {out.nf_core_url ? (
                <Anchor href={out.nf_core_url} target="_blank" size="xs">
                  nf-core
                </Anchor>
              ) : null}
              {out.biotools_url ? (
                <Anchor href={out.biotools_url} target="_blank" size="xs">
                  bio.tools
                </Anchor>
              ) : null}
              {(out.edam || []).map((u) => (
                <Anchor key={u} href={u} target="_blank" size="xs">
                  {edamShort(u)}
                </Anchor>
              ))}
            </Group>
          </InfoRow>
        ) : null}
      </Stack>
    </Paper>
  );
};

const FixturePreviewPanel: React.FC<{ fixture: FixturePreview }> = ({ fixture }) => (
  <Accordion variant="contained" chevronPosition="left" defaultValue="fixture">
    <Accordion.Item value="fixture">
      <Accordion.Control>
        <Text size="sm" fw={600}>
          Fixture data — first {fixture.rows.length} of {fixture.total} rows
        </Text>
      </Accordion.Control>
      <Accordion.Panel>
        <div className="ag-theme-alpine" style={{ height: 360, width: '100%' }}>
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

const CatalogPreviewApp: React.FC = () => {
  const g = window.__CATALOG_PREVIEW__;
  const out = g.output as unknown as OutputInfo;
  const fixture = (g as unknown as { fixturePreview?: FixturePreview }).fixturePreview;
  const renders = g.renders as StoredMetadata[];
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

  const info = (m: StoredMetadata) =>
    (m as Record<string, unknown>)._info as
      | { label?: string; bindings?: [string, string][] }
      | undefined;
  const codeOf = (m: StoredMetadata) => (m as Record<string, unknown>)._code as string | undefined;

  const cards = renders.filter((m) => m.component_type === 'card');
  const rest = renders.filter((m) => m.component_type !== 'card');

  return (
    <Box p="lg" style={{ maxWidth: 1200, margin: '0 auto' }}>
      <OutputHeader out={out} count={renders.length} />
      <Box mt="md">
        <OutputInfoPanel out={out} />
      </Box>
      <Divider my="lg" />

      <Stack gap="xl">
        {cards.length > 0 ? (
          <Stack gap="xs">
            <Text size="sm" fw={600} c="dimmed">
              Metrics
            </Text>
            <SimpleGrid cols={{ base: 1, xs: 2, sm: 3, md: 4 }} spacing="md">
              {cards.map((m) => (
                <Box key={m.index}>{renderOne(m)}</Box>
              ))}
            </SimpleGrid>
          </Stack>
        ) : null}

        {rest.map((m) => {
          const inf = info(m);
          const code = codeOf(m);
          const h =
            ((m as Record<string, unknown>)._preview_height as number) ||
            DEFAULT_HEIGHT[m.component_type];
          return (
            <Stack key={m.index} gap={6}>
              <Group gap={6} align="center">
                <Badge variant="light" color="grape" radius="sm">
                  {inf?.label || m.component_type}
                </Badge>
                {(inf?.bindings || []).map(([k, v]) => (
                  <Badge
                    key={k}
                    variant="default"
                    radius="sm"
                    size="sm"
                    leftSection={
                      <Text span fz={9} c="dimmed" fw={600}>
                        {k}
                      </Text>
                    }
                    styles={{ label: { textTransform: 'none', fontWeight: 600 } }}
                  >
                    {v}
                  </Badge>
                ))}
              </Group>
              {code ? (
                <Spoiler maxHeight={0} showLabel="Show code" hideLabel="Hide code" fz="xs">
                  <Code block fz="xs">
                    {code}
                  </Code>
                </Spoiler>
              ) : null}
              <Box style={{ height: h }}>{renderOne(m)}</Box>
            </Stack>
          );
        })}

        {fixture ? <FixturePreviewPanel fixture={fixture} /> : null}
      </Stack>
    </Box>
  );
};

export default CatalogPreviewApp;
