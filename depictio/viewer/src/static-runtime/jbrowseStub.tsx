/**
 * Stand-in for depictio-react-core's `JBrowseRenderer` in static bundles.
 *
 * vite.static.config.ts swaps the real module for this one. A genome browser
 * streams its tracks from the server at view time, and the real renderer would
 * add ~2.5 MB of JBrowse and its adapters to every single-file bundle. What a
 * bundle can carry is the export-time session (producer A freezes
 * `render_jbrowse` at the default filter state): the assembly, the locus it
 * opened on and the track table — shown here, labelled as a snapshot.
 */
import React, { useEffect, useState } from 'react';
import { Badge, Center, Group, ScrollArea, Stack, Table, Text } from '@mantine/core';

import type { JBrowseSessionResponse } from '../../../../packages/depictio-react-core/src/api';
// From the shim itself: this module IS a shim (vite.static.config.ts), and the
// module-shim plugin lets a shim's imports of api.ts through to the real one.
import { fetchJBrowseSession } from './apiShim';

interface Props {
  dashboardId?: string;
  metadata?: { index?: string | number };
  [key: string]: unknown;
}

const NEEDS_SERVER = 'The genome browser streams its tracks from a Depictio server at view time.';

const JBrowseRenderer: React.FC<Props> = ({ dashboardId, metadata }) => {
  const [session, setSession] = useState<JBrowseSessionResponse | null>(null);
  const [missing, setMissing] = useState(false);
  useEffect(() => {
    let cancelled = false;
    fetchJBrowseSession(String(dashboardId ?? ''), String(metadata?.index ?? ''))
      .then((s) => {
        if (!cancelled) setSession(s);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        console.warn('static bundle: no JBrowse session snapshot', err);
        setMissing(true);
      });
    return () => {
      cancelled = true;
    };
  }, [dashboardId, metadata?.index]);

  if (missing || !session) {
    return (
      <Center h="100%" p="md">
        <Text size="sm" c="dimmed" ta="center">
          {missing ? `${NEEDS_SERVER} It is not included in this static copy.` : 'Loading…'}
        </Text>
      </Center>
    );
  }
  const assembly = String((session.assembly as { name?: string }).name ?? '');
  const shown = new Set(session.shown_track_ids);
  const rows = session.track_rows ?? [];
  return (
    <Stack gap="xs" p="sm" h="100%" data-testid="jbrowse-snapshot">
      <Text size="xs" c="dimmed">
        {NEEDS_SERVER} Export-time session:
      </Text>
      <Group gap="xs">
        {assembly && <Badge variant="light">{assembly}</Badge>}
        {session.location && <Badge variant="outline">{session.location}</Badge>}
        <Badge variant="light" color="gray">
          {session.matched_tracks} of {session.total_tracks} tracks
        </Badge>
      </Group>
      <ScrollArea style={{ flex: 1 }}>
        <Table striped withTableBorder fz="xs">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Track</Table.Th>
              <Table.Th>Format</Table.Th>
              <Table.Th>Sample</Table.Th>
              <Table.Th>Shown</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((r) => (
              <Table.Tr key={r.track_id}>
                <Table.Td>{r.name}</Table.Td>
                <Table.Td>{r.format}</Table.Td>
                <Table.Td>{r.sample ?? ''}</Table.Td>
                <Table.Td>{shown.has(r.track_id) ? 'yes' : ''}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </ScrollArea>
    </Stack>
  );
};

export default JBrowseRenderer;
