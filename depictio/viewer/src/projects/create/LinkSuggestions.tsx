/**
 * After data is added: the links its tables could have, found from the values
 * they share with the other collections. Nothing is linked without a click,
 * and each proposal opens the link dialog already filled.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { ActionIcon, Badge, Button, Collapse, Group, Loader, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';
import { fetchLinkSuggestions, fetchProject, listLinkResolvers } from 'depictio-react-core';
import type { LinkSuggestion, ResolverInfo } from 'depictio-react-core';

import { useListingAccents } from '../../lib/useListingAccents';
import { LinkExamples } from '../detail/LinkExamples';
import LinkEditModal from '../detail/LinkEditModal';
import { plural } from '../fromRun/plural';
import type { TableUploadOutcome } from './FilesDropArea';
import { identifyFile } from './fileKinds';
import { SourceSection } from './SourceSection';

interface CollectionOption {
  id: string;
  tag: string;
  type: string;
}

const keyOf = (s: LinkSuggestion) => `${s.source_dc_id}:${s.target_dc_id}`;

export const LinkSuggestions: React.FC<{
  projectId: string;
  uploads: TableUploadOutcome[];
  /** Every upload and ingestion is over: the collections can be read. */
  ready: boolean;
  testId: string;
}> = ({ projectId, uploads, ready, testId }) => {
  const accent = useListingAccents('projects');
  const [tableIds, setTableIds] = useState<string[] | null>(null);
  const [suggestions, setSuggestions] = useState<LinkSuggestion[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [collections, setCollections] = useState<CollectionOption[]>([]);
  const [resolvers, setResolvers] = useState<ResolverInfo[]>([]);
  const [draft, setDraft] = useState<Partial<LinkSuggestion> | null>(null);
  const [linked, setLinked] = useState<Set<string>>(new Set());
  /** The first proposal starts open, so the reader sees what a link means. */
  const [previewed, setPreviewed] = useState<string | null>(null);

  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    const added = uploads.filter((u) => u.dataCollectionId);
    Promise.all(added.map((u) => identifyFile(u.file))).then((guesses) => {
      if (cancelled) return;
      const ids = added.filter((_, i) => guesses[i].kind === 'table');
      setTableIds(ids.map((u) => u.dataCollectionId as string));
    });
    return () => {
      cancelled = true;
    };
  }, [ready, uploads]);

  useEffect(() => {
    if (!tableIds || tableIds.length === 0) return;
    let cancelled = false;
    Promise.all([
      fetchLinkSuggestions(projectId, tableIds),
      fetchProject(projectId, { skipEnrichment: true }),
      listLinkResolvers(projectId).catch(() => [] as ResolverInfo[]),
    ])
      .then(([found, { project }, known]) => {
        if (cancelled) return;
        setSuggestions(found);
        setPreviewed(found[0] ? keyOf(found[0]) : null);
        setResolvers(known);
        setCollections(
          (project.workflows ?? []).flatMap((workflow) =>
            (workflow.data_collections ?? []).map((dc) => ({
              id: String(dc._id ?? dc.id ?? ''),
              tag: dc.data_collection_tag ?? '',
              type: String(dc.config?.type ?? ''),
            })),
          ),
        );
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, tableIds]);

  const firstTable = tableIds?.[0];
  const blank = useMemo(() => ({ source_dc_id: firstTable }), [firstTable]);

  if (!ready || !tableIds || tableIds.length === 0) return null;

  const count = suggestions?.length ?? 0;
  let summary = 'Looking for values your tables share with the other data';
  if (failed) summary = 'Suggestions are not available';
  else if (suggestions) {
    summary = count > 0 ? `${plural(count, 'possible link')} found` : 'No shared values found';
  }

  return (
    <>
      <SourceSection
        icon="mdi:link-variant"
        title="Link your tables"
        summary={summary}
        testId={testId}
        defaultOpen
      >
        <Stack gap="sm">
          <Text size="sm" c="dimmed">
            A link lets a filter on your table narrow the other data too.
          </Text>
          {!suggestions && !failed && <Loader size="sm" />}
          {suggestions?.map((s) => {
            const key = keyOf(s);
            const open = previewed === key;
            return (
              <Stack key={key} gap="xs" data-testid={`${testId}-row-${s.target_dc_tag}`}>
                <Group justify="space-between" wrap="nowrap">
                  <Stack gap={0} style={{ minWidth: 0 }}>
                    <Text size="sm" style={{ overflowWrap: 'anywhere' }}>
                      <b>{s.source_dc_tag}</b>, column <code>{s.source_column}</code>
                      {' to '}
                      <b>{s.target_dc_tag}</b>
                    </Text>
                    <Text size="xs" c="dimmed">
                      {s.matched} of {s.total} values found in {s.target_dc_tag}
                    </Text>
                  </Stack>
                  <Group gap="xs" wrap="nowrap">
                    <ActionIcon
                      variant="subtle"
                      color="gray"
                      onClick={() => setPreviewed(open ? null : key)}
                      aria-expanded={open}
                      aria-label={`${open ? 'Hide' : 'Show'} the values linked to ${s.target_dc_tag}`}
                      data-testid={`${testId}-preview-${s.target_dc_tag}`}
                    >
                      <Icon icon={open ? 'mdi:chevron-up' : 'mdi:chevron-down'} width={18} />
                    </ActionIcon>
                    {linked.has(key) ? (
                      <Badge variant="light" color={accent.secondary}>
                        Linked
                      </Badge>
                    ) : (
                      <Button
                        size="xs"
                        variant="light"
                        color={accent.secondary}
                        onClick={() => setDraft(s)}
                        data-testid={`${testId}-link-${s.target_dc_tag}`}
                      >
                        Link
                      </Button>
                    )}
                  </Group>
                </Group>
                <Collapse in={open}>
                  <LinkExamples suggestion={s} />
                </Collapse>
              </Stack>
            );
          })}
          <Group>
            <Button
              size="xs"
              variant="subtle"
              color="gray"
              leftSection={<Icon icon="mdi:plus" width={14} />}
              onClick={() => setDraft(blank)}
              data-testid={`${testId}-manual`}
            >
              Link it yourself
            </Button>
          </Group>
        </Stack>
      </SourceSection>
      <LinkEditModal
        opened={draft !== null}
        projectId={projectId}
        link={null}
        initial={draft}
        dataCollections={collections}
        resolvers={resolvers}
        onClose={() => setDraft(null)}
        onSaved={(link) => {
          setLinked((done) => new Set(done).add(`${link.source_dc_id}:${link.target_dc_id}`));
          setDraft(null);
        }}
      />
    </>
  );
};
