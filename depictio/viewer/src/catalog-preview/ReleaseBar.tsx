/**
 * Release selector + "What's new" for the multi-file catalog site, in the top bar
 * (the Paper bar's extras, before the view switch; the Classic bar's right group).
 * Each half hides itself, silently, when its file (`../versions.json`,
 * `../releases.json`) is missing: a bare export has neither.
 */
import React, { useEffect, useState } from 'react';
import {
  ActionIcon,
  Anchor,
  Badge,
  Button,
  Group,
  Modal,
  Select,
  Stack,
  Text,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { Sparkles } from 'lucide-react';
import { useCatalogPaper } from './shared';
import type { CatalogGlobal } from './shared';
import { fetchReleases, fetchVersions } from './siteData';
import type { ReleaseEntry, ReleasesFile, VersionsFile } from './siteData';
import { BumpBadge } from './ModuleVersions';
import { currentSlot, knownSlots, slotHref } from './siteTree';

const Section: React.FC<{ title: string; children: React.ReactNode }> = ({ title, children }) => (
  <Stack gap={4}>
    <Text size="xs" fw={700} c="dimmed" tt="uppercase">
      {title}
    </Text>
    {children}
  </Stack>
);

const WhatsNew: React.FC<{
  g: CatalogGlobal;
  release: ReleaseEntry;
  onClose: () => void;
}> = ({ g, release, onClose }) => {
  const c = release.changes ?? {};
  const toolIds = new Set(g.tools.map((t) => t.id));
  const outputIds = new Set(g.tools.flatMap((t) => t.outputs.map((o) => o.output.id)));
  const nameOf = (id: string) => g.tools.find((t) => t.id === id)?.name ?? id;
  const toolLink = (id: string) =>
    toolIds.has(id) ? (
      <Anchor href={`#tool=${encodeURIComponent(id)}`} size="sm" fw={600} onClick={onClose}>
        {nameOf(id)}
      </Anchor>
    ) : (
      <Text size="sm" fw={600} span>
        {nameOf(id)}
      </Text>
    );
  const outLink = (id: string) =>
    outputIds.has(id) ? (
      <Anchor href={`#output=${encodeURIComponent(id)}`} size="xs" onClick={onClose}>
        {id}
      </Anchor>
    ) : (
      <Text size="xs" span>
        {id}
      </Text>
    );
  const added = c.added ?? [];
  const removed = c.removed ?? [];
  const bumped = c.bumped ?? [];
  const oa = c.outputs_added ?? [];
  const or = c.outputs_removed ?? [];
  const empty = !(added.length || removed.length || bumped.length || oa.length || or.length);
  return (
    <Stack gap="md" data-testid="whats-new">
      {release.previous ? (
        <Text size="xs" c="dimmed">
          Compared with {release.previous}
          {release.published ? ` · ${release.published.slice(0, 10)}` : ''}
        </Text>
      ) : null}
      {empty ? <Text size="sm">No catalog changes.</Text> : null}
      {added.length ? (
        <Section title="Tools added">
          <Group gap="sm">{added.map((id) => <span key={id}>{toolLink(id)}</span>)}</Group>
        </Section>
      ) : null}
      {bumped.length ? (
        <Section title="Modules updated">
          {bumped.map((b) => (
            <Group key={b.id} gap={8} wrap="nowrap">
              {toolLink(b.id)}
              <Text size="xs" c="dimmed">
                {b.from} → {b.to}
              </Text>
              <BumpBadge bump={b.bump} />
            </Group>
          ))}
        </Section>
      ) : null}
      {removed.length ? (
        <Section title="Tools removed">
          <Group gap="sm">{removed.map((id) => <span key={id}>{toolLink(id)}</span>)}</Group>
        </Section>
      ) : null}
      {oa.length ? (
        <Section title="Outputs added">
          <Group gap="sm">{oa.map((id) => <span key={id}>{outLink(id)}</span>)}</Group>
        </Section>
      ) : null}
      {or.length ? (
        <Section title="Outputs removed">
          <Group gap="sm">{or.map((id) => <span key={id}>{outLink(id)}</span>)}</Group>
        </Section>
      ) : null}
    </Stack>
  );
};

const ReleaseBar: React.FC = () => {
  const g = window.__CATALOG_PREVIEW__ as unknown as CatalogGlobal | undefined;
  const lazy = Boolean(g?.lazyOutputs);
  const [versions, setVersions] = useState<VersionsFile | null>(null);
  const [releases, setReleases] = useState<ReleasesFile | null>(null);
  const [open, setOpen] = useState(false);
  const { paper, tone } = useCatalogPaper();

  useEffect(() => {
    if (!lazy || !g) return;
    let cancelled = false;
    // releases.json only when versions.json exists (a bare export has neither).
    fetchVersions(g).then(async (v) => {
      if (cancelled) return;
      setVersions(v);
      if (!v) return;
      const r = await fetchReleases(g);
      if (!cancelled) setReleases(r);
    });
    return () => {
      cancelled = true;
    };
  }, [lazy, g]);

  if (!g || !lazy) return null;
  const list = versions?.versions ?? [];
  const slot = currentSlot(window.location.pathname, list, g.version);
  const release = slot ? releases?.releases.find((r) => r.slot === slot) : undefined;

  const go = (next: string | null) => {
    if (!next || next === slot) return;
    window.location.href = slotHref(
      window.location.href,
      g.dataBase ?? 'data/',
      next,
      window.location.search,
      window.location.hash,
    );
  };

  const slotChoices = versions ? knownSlots(versions) : [];
  return (
    <Group gap={6} wrap="nowrap">
      {versions ? (
        <Tooltip label="Catalog release" withArrow>
          <Select
            size="xs"
            w={paper ? 96 : 112}
            aria-label="Catalog release"
            allowDeselect={false}
            value={slot}
            data={slotChoices.map((s) => ({ value: s, label: s }))}
            onChange={go}
            comboboxProps={{ withinPortal: true }}
          />
        </Tooltip>
      ) : null}
      {release && slot ? (
        <>
          {paper ? (
            // Paper's bar is a row of icon keys; a labelled button there pushed the
            // bar's title ("Tools catalog") into an ellipsis at desktop width.
            <Tooltip label="What’s new" withArrow openDelay={250}>
              <ActionIcon
                size="lg"
                variant="subtle"
                color="gray"
                aria-label="What’s new"
                onClick={() => setOpen(true)}
              >
                <Sparkles size={19} strokeWidth={1.6} aria-hidden />
              </ActionIcon>
            </Tooltip>
          ) : (
            <Button
              size="xs"
              variant="light"
              color={tone}
              leftSection={<Icon icon="mdi:new-box" width={16} />}
              onClick={() => setOpen(true)}
            >
              What&rsquo;s new
            </Button>
          )}
          <Modal
            opened={open}
            onClose={() => setOpen(false)}
            size="md"
            title={
              <Group gap={8}>
                <Text fw={700} size="sm">
                  {slot === 'latest'
                    ? `Unreleased changes since ${release.previous ?? 'the last release'}`
                    : `What's new in ${slot}`}
                </Text>
                <Badge size="xs" variant="light" color="gray" radius="sm">
                  {slot}
                </Badge>
              </Group>
            }
          >
            <WhatsNew g={g} release={release} onClose={() => setOpen(false)} />
          </Modal>
        </>
      ) : null}
    </Group>
  );
};

export default ReleaseBar;
