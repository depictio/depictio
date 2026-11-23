import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Badge,
  Box,
  Button,
  Group,
  Loader,
  NumberInput,
  SegmentedControl,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Title,
  DEFAULT_THEME,
  useComputedColorScheme,
} from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import { Icon } from '@iconify/react';
import Plot from 'react-plotly.js';
import { DepictioCard } from 'depictio-components';
import {
  CARD_FRAME,
  FigureHeader,
  fetchUsageCsv,
  fetchUsageReport,
  figurePlotConfig,
  type UsageGranularity,
  type UsageQuery,
  type UsageReport,
} from 'depictio-react-core';
import { mantinePlotlyTemplate } from '../static-runtime/mantinePlotlyTemplate';

/**
 * Admin › Activity › Usage: internal usage statistics (`GET /analytics/usage`).
 *
 * Mode-aware: an instance with accounts leads with users and logins, a public
 * one with visitors and addresses, a single-user one with visits only. Every
 * number is the one the API returns, so an agent reading the API and an admin
 * reading this page see the same thing.
 */

const DEFAULT_PERIODS: Record<UsageGranularity, number> = { day: 30, week: 12, month: 12, year: 5 };
const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

type KpiDef = { key: string; label: string; icon: string; color: string; suffix?: string };

const KPIS: Record<UsageReport['mode'], KpiDef[]> = {
  multi_user: [
    { key: 'active_users', label: 'Active users', icon: 'mdi:account-group', color: 'blue' },
    { key: 'logins', label: 'Logins', icon: 'mdi:login', color: 'teal' },
    { key: 'signups', label: 'New accounts', icon: 'mdi:account-plus', color: 'grape' },
    { key: 'returning_users_pct', label: 'Returning users', suffix: '%', icon: 'mdi:account-convert', color: 'orange' },
    { key: 'dashboard_views', label: 'Dashboard views', icon: 'mdi:view-dashboard', color: 'indigo' },
    { key: 'visitors', label: 'Browsers', icon: 'mdi:web', color: 'cyan' },
  ],
  public: [
    { key: 'visitors', label: 'Visitors', icon: 'mdi:web', color: 'cyan' },
    { key: 'unique_ips', label: 'Unique IPs', icon: 'mdi:ip-network', color: 'violet' },
    { key: 'pageviews', label: 'Page views', icon: 'mdi:eye', color: 'green' },
    { key: 'dashboard_views', label: 'Dashboard views', icon: 'mdi:view-dashboard', color: 'indigo' },
    { key: 'countries', label: 'Countries', icon: 'mdi:earth', color: 'pink' },
    { key: 'logins', label: 'Sign-ins', icon: 'mdi:login', color: 'teal' },
  ],
  single_user: [
    { key: 'pageviews', label: 'Page views', icon: 'mdi:eye', color: 'green' },
    { key: 'dashboard_views', label: 'Dashboard views', icon: 'mdi:view-dashboard', color: 'indigo' },
    { key: 'visitors', label: 'Browsers', icon: 'mdi:web', color: 'cyan' },
    { key: 'logins', label: 'Sessions opened', icon: 'mdi:login', color: 'teal' },
  ],
};

const regionNames = (() => {
  try {
    return new Intl.DisplayNames(['en'], { type: 'region' });
  } catch {
    return null;
  }
})();
const countryName = (code: string) => regionNames?.of(code) ?? code;

function fmtPeriod(iso: string, g: UsageGranularity): string {
  const d = new Date(`${iso}Z`);
  if (g === 'year') return String(d.getUTCFullYear());
  if (g === 'month')
    return d.toLocaleDateString(undefined, { month: 'short', year: '2-digit', timeZone: 'UTC' });
  return d.toLocaleDateString(undefined, { day: '2-digit', month: 'short', timeZone: 'UTC' });
}

const toIsoDay = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

/** A metric tile: the dashboards' own card, with the previous period beneath. */
const Kpi: React.FC<{ def: KpiDef; current: number; previous: number }> = ({
  def,
  current,
  previous,
}) => {
  const delta = previous ? Math.round(((current - previous) / previous) * 100) : null;
  let trend = `previous period: ${previous.toLocaleString()}`;
  if (def.suffix) trend = 'of active users, seen before this range';
  else if (delta !== null)
    trend = `${delta >= 0 ? '▲' : '▼'} ${Math.abs(delta)}% vs previous (${previous.toLocaleString()})`;
  return (
    <Box h={118}>
      <DepictioCard
        title={def.label}
        value={`${current.toLocaleString()}${def.suffix ?? ''}`}
        icon_name={def.icon}
        icon_color={def.color}
        icon_style="watermark"
        title_font_size="sm"
        value_font_size="xl"
        aggregation_description={trend}
      />
    </Box>
  );
};

/** A figure/table tile: the metric card's frame + the dashboards' minimal figure header. */
const Tile: React.FC<{
  title: string;
  subtitle?: string;
  icon: string;
  color?: string;
  children: React.ReactNode;
}> = ({ title, subtitle, icon, color, children }) => (
  <Box style={CARD_FRAME} p="sm">
    <FigureHeader title={title} subtitle={subtitle} icon={icon} iconColor={color} />
    {children}
  </Box>
);

const MiniTable: React.FC<{
  title: string;
  icon: string;
  rows: Array<Record<string, string | number>>;
  columns: Array<{ key: string; label: string; render?: (v: string | number) => React.ReactNode }>;
  empty?: string;
}> = ({ title, icon, rows, columns, empty = 'No data for this period.' }) => (
  <Tile title={title} icon={icon} color="gray">
    {rows.length === 0 ? (
      <Text size="xs" c="dimmed">
        {empty}
      </Text>
    ) : (
      <Table striped highlightOnHover verticalSpacing={4} fz="xs">
        <Table.Thead>
          <Table.Tr>
            {columns.map((c) => (
              <Table.Th key={c.key}>{c.label}</Table.Th>
            ))}
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.slice(0, 10).map((r, i) => (
            <Table.Tr key={i}>
              {columns.map((c) => (
                <Table.Td key={c.key}>{c.render ? c.render(r[c.key]) : r[c.key]}</Table.Td>
              ))}
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    )}
  </Tile>
);

export const UsagePane: React.FC = () => {
  const scheme = useComputedColorScheme('light');
  const template = useMemo(() => mantinePlotlyTemplate(scheme), [scheme]);
  // One hue, from the body colour up to the brand blue: a heatmap of counts
  // reads as "more", never as a diverging scale.
  const heatScale = useMemo((): Array<[number, string]> => {
    const blue = DEFAULT_THEME.colors.blue;
    const low = scheme === 'dark' ? DEFAULT_THEME.colors.dark[6] : blue[0];
    return [
      [0, low],
      [0.5, blue[scheme === 'dark' ? 7 : 3]],
      [1, blue[scheme === 'dark' ? 4 : 7]],
    ];
  }, [scheme]);
  const [granularity, setGranularity] = useState<UsageGranularity>('month');
  const [periods, setPeriods] = useState<number>(DEFAULT_PERIODS.month);
  const [range, setRange] = useState<[Date | null, Date | null]>([null, null]);
  const [report, setReport] = useState<UsageReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const query: UsageQuery = useMemo(() => {
    const [s, e] = range;
    return s && e
      ? { granularity, start: toIsoDay(s), end: toIsoDay(e) }
      : { granularity, periods };
  }, [granularity, periods, range]);

  const load = useCallback(() => {
    setLoading(true);
    fetchUsageReport(query)
      .then((r) => {
        setReport(r);
        setError(null);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [query]);

  useEffect(load, [load]);

  const downloadCsv = useCallback(() => {
    void fetchUsageCsv(query).then((text) => {
      const url = URL.createObjectURL(new Blob([text], { type: 'text/csv' }));
      const a = document.createElement('a');
      a.href = url;
      a.download = `depictio-usage-${granularity}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    });
  }, [query, granularity]);

  const x = report?.series.map((p) => fmtPeriod(p.period_start, report.granularity)) ?? [];
  const isPublic = report?.mode === 'public';
  const plotLayout = (extra: Record<string, unknown> = {}) => ({
    template,
    autosize: true,
    height: 260,
    margin: { l: 40, r: 10, t: 10, b: 40 },
    legend: { orientation: 'h' as const, y: -0.2 },
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    ...extra,
  });
  const plotConfig = figurePlotConfig('minimal');
  const b = report?.breakdowns ?? {};

  return (
    <Stack gap="md">
      <Group justify="space-between" wrap="wrap" gap="sm">
        <Group gap="xs">
          <Title order={6}>Usage</Title>
          {loading && <Loader size="xs" />}
          {report && (
            <Badge variant="light" size="sm">
              {report.mode.replace('_', '-')}
            </Badge>
          )}
          <Badge variant="outline" color="gray" size="sm">
            UTC
          </Badge>
        </Group>
        <Group gap="xs" wrap="wrap">
          <SegmentedControl
            size="xs"
            value={granularity}
            onChange={(v) => {
              const g = v as UsageGranularity;
              setGranularity(g);
              setPeriods(DEFAULT_PERIODS[g]);
            }}
            data={[
              { value: 'week', label: 'Week' },
              { value: 'month', label: 'Month' },
              { value: 'year', label: 'Year' },
            ]}
          />
          <NumberInput
            size="xs"
            w={80}
            min={1}
            max={120}
            value={periods}
            disabled={Boolean(range[0] && range[1])}
            onChange={(v) => setPeriods(Number(v) || 1)}
            aria-label="Number of periods"
          />
          <DatePickerInput
            size="xs"
            type="range"
            clearable
            placeholder="Custom range"
            value={range}
            onChange={setRange}
            w={220}
          />
          <Button
            size="xs"
            variant="default"
            leftSection={<Icon icon="mdi:download" width={14} />}
            onClick={downloadCsv}
          >
            CSV
          </Button>
          <Button size="xs" variant="subtle" onClick={load} aria-label="Refresh">
            <Icon icon="mdi:refresh" width={16} />
          </Button>
        </Group>
      </Group>

      {error && (
        <Alert color="red" variant="light">
          {error}
        </Alert>
      )}
      {report && !report.geoip_available && (
        <Text size="xs" c="dimmed">
          Countries and cities are off: set DEPICTIO_USAGE_STATS_GEOIP_DB_PATH to a DB-IP Lite
          City .mmdb file.
        </Text>
      )}

      {report && (
        <>
          <SimpleGrid cols={{ base: 2, sm: 3, lg: 6 }} spacing="sm">
            {KPIS[report.mode].map((k) => (
              <Kpi
                key={k.key}
                def={k}
                current={report.kpis[k.key]?.current ?? 0}
                previous={report.kpis[k.key]?.previous ?? 0}
              />
            ))}
          </SimpleGrid>
          <Group gap="lg">
            {Object.entries(report.totals).map(([k, v]) => (
              <Text key={k} size="xs" c="dimmed">
                {k.replace('_', ' ')}: <b>{v.toLocaleString()}</b>
              </Text>
            ))}
          </Group>

          <SimpleGrid cols={{ base: 1, md: 2 }} spacing="sm">
            <Tile
              title="Activity"
              subtitle={isPublic ? 'visitors, sign-ins, dashboard views' : 'active users, logins, dashboard views'}
              icon="mdi:chart-timeline-variant"
              color="blue"
            >
              <Plot
                style={{ width: '100%' }}
                useResizeHandler
                config={plotConfig}
                layout={plotLayout()}
                data={[
                  isPublic
                    ? { type: 'bar', name: 'Visitors', x, y: report.series.map((p) => p.visitors) }
                    : { type: 'bar', name: 'Active users', x, y: report.series.map((p) => p.active_users) },
                  { type: 'scatter', mode: 'lines+markers', name: 'Logins', x, y: report.series.map((p) => p.logins) },
                  {
                    type: 'scatter',
                    mode: 'lines+markers',
                    name: 'Dashboard views',
                    x,
                    y: report.series.map((p) => p.dashboard_views),
                  },
                ]}
              />
            </Tile>
            <Tile
              title={isPublic ? 'New vs returning visitors' : 'New vs returning users'}
              subtitle="first seen in the period, or seen before"
              icon="mdi:account-convert"
              color="orange"
            >
              <Plot
                style={{ width: '100%' }}
                useResizeHandler
                config={plotConfig}
                layout={plotLayout({ barmode: 'stack' })}
                data={
                  isPublic
                    ? [
                        {
                          type: 'bar',
                          name: 'New',
                          x,
                          y: report.series.map((p) => p.new_visitors),
                          marker: { color: DEFAULT_THEME.colors.teal[6] },
                        },
                        {
                          type: 'bar',
                          name: 'Returning',
                          x,
                          y: report.series.map((p) => p.returning_visitors),
                          marker: { color: DEFAULT_THEME.colors.blue[6] },
                        },
                      ]
                    : [
                        {
                          type: 'bar',
                          name: 'New',
                          x,
                          y: report.series.map((p) => p.new_users),
                          marker: { color: DEFAULT_THEME.colors.teal[6] },
                        },
                        {
                          type: 'bar',
                          name: 'Returning',
                          x,
                          y: report.series.map((p) => p.returning_users),
                          marker: { color: DEFAULT_THEME.colors.blue[6] },
                        },
                      ]
                }
              />
            </Tile>
            <Tile
              title="Content created"
              subtitle="accounts, projects, dashboards, ingestions"
              icon="mdi:folder-plus"
              color="grape"
            >
              <Plot
                style={{ width: '100%' }}
                useResizeHandler
                config={plotConfig}
                layout={plotLayout({ barmode: 'group' })}
                data={[
                  { type: 'bar', name: 'Accounts', x, y: report.series.map((p) => p.signups) },
                  { type: 'bar', name: 'Projects', x, y: report.series.map((p) => p.new_projects) },
                  { type: 'bar', name: 'Dashboards', x, y: report.series.map((p) => p.new_dashboards) },
                  { type: 'bar', name: 'Ingestions', x, y: report.series.map((p) => p.ingestions) },
                ]}
              />
            </Tile>
            <Tile
              title="When"
              subtitle="page views, weekday × hour (UTC)"
              icon="mdi:calendar-clock"
              color="teal"
            >
              <Plot
                style={{ width: '100%' }}
                useResizeHandler
                config={plotConfig}
                layout={plotLayout({ yaxis: { autorange: 'reversed' } })}
                data={[
                  {
                    type: 'heatmap',
                    z: report.hours_heatmap,
                    y: WEEKDAYS,
                    x: Array.from({ length: 24 }, (_, h) => `${h}h`),
                    showscale: false,
                    colorscale: heatScale,
                    xgap: 2,
                    ygap: 2,
                  },
                ]}
              />
            </Tile>
          </SimpleGrid>

          {report.geoip_available && (
            <Tile title="Visitors by country" icon="mdi:earth" color="pink">
              <Plot
                style={{ width: '100%' }}
                useResizeHandler
                config={plotConfig}
                layout={plotLayout({
                  height: 320,
                  margin: { l: 0, r: 0, t: 0, b: 0 },
                  geo: { showframe: false, bgcolor: 'rgba(0,0,0,0)', projection: { type: 'natural earth' } },
                })}
                data={[
                  {
                    type: 'choropleth',
                    locationmode: 'country names',
                    colorscale: heatScale,
                    marker: { line: { width: 0.5, color: 'rgba(128,128,128,0.4)' } },
                    locations: (b.countries ?? []).map((c) => countryName(String(c.country))),
                    z: (b.countries ?? []).map((c) => Number(c.visitors)),
                    showscale: false,
                  },
                ]}
              />
            </Tile>
          )}

          <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} spacing="sm">
            <MiniTable
              title="Top dashboards"
              icon="mdi:view-dashboard"
              rows={b.top_dashboards ?? []}
              columns={[
                {
                  key: 'title',
                  label: 'Dashboard',
                  render: (v) => String(v),
                },
                { key: 'project', label: 'Project' },
                { key: 'views', label: 'Views' },
                { key: 'visitors', label: 'Visitors' },
              ]}
            />
            <MiniTable
              title="Top projects"
              icon="mdi:folder"
              rows={b.top_projects ?? []}
              columns={[
                { key: 'name', label: 'Project' },
                { key: 'views', label: 'Dashboard views' },
              ]}
            />
            <MiniTable
              title="Login methods"
              icon="mdi:login"
              rows={b.login_methods ?? []}
              columns={[
                { key: 'method', label: 'Method' },
                { key: 'logins', label: 'Logins' },
              ]}
            />
            {report.geoip_available && (
              <MiniTable
                title="Countries"
                icon="mdi:flag"
                rows={b.countries ?? []}
                columns={[
                  { key: 'country', label: 'Country', render: (v) => countryName(String(v)) },
                  { key: 'visitors', label: 'Visitors' },
                ]}
              />
            )}
            {report.geoip_available && (
              <MiniTable
                title="Cities"
                icon="mdi:city"
                rows={b.cities ?? []}
                columns={[
                  { key: 'city', label: 'City' },
                  { key: 'country', label: 'Country' },
                  { key: 'visitors', label: 'Visitors' },
                ]}
              />
            )}
            <MiniTable
              title="Browsers"
              icon="mdi:web"
              rows={b.browsers ?? []}
              columns={[
                { key: 'name', label: 'Browser' },
                { key: 'visitors', label: 'Visitors' },
              ]}
            />
            <MiniTable
              title="Operating systems"
              icon="mdi:monitor"
              rows={b.os ?? []}
              columns={[
                { key: 'name', label: 'OS' },
                { key: 'visitors', label: 'Visitors' },
              ]}
            />
            <MiniTable
              title="Devices"
              icon="mdi:cellphone-link"
              rows={b.devices ?? []}
              columns={[
                { key: 'name', label: 'Device' },
                { key: 'visitors', label: 'Visitors' },
              ]}
            />
            <MiniTable
              title="Languages"
              icon="mdi:translate"
              rows={b.languages ?? []}
              columns={[
                { key: 'name', label: 'Language' },
                { key: 'visitors', label: 'Visitors' },
              ]}
            />
            <MiniTable
              title="Referrers"
              icon="mdi:link-variant"
              rows={b.referrers ?? []}
              columns={[
                { key: 'domain', label: 'Domain' },
                { key: 'visits', label: 'Visits' },
              ]}
            />
            <MiniTable
              title="Browsers per address (shared NAT)"
              icon="mdi:lan"
              rows={b.visitors_per_ip ?? []}
              empty="No address seen yet."
              columns={[
                { key: 'ip_hash', label: 'Address (hashed)', render: (v) => String(v).slice(0, 8) },
                { key: 'visitors', label: 'Browsers' },
              ]}
            />
          </SimpleGrid>
        </>
      )}
    </Stack>
  );
};

export default UsagePane;
