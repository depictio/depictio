import React, { useEffect, useState } from 'react';
import { Anchor, Button, CopyButton, Group, Mark, Popover, ScrollArea, Stack, Text, TextInput } from '@mantine/core';

import { StoredMetadata, TextFilterMatchesResult, fetchTextFilterMatches } from '../../api';
import { dataPinBody, isDataVersionActive, useDataVersions } from '../../dataVersions';
import { firstMatchSpan, normalizeTextFilterValue, regexError } from './textFilter';

/** More values than this and the list gets a box to narrow it. */
const SEARCH_FROM = 12;

/** One matching value, the part the pattern caught marked. */
const MatchRow: React.FC<{ value: string; span: [number, number] | null }> = ({ value, span }) => (
  <Text size="xs" ff="monospace" style={{ wordBreak: 'break-all' }}>
    {span ? (
      <>
        {value.slice(0, span[0])}
        <Mark>{value.slice(span[0], span[1])}</Mark>
        {value.slice(span[1])}
      </>
    ) : (
      value
    )}
  </Text>
);

/**
 * "4 of 122 values match", under a TextInput, and the values themselves.
 *
 * A pattern is a guess until you see what it caught: `^ACG` kept nothing and
 * the dashboard just looked empty. The count is asked of the server, which
 * applies the very predicate the filter does (a JS RegExp would read another
 * dialect), over the column's distinct values in the whole collection. The
 * list opens in a popover and copies as one value per line.
 *
 * It follows the *applied* value (the one the filter holds), so it settles
 * together with the dashboard and never counts a half-typed pattern.
 */
const TextFilterMatches: React.FC<{
  metadata: StoredMetadata;
  /** The value the filter currently applies. */
  applied: string;
}> = ({ metadata, applied }) => {
  const versionState = useDataVersions();
  const dashboardId = versionState.dashboardId;
  const pins = isDataVersionActive(versionState) ? dataPinBody(versionState) : {};
  const pinKey = JSON.stringify(pins);
  const pattern = normalizeTextFilterValue(applied);
  const [result, setResult] = useState<TextFilterMatchesResult | null>(null);
  const [failed, setFailed] = useState(false);
  const [narrow, setNarrow] = useState('');

  const dcId = metadata.dc_id;
  const column = metadata.column_name;
  const enabled =
    Boolean(dashboardId && dcId && column) &&
    pattern !== null &&
    regexError(pattern, metadata.match_mode) === null;

  useEffect(() => {
    if (!enabled || !dashboardId || !dcId || !column || pattern === null) {
      setResult(null);
      setFailed(false);
      return undefined;
    }
    const controller = new AbortController();
    setFailed(false);
    fetchTextFilterMatches(
      dashboardId,
      {
        dc_id: dcId,
        column,
        value: pattern,
        case_sensitive: metadata.case_sensitive === true,
        match_mode: metadata.match_mode ?? 'regex',
        filter_expr: metadata.filter_expr ?? null,
        ...pins,
      },
      controller.signal,
    )
      .then(setResult)
      .catch((err) => {
        if (!controller.signal.aborted) {
          setResult(null);
          setFailed(true);
          console.warn('text filter matches failed', err);
        }
      });
    return () => controller.abort();
    // `pinKey` is the content of `pins`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, dashboardId, dcId, column, pattern, metadata.case_sensitive, metadata.match_mode, metadata.filter_expr, pinKey]);

  if (!enabled || failed || !result) return null;

  const { matching, total, values, truncated } = result;
  const needle = narrow.trim().toLowerCase();
  const shown = needle ? values.filter((v) => v.toLowerCase().includes(needle)) : values;
  const noun = total === 1 ? 'value' : 'values';
  const summary =
    matching === 0
      ? `No ${column} value matches (${total} checked)`
      : `${matching} of ${total} ${noun} match`;

  return (
    <Group gap={6} wrap="nowrap" data-testid="text-filter-matches">
      <Text size="xs" c={matching === 0 ? 'red' : 'dimmed'}>
        {summary}
      </Text>
      {matching > 0 ? (
        <Popover width={400} position="bottom-start" shadow="md" withArrow onClose={() => setNarrow('')}>
          <Popover.Target>
            <Anchor component="button" type="button" size="xs">
              show
            </Anchor>
          </Popover.Target>
          <Popover.Dropdown>
            <Stack gap={6}>
              <Group justify="space-between" wrap="nowrap">
                <Text size="xs" fw={600}>
                  {matching} matching {column}
                </Text>
                <CopyButton value={values.join('\n')}>
                  {({ copied, copy }) => (
                    <Button size="compact-xs" variant="subtle" onClick={copy}>
                      {copied ? 'Copied' : 'Copy'}
                    </Button>
                  )}
                </CopyButton>
              </Group>
              {values.length > SEARCH_FROM ? (
                <TextInput
                  size="xs"
                  placeholder="Narrow this list"
                  value={narrow}
                  onChange={(e) => setNarrow(e.currentTarget.value)}
                />
              ) : null}
              <ScrollArea.Autosize mah={260}>
                <Stack gap={2}>
                  {shown.map((v) => (
                    <MatchRow
                      key={v}
                      value={v}
                      span={firstMatchSpan(v, pattern, metadata.match_mode, metadata.case_sensitive === true)}
                    />
                  ))}
                  {shown.length === 0 ? (
                    <Text size="xs" c="dimmed">
                      None of the listed values contains that.
                    </Text>
                  ) : null}
                </Stack>
              </ScrollArea.Autosize>
              {truncated ? (
                <Text size="xs" c="dimmed">
                  First {values.length} of {matching} listed; the filter still keeps all {matching}.
                </Text>
              ) : null}
            </Stack>
          </Popover.Dropdown>
        </Popover>
      ) : null}
    </Group>
  );
};

export default TextFilterMatches;
