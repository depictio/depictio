import { useRef, useState } from 'react';
import { Stack, Title, Text, Center, Group, Badge, Table, ScrollArea, Paper, Code } from '@mantine/core';
import { Icon } from '@iconify/react';
import { notifications } from '@mantine/notifications';
import { useStudioStore } from '../state/useStudioStore';
import { parseFixture } from '../catalog/parseFixture';
import type { Dtype } from '../types';

const DTYPE_COLOR: Record<Dtype, string> = {
  String: 'gray',
  Int64: 'blue',
  Float64: 'cyan',
  Boolean: 'grape',
  Datetime: 'orange',
};

export default function FixtureDrop() {
  const fixture = useStudioStore((s) => s.fixture);
  const setFixture = useStudioStore((s) => s.setFixture);
  const [dragActive, setDragActive] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const ingest = async (file: File) => {
    const lower = file.name.toLowerCase();
    if (!lower.endsWith('.csv') && !lower.endsWith('.tsv')) {
      notifications.show({ color: 'red', message: 'Drop a .csv or .tsv file.' });
      return;
    }
    const raw = await file.text();
    const parsed = parseFixture(file.name, raw);
    if (parsed.columns.length === 0) {
      notifications.show({ color: 'red', message: 'No columns detected — is the header row present?' });
      return;
    }
    setFixture(parsed);
    notifications.show({
      color: 'teal',
      message: `${file.name}: ${parsed.columns.length} columns, ${parsed.rows.length} rows.`,
    });
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragActive(false);
    const file = e.dataTransfer.files?.[0];
    if (file) void ingest(file);
  };

  const preview = fixture?.rows.slice(0, 8) ?? [];

  return (
    <Stack gap="lg">
      <div>
        <Title order={3} style={{ fontFamily: 'Virgil', fontWeight: 400 }}>
          Fixture
        </Title>
        <Text c="dimmed" size="sm">
          Drop the tool's output file. It's bundled verbatim as the fixture and grounds your
          bindings in CI. Nothing leaves your browser.
        </Text>
      </div>

      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragActive(true);
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={onDrop}
        style={{
          width: '100%',
          borderWidth: 2,
          borderStyle: 'dashed',
          borderRadius: 8,
          borderColor: dragActive ? 'var(--mantine-color-blue-filled)' : 'var(--mantine-color-default-border)',
          padding: '40px 20px',
          cursor: 'pointer',
          background: dragActive ? 'var(--mantine-color-blue-light)' : 'transparent',
          color: 'inherit',
          transition: 'border-color 120ms, background-color 120ms',
        }}
      >
        <Center>
          <Stack align="center" gap={4}>
            <Icon icon="mdi:file-upload-outline" width={40} />
            <Text fw={600}>{fixture ? fixture.fileName : 'Drop CSV/TSV or click to browse'}</Text>
            <Text size="xs" c="dimmed">
              Delimiter auto-detected (.tsv → tab, else comma)
            </Text>
          </Stack>
        </Center>
      </button>
      <input
        ref={inputRef}
        type="file"
        accept=".csv,.tsv"
        style={{ display: 'none' }}
        onChange={(e) => {
          const f = e.currentTarget.files?.[0];
          if (f) void ingest(f);
        }}
      />

      {fixture && (
        <Paper withBorder p="md" radius="md">
          <Group justify="space-between" mb="sm">
            <Title order={5}>Columns</Title>
            <Group gap="xs">
              <Badge variant="light">{fixture.columns.length} cols</Badge>
              <Badge variant="light" color="gray">
                {fixture.rows.length} rows
              </Badge>
              <Badge variant="light" color={fixture.delimiter === '\t' ? 'orange' : 'blue'}>
                {fixture.delimiter === '\t' ? 'TSV' : 'CSV'}
              </Badge>
            </Group>
          </Group>
          <Group gap="xs" mb="md">
            {fixture.columns.map((c) => (
              <Badge key={c.name} color={DTYPE_COLOR[c.dtype]} variant="light" radius="sm">
                {c.name} · {c.dtype}
              </Badge>
            ))}
          </Group>
          <ScrollArea type="auto">
            <Table striped highlightOnHover withTableBorder fz="xs">
              <Table.Thead>
                <Table.Tr>
                  {fixture.columns.map((c) => (
                    <Table.Th key={c.name}>{c.name}</Table.Th>
                  ))}
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {preview.map((row, i) => (
                  <Table.Tr key={i}>
                    {fixture.columns.map((c) => (
                      <Table.Td key={c.name}>
                        <Code fz="xs">{String(row[c.name] ?? '')}</Code>
                      </Table.Td>
                    ))}
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </ScrollArea>
        </Paper>
      )}
    </Stack>
  );
}
