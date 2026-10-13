/**
 * A look into a run's `pipeline_info`, the report the workflow engine wrote
 * about the run, as read with the folder's detection: the run itself (engine
 * and its version, run name, home page), its parameters (the ones that place
 * the run first, filterable), the tools it ran, and the report files found.
 */
import React, { useMemo, useState } from 'react';
import {
  Anchor,
  Badge,
  Group,
  ScrollArea,
  SimpleGrid,
  Stack,
  Table,
  Tabs,
  Text,
  TextInput,
  ThemeIcon,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { relativeToRunFolder } from 'depictio-react-core';
import type { RunInfoSummary, RunReportFile } from 'depictio-react-core';

import { engineLabel, WorkflowEngineLogo } from '../../template';
import { fileSize } from '../fileSize';
import { FolderPath } from '../FolderPath';
import { plural } from '../plural';

/** Parameters that say where a run read and wrote, shown first. */
const KEY_PARAMS = [
  'input',
  'outdir',
  'genome',
  'fasta',
  'gtf',
  'metadata',
  'reference',
  'aligner',
  'profile',
];

const REPORT_KIND: Record<RunReportFile['kind'], { label: string; icon: string }> = {
  software_versions: { label: 'Software versions', icon: 'mdi:tag-multiple-outline' },
  params: { label: 'Parameters', icon: 'mdi:tune-variant' },
  execution_report: { label: 'Execution report', icon: 'mdi:file-chart-outline' },
  execution_trace: { label: 'Execution trace', icon: 'mdi:timeline-text-outline' },
  pipeline_dag: { label: 'Pipeline graph', icon: 'mdi:graph-outline' },
};

const EXTRA_LABEL: Record<string, string> = {
  pipeline_version_raw: 'Version as written',
  identity_from_run: 'Identity read from',
};

function paramText(value: string | number | boolean | null): string {
  if (value === null) return 'null';
  return String(value);
}

const Fact: React.FC<{ label: string; children: React.ReactNode; testId?: string }> = ({
  label,
  children,
  testId,
}) => (
  <Stack gap={2} style={{ minWidth: 0 }} data-testid={testId}>
    <Text size="xs" fw={700} c="dimmed" tt="uppercase">
      {label}
    </Text>
    {children}
  </Stack>
);

const RunFacts: React.FC<{ info: RunInfoSummary }> = ({ info }) => (
  <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md" verticalSpacing="sm">
    <Fact label="Engine" testId="pipeline-info-engine">
      {info.engine ? (
        <Group gap={6} wrap="nowrap">
          <WorkflowEngineLogo engine={info.engine} size={16} />
          <Text size="sm">
            {engineLabel(info.engine)}
            {info.engine_version ? ` ${info.engine_version}` : ''}
          </Text>
        </Group>
      ) : (
        <Text size="sm" c="dimmed">
          not stated
        </Text>
      )}
    </Fact>
    <Fact label="Run name" testId="pipeline-info-run-name">
      <Text size="sm" ff="monospace" c={info.run_name ? undefined : 'dimmed'}>
        {info.run_name ?? 'not stated'}
      </Text>
    </Fact>
    {info.homepage && (
      <Fact label="Pipeline home page">
        <Anchor href={info.homepage} target="_blank" rel="noreferrer" size="sm" style={{ wordBreak: 'break-all' }}>
          {info.homepage}
        </Anchor>
      </Fact>
    )}
    {Object.entries(info.extra).map(([key, value]) => (
      <Fact key={key} label={EXTRA_LABEL[key] ?? key.replace(/_/g, ' ')}>
        <Text size="sm" ff="monospace" style={{ wordBreak: 'break-all' }}>
          {value}
        </Text>
      </Fact>
    ))}
  </SimpleGrid>
);

const Params: React.FC<{ info: RunInfoSummary }> = ({ info }) => {
  const [query, setQuery] = useState('');
  const rows = useMemo(() => {
    const entries = Object.entries(info.params);
    const key = (name: string) => {
      const at = KEY_PARAMS.indexOf(name);
      return at < 0 ? KEY_PARAMS.length : at;
    };
    entries.sort(([a], [b]) => key(a) - key(b) || a.localeCompare(b));
    const q = query.trim().toLowerCase();
    return q
      ? entries.filter(([name, value]) => `${name} ${paramText(value)}`.toLowerCase().includes(q))
      : entries;
  }, [info.params, query]);
  const shown = Object.keys(info.params).length;

  if (shown === 0) {
    return (
      <Text size="sm" c="dimmed">
        The run recorded no parameters.
      </Text>
    );
  }
  return (
    <Stack gap="xs">
      <TextInput
        size="xs"
        placeholder="Filter the parameters"
        leftSection={<Icon icon="mdi:magnify" width={14} />}
        value={query}
        onChange={(e) => setQuery(e.currentTarget.value)}
        data-testid="pipeline-info-params-filter"
      />
      <ScrollArea.Autosize mah={280} type="auto" offsetScrollbars>
        <Table verticalSpacing={4} striped highlightOnHover data-testid="pipeline-info-params">
          <Table.Tbody>
            {rows.map(([name, value]) => (
              <Table.Tr key={name}>
                <Table.Td w="40%" style={{ verticalAlign: 'top' }}>
                  <Text size="xs" ff="monospace" fw={KEY_PARAMS.includes(name) ? 700 : 400}>
                    {name}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Text size="xs" ff="monospace" style={{ wordBreak: 'break-all' }}>
                    {paramText(value)}
                  </Text>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </ScrollArea.Autosize>
      {info.params_total > shown && (
        <Text size="xs" c="dimmed">
          The first {shown} of {plural(info.params_total, 'parameter')}.
        </Text>
      )}
    </Stack>
  );
};

const Tools: React.FC<{ tools: string[] }> = ({ tools }) =>
  tools.length === 0 ? (
    <Text size="sm" c="dimmed">
      The run did not list the tools it ran.
    </Text>
  ) : (
    <Stack gap="xs">
      <Text size="xs" c="dimmed">
        The collections built from these tools&rsquo; outputs are the ones that find data.
      </Text>
      <ScrollArea.Autosize mah={240} type="auto" offsetScrollbars>
        <Group gap={4} wrap="wrap" data-testid="pipeline-info-tools">
          {tools.map((tool) => (
            <Badge key={tool} variant="light" color="gray" radius="sm" tt="none" fw={500}>
              {tool}
            </Badge>
          ))}
        </Group>
      </ScrollArea.Autosize>
    </Stack>
  );

const Reports: React.FC<{ reports: RunReportFile[]; folder: string }> = ({ reports, folder }) =>
  reports.length === 0 ? (
    <Text size="sm" c="dimmed">
      No report file was recognised in pipeline_info.
    </Text>
  ) : (
    <Stack gap={6} data-testid="pipeline-info-reports">
      {reports.map((report) => {
        const kind = REPORT_KIND[report.kind];
        const size = fileSize(report.size);
        const relative = relativeToRunFolder(folder, report.location);
        return (
          <Group key={report.location} gap="sm" wrap="nowrap" align="center">
            <ThemeIcon variant="light" color="gray" size="md" radius="md">
              <Icon icon={kind?.icon ?? 'mdi:file-outline'} width={14} />
            </ThemeIcon>
            <Stack gap={0} style={{ flex: 1, minWidth: 0 }}>
              <Text size="sm" fw={600}>
                {kind?.label ?? report.kind}
              </Text>
              <FolderPath location={report.location} label={relative || report.name} maxLength={72} />
            </Stack>
            {size && (
              <Text size="xs" c="dimmed" style={{ flexShrink: 0 }}>
                {size}
              </Text>
            )}
          </Group>
        );
      })}
    </Stack>
  );

export const PipelineInfoPreview: React.FC<{ info: RunInfoSummary; folder: string }> = ({
  info,
  folder,
}) => (
  <Tabs defaultValue="run" variant="outline" radius="md" keepMounted={false} data-testid="pipeline-info-preview">
    <Tabs.List>
      <Tabs.Tab value="run" leftSection={<Icon icon="mdi:play-circle-outline" width={14} />}>
        Run
      </Tabs.Tab>
      <Tabs.Tab value="params" leftSection={<Icon icon="mdi:tune-variant" width={14} />}>
        Parameters ({info.params_total})
      </Tabs.Tab>
      <Tabs.Tab value="tools" leftSection={<Icon icon="mdi:tools" width={14} />}>
        Tools ({info.tools_executed.length})
      </Tabs.Tab>
      <Tabs.Tab value="files" leftSection={<Icon icon="mdi:file-document-multiple-outline" width={14} />}>
        Files ({info.reports.length})
      </Tabs.Tab>
    </Tabs.List>
    <Tabs.Panel value="run" pt="sm">
      <RunFacts info={info} />
    </Tabs.Panel>
    <Tabs.Panel value="params" pt="sm">
      <Params info={info} />
    </Tabs.Panel>
    <Tabs.Panel value="tools" pt="sm">
      <Tools tools={info.tools_executed} />
    </Tabs.Panel>
    <Tabs.Panel value="files" pt="sm">
      <Reports reports={info.reports} folder={folder} />
    </Tabs.Panel>
  </Tabs>
);
