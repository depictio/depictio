import React from 'react';
import { Anchor, Divider, Group, Stack, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import type { BundleManifest } from 'depictio-static-core';

/**
 * Export provenance for the sidebar footer — who built this bundle, from where,
 * and with which depictio.
 *
 * Only rendered inside a serverless static bundle: the manifest lives on
 * `window.__DEPICTIO_BUNDLE__`, which the static runtime's entry sets and the
 * server build never does, so this is a `null` return and nothing else in a
 * normal render. Reading the global (rather than importing the runtime's
 * `bundle()`) is what keeps `depictio-static-core` out of the server bundle —
 * the type import above is erased at build time.
 *
 * Every provenance field is optional: producer B builds from a spec and knows
 * almost nothing about an instance. Rows render only for the fields that are
 * present, and the row block disappears entirely rather than leaving an empty
 * frame. The one-line "what am I looking at" statement always renders, because
 * inside a bundle it is always true and is the whole point for a reader who
 * received the file with no context.
 */

/** Manifest `producer` -> what that letter means for a reader. */
const PRODUCER_LABEL: Record<string, string> = {
  A: 'exported from a running instance',
  B: 'built from a spec',
  C: 'exported through the API',
};

/**
 * Render an export timestamp as a plain, unambiguous UTC stamp.
 *
 * depictio's API writes naive UTC (no offset), which `Date` would read as local
 * time — so a bare string gets a `Z` before parsing. Anything unparseable is
 * shown verbatim: a provenance line must never invent a date.
 */
function formatExportedAt(raw: string | null | undefined): string | null {
  if (!raw) return null;
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(raw);
  const parsed = new Date(hasZone ? raw : `${raw}Z`);
  if (Number.isNaN(parsed.getTime())) return raw;
  return `${parsed.toISOString().slice(0, 16).replace('T', ' ')} UTC`;
}

interface ProvenanceRow {
  label: string;
  value: string;
  /** Tooltip text. Defaults to the value, which is what a truncated one needs. */
  hint?: string;
  /** Rendered instead of the plain text value (external instance link). */
  href?: string;
}

function provenanceRows(manifest: BundleManifest): ProvenanceRow[] {
  const p = manifest.provenance ?? {};
  const rows: ProvenanceRow[] = [];
  const push = (label: string, value: string | null | undefined, hint?: string) => {
    if (value) rows.push(hint ? { label, value, hint } : { label, value });
  };

  push('By', p.exported_by);
  push('On', formatExportedAt(p.exported_at));
  push('From', p.source);
  push('Project', p.project_name);
  push(
    'Built with',
    manifest.depictio_version ? `depictio ${manifest.depictio_version}` : null,
  );
  // Just the letter in the rail — the column is ~120px wide and the gloss does
  // not fit. It rides in the tooltip instead of being truncated to nothing.
  push(
    'Producer',
    manifest.producer,
    manifest.producer && PRODUCER_LABEL[manifest.producer]
      ? `Producer ${manifest.producer} — ${PRODUCER_LABEL[manifest.producer]}`
      : undefined,
  );
  // Only an absolute http(s) URL is worth offering: it is the one link in a
  // bundle that still resolves, and it opens the live dashboard elsewhere.
  const url = p.dashboard_url;
  if (url && /^https?:\/\//i.test(url)) {
    rows.push({ label: 'Live copy', value: 'open in a new tab', href: url });
  }
  return rows;
}

const StaticProvenance: React.FC = () => {
  const manifest = typeof window === 'undefined' ? undefined : window.__DEPICTIO_BUNDLE__;
  if (!manifest) return null;
  const rows = provenanceRows(manifest);

  return (
    <Stack gap={4} w="100%">
      <Divider w="100%" />
      <Group gap={6} justify="center" wrap="nowrap">
        <Icon icon="mdi:package-variant-closed" width={14} height={14} />
        <Text size="xs" fw={600} c="dimmed">
          Static export
        </Text>
      </Group>
      <Text size="xs" c="dimmed" ta="center" lh={1.3}>
        A self-contained copy of this dashboard. No server, no live data.
      </Text>
      {rows.length > 0 && (
        <Stack gap={0} mt={2}>
          {rows.map((row) => (
            <Group key={row.label} gap={8} justify="space-between" wrap="nowrap">
              <Text size="xs" c="dimmed" style={{ flexShrink: 0 }}>
                {row.label}
              </Text>
              {/* The rail is 250px wide and a source URL or an email is easily
                  longer, so values truncate and carry the full string in a
                  tooltip. */}
              <Tooltip
                label={row.hint ?? row.href ?? row.value}
                withArrow
                position="top-end"
                multiline
              >
                {row.href ? (
                  <Anchor
                    href={row.href}
                    target="_blank"
                    rel="noreferrer"
                    size="xs"
                    c="dimmed"
                    truncate
                  >
                    {row.value}
                  </Anchor>
                ) : (
                  <Text size="xs" c="dimmed" truncate>
                    {row.value}
                  </Text>
                )}
              </Tooltip>
            </Group>
          ))}
        </Stack>
      )}
    </Stack>
  );
};

export default StaticProvenance;
