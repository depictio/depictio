import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  NumberInput,
  SegmentedControl,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Title,
  useComputedColorScheme,
} from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import { Icon } from '@iconify/react';
import Plot from 'react-plotly.js';
import {
  fetchUsageCsv,
  fetchUsageReport,
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

type KpiDef = { key: string; label: string; suffix?: string };

const KPIS: Record<UsageReport['mode'], KpiDef[]> = {
  multi_user: [
    { key: 'active_users', label: 'Active users' },
    { key: 'logins', label: 'Logins' },
    { key: 'signups', label: 'New accounts' },
    { key: 'returning_users_pct', label: 'Returning users', suffix: '%' },
    { key: 'dashboard_views', label: 'Dashboard views' },
    { key: 'visitors', label: 'Browsers' },
  ],
  public: [
    { key: 'visitors', label: 'Visitors' },
    { key: 'unique_ips', label: 'Unique IPs' },
    { key: 'pageviews', label: 'Page views' },
    { key: 'dashboard_views', label: 'Dashboard views' },
    { key: 'countries', label: 'Countries' },
    { key: 'logins', label: 'Sign-ins' },
  ],
  single_user: [
    { key: 'pageviews', label: 'Page views' },
    { key: 'dashboard_views', label: 'Dashboard views' },
    { key: 'visitors', label: 'Browsers' },
    { key: 'logins', label: 'Sessions opened' },
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
  if (g === 'month') return d.toLocaleDateString(undefined, { month: 'short', year: 'numeric', timeZone: 'UTC' });
  return d.toLocaleDateString(undefined, { day: '2-digit', month: 'short', timeZone: 'UTC' });
}

const toIsoDay = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

const Kpi: React.FC<{ label: string; current: number; previous: number; suffix?: string }> = ({
  label,
  current,
  previous,
  suffix,
}) => {
  const delta = previous ? Math.round(((current - previous) / previous) * 100) : null;
  return (
    <Card withBorder radius="md" p="sm">
      <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
        {label}
      </Text>
      <Group gap="xs" align="baseline">
        <Text fz={26} fw={700}>
          {current.toLocaleString()}
          {suffix}
        </Text>
        {delta !== null && !suffix && (
          <Text size="xs" fw={600} c={delta >= 0 ? 'teal' : 'red'}>
            {delta >= 0 ? '▲' : '▼'} {Math.abs(delta)}%
          </Text>
        )}
      </Group>
      {!suffix && (
        <Text size="xs" c="dimmed">
          previous period: {previous.toLocaleString()}
        </Text>
      )}
    </Card>
  );
};

const MiniTable: React.FC<{
  title: string;
  rows: Array<Record<string, string | number>>;
  columns: Array<{ key: string; label: string; render?: (v: string | number) => React.ReactNode }>;
  empty?: string;
}> = ({ title, rows, columns, empty = 'No data for this period.' }) => (
  <Card withBorder radius="md" p="sm">
    <Text size="sm" fw={600} mb={6}>
      {title}
    </Text>
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
  </Card>
);

export const UsagePane: React.FC = () => {
  const scheme = useComputedColorScheme('light');
  const template = useMemo(() => mantinePlotlyTemplate(scheme), [scheme]);
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
  const plotConfig = { displayModeBar: false, responsive: true };
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
                label={k.label}
                suffix={k.suffix}
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
            <Card withBorder radius="md" p="sm">
              <Text size="sm" fw={600}>
                Activity
              </Text>
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
            </Card>
            <Card withBorder radius="md" p="sm">
              <Text size="sm" fw={600}>
                {isPublic ? 'New vs returning visitors' : 'New vs returning users'}
              </Text>
              <Plot
                style={{ width: '100%' }}
                useResizeHandler
                config={plotConfig}
                layout={plotLayout({ barmode: 'stack' })}
                data={
                  isPublic
                    ? [
                        { type: 'bar', name: 'New', x, y: report.series.map((p) => p.new_visitors) },
                        { type: 'bar', name: 'Returning', x, y: report.series.map((p) => p.returning_visitors) },
                      ]
                    : [
                        { type: 'bar', name: 'New', x, y: report.series.map((p) => p.new_users) },
                        { type: 'bar', name: 'Returning', x, y: report.series.map((p) => p.returning_users) },
                      ]
                }
              />
            </Card>
            <Card withBorder radius="md" p="sm">
              <Text size="sm" fw={600}>
                Content created
              </Text>
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
            </Card>
            <Card withBorder radius="md" p="sm">
              <Text size="sm" fw={600}>
                When (page views, weekday × hour UTC)
              </Text>
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
                  },
                ]}
              />
            </Card>
          </SimpleGrid>

          {report.geoip_available && (
            <Card withBorder radius="md" p="sm">
              <Text size="sm" fw={600}>
                Visitors by country
              </Text>
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
                    locations: (b.countries ?? []).map((c) => countryName(String(c.country))),
                    z: (b.countries ?? []).map((c) => Number(c.visitors)),
                    showscale: false,
                  },
                ]}
              />
            </Card>
          )}

          <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} spacing="sm">
            <MiniTable
              title="Top dashboards"
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
              rows={b.top_projects ?? []}
              columns={[
                { key: 'name', label: 'Project' },
                { key: 'views', label: 'Dashboard views' },
              ]}
            />
            <MiniTable
              title="Login methods"
              rows={b.login_methods ?? []}
              columns={[
                { key: 'method', label: 'Method' },
                { key: 'logins', label: 'Logins' },
              ]}
            />
            {report.geoip_available && (
              <MiniTable
                title="Countries"
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
              rows={b.browsers ?? []}
              columns={[
                { key: 'name', label: 'Browser' },
                { key: 'visitors', label: 'Visitors' },
              ]}
            />
            <MiniTable
              title="Operating systems"
              rows={b.os ?? []}
              columns={[
                { key: 'name', label: 'OS' },
                { key: 'visitors', label: 'Visitors' },
              ]}
            />
            <MiniTable
              title="Devices"
              rows={b.devices ?? []}
              columns={[
                { key: 'name', label: 'Device' },
                { key: 'visitors', label: 'Visitors' },
              ]}
            />
            <MiniTable
              title="Languages"
              rows={b.languages ?? []}
              columns={[
                { key: 'name', label: 'Language' },
                { key: 'visitors', label: 'Visitors' },
              ]}
            />
            <MiniTable
              title="Referrers"
              rows={b.referrers ?? []}
              columns={[
                { key: 'domain', label: 'Domain' },
                { key: 'visits', label: 'Visits' },
              ]}
            />
            <MiniTable
              title="Browsers per address (shared NAT)"
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
