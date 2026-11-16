/**
 * depictio-react-core's `JBrowseRenderer` in static bundles.
 *
 * vite.static.config.ts swaps the real module for this one. Producer A freezes
 * `render_jbrowse` at the default filter state and, when the session's files
 * fit the bundle's budget, ships them (`payload.bundle`, see
 * depictio/serverless/jbrowse_bundle.py) and rewrites every location to a URL
 * the runtime's fetch shim answers from memory (`jbrowse/bundleFetch.ts`).
 * Then this mounts the REAL renderer — JBrowse itself comes from the `jbrowse`
 * add-on the producer appended (`jbrowse/vendor.ts`).
 *
 * Otherwise (an older bundle, no add-on, or nothing the browser could draw
 * fitting the budget) it shows the export-time session: the assembly, the
 * locus it opened on and the track table, with the reason it is not the
 * browser.
 */
import React, { Suspense, useEffect, useMemo, useState } from 'react';
import { Badge, Center, Group, ScrollArea, Stack, Table, Text } from '@mantine/core';
import type { BundledFileEntry } from 'depictio-static-core';

import type {
  JBrowseSessionResponse,
  StoredMetadata,
} from '../../../../packages/depictio-react-core/src/api';
// From the shim itself: this module IS a shim (vite.static.config.ts), so its
// imports reach the real modules.
import RealJBrowseRenderer from '../../../../packages/depictio-react-core/src/components/JBrowseRenderer';
import { fetchJBrowseSession } from './apiShim';
import { registerBundledFiles } from './jbrowse/bundleFetch';
import { jbrowseVendorLoaded, jbrowseVendorProblem } from './jbrowse/vendor';

/** What producer A ships next to the session (`jbrowse_bundle.py`). */
export interface BundledSession {
  version: number;
  renderable: boolean;
  reason?: string | null;
  files: Record<string, BundledFileEntry>;
  omitted?: { track_id: string; name?: string; reason: string }[];
  region?: string | null;
  sequence?: string | null;
}

type Session = JBrowseSessionResponse & { bundle?: BundledSession };

type Props = React.ComponentProps<typeof RealJBrowseRenderer>;

const NEEDS_SERVER = 'The genome browser streams its tracks from a Depictio server at view time.';

/** Why the real browser cannot be mounted for this session, or null when it can. */
export function offlineBlocker(session: Session): string | null {
  const b = session.bundle;
  if (!b) return 'this bundle was exported before genome data could be bundled';
  if (!b.renderable) return b.reason || 'none of the genome data fits the bundle';
  if (!jbrowseVendorLoaded()) return jbrowseVendorProblem();
  return null;
}

const SessionTable: React.FC<{ session: Session; why: string }> = ({ session, why }) => {
  const assembly = String((session.assembly as { name?: string }).name ?? '');
  const shown = new Set(session.shown_track_ids);
  const rows = session.track_rows ?? [];
  return (
    <Stack gap="xs" p="sm" h="100%" data-testid="jbrowse-snapshot">
      <Text size="xs" c="dimmed">
        {NEEDS_SERVER} Not drawn offline: {why}. Export-time session:
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

const JBrowseRenderer: React.FC<Props> = (props) => {
  const { dashboardId, metadata } = props;
  const [session, setSession] = useState<Session | null>(null);
  const [missing, setMissing] = useState(false);
  useEffect(() => {
    let cancelled = false;
    fetchJBrowseSession(String(dashboardId ?? ''), String(metadata?.index ?? ''))
      .then((s: Session) => {
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

  const blocker = session ? offlineBlocker(session) : null;
  if (session && !blocker) registerBundledFiles(session.bundle?.files);

  // The extra views (breakpoint, circular) are not in the add-on; the session
  // is the frozen one whatever the filters (the tier says so).
  const offlineMetadata = useMemo(
    () => ({ ...(metadata as StoredMetadata), views: [] }) as StoredMetadata,
    [metadata],
  );
  const loadSession = useMemo(
    () => (session ? () => Promise.resolve(session as JBrowseSessionResponse) : undefined),
    [session],
  );

  if (missing || !session) {
    return (
      <Center h="100%" p="md">
        <Text size="sm" c="dimmed" ta="center">
          {missing ? `${NEEDS_SERVER} It is not included in this static copy.` : 'Loading…'}
        </Text>
      </Center>
    );
  }
  if (blocker) return <SessionTable session={session} why={blocker} />;
  return (
    <Suspense fallback={null}>
      <RealJBrowseRenderer {...props} metadata={offlineMetadata} loadSession={loadSession} />
    </Suspense>
  );
};

export default JBrowseRenderer;
