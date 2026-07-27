/**
 * "Will this version still render?" — shown before a restore is committed.
 *
 * Names the columns that changed and the components that reference them.
 * A pair of schema hashes can only say *different*, which is not something
 * anyone can act on; "3 components reference a column that no longer exists"
 * is.
 *
 * Loads on mount, so it only costs a request when a restore dialog is
 * actually open.
 */

import React, { useEffect, useState } from 'react';
import { Alert, Group, List, Loader, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';
import { fetchVersionCompatibility, type CompatibilityReport } from 'depictio-react-core';

interface VersionCompatibilityPanelProps {
  versionId: string | null;
}

const SEVERITY_META: Record<string, { color: string; icon: string; title: string }> = {
  ok: { color: 'green', icon: 'mdi:check-circle', title: 'Still matches the current data' },
  info: { color: 'blue', icon: 'mdi:information', title: 'Data has changed since' },
  warning: { color: 'yellow', icon: 'mdi:alert', title: 'Data has changed since' },
  error: { color: 'red', icon: 'mdi:alert-circle', title: 'Some components will not render' },
};

const VersionCompatibilityPanel: React.FC<VersionCompatibilityPanelProps> = ({ versionId }) => {
  const [report, setReport] = useState<CompatibilityReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!versionId) {
      setReport(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setFailed(false);
    fetchVersionCompatibility(versionId)
      .then((result) => {
        if (!cancelled) setReport(result);
      })
      .catch(() => {
        // A failed check must not block the restore — the restore itself is
        // undoable, so an unavailable report is an inconvenience, not a risk.
        if (!cancelled) setFailed(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [versionId]);

  if (loading) {
    return (
      <Group gap={8}>
        <Loader size="xs" />
        <Text size="xs" c="dimmed">
          Checking against current data…
        </Text>
      </Group>
    );
  }

  if (failed) {
    return (
      <Text size="xs" c="dimmed">
        Could not check this version against the current data.
      </Text>
    );
  }

  if (!report || report.checks.length === 0) return null;

  const meta = SEVERITY_META[report.severity] ?? SEVERITY_META.info;
  const notable = report.checks.filter(
    (check) =>
      !check.found ||
      check.columns_removed.length > 0 ||
      check.columns_retyped.length > 0 ||
      check.affected_components.length > 0,
  );

  if (report.severity === 'ok' || notable.length === 0) {
    return (
      <Alert
        color="green"
        variant="light"
        icon={<Icon icon="mdi:check-circle" width={16} />}
        data-testid="version-compatibility"
      >
        <Text size="sm">Still matches the current data.</Text>
      </Alert>
    );
  }

  return (
    <Alert
      color={meta.color}
      variant="light"
      title={meta.title}
      icon={<Icon icon={meta.icon} width={16} />}
      data-testid="version-compatibility"
    >
      <Stack gap={6}>
        <List size="xs" spacing={4}>
          {notable.map((check) => {
            const name = check.data_collection_tag || check.dc_id;
            if (!check.found) {
              return (
                <List.Item key={check.dc_id}>
                  <Text size="xs">
                    <strong>{name}</strong> no longer exists
                    {check.affected_components.length > 0 &&
                      ` — ${check.affected_components.length} component(s) affected`}
                  </Text>
                </List.Item>
              );
            }
            return (
              <List.Item key={check.dc_id}>
                <Text size="xs">
                  <strong>{name}</strong>
                  {check.columns_removed.length > 0 &&
                    ` — missing ${check.columns_removed.join(', ')}`}
                  {check.columns_retyped.length > 0 &&
                    ` — retyped ${check.columns_retyped
                      .map((c) => `${c.name} (${c.from} → ${c.to})`)
                      .join(', ')}`}
                  {check.affected_components.length > 0 &&
                    ` · ${check.affected_components.length} component(s) affected`}
                </Text>
              </List.Item>
            );
          })}
        </List>
        <Text size="xs" c="dimmed">
          Restoring is still allowed — affected components will render empty.
        </Text>
      </Stack>
    </Alert>
  );
};

export default VersionCompatibilityPanel;
