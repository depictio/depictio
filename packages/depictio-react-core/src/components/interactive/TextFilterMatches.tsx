import React, { useEffect, useState } from 'react';
import { Anchor, Badge, Box, Button, CopyButton, Group, Mark, Popover, ScrollArea, Stack, Text, TextInput } from '@mantine/core';

import { StoredMetadata, TextFilterMatchesResult, fetchTextFilterMatches } from '../../api';
import { dataPinBody, isDataVersionActive, useDataVersions } from '../../dataVersions';
import {
  MARK_COLORS,
  countAlternativeHits,
  markMatches,
  normalizeTextFilterValue,
  regexError,
  splitAlternatives,
} from './textFilter';

/** Wait after the last keystroke before the count is asked (the dashboard's own wait is longer). */
const LIVE_DEBOUNCE_MS = 200;

/** More values than this and the list gets a box to narrow it. */
const SEARCH_FROM = 12;

const markColor = (alt: number) => MARK_COLORS[alt % MARK_COLORS.length];

/** One matching value, every part a pattern caught marked in that pattern's colour. */
const MatchRow: React.FC<{ pieces: ReturnType<typeof markMatches> }> = ({ pieces }) => (
  <Text size="xs" ff="monospace" style={{ whiteSpace: 'nowrap' }}>
    {pieces.map((piece, i) =>
      piece.alt === null ? (
        <React.Fragment key={i}>{piece.text}</React.Fragment>
      ) : (
        <Mark key={i} color={markColor(piece.alt)}>
          {piece.text}
        </Mark>
      ),
    )}
  </Text>
);

/** Columns a list of this length is laid out in, so a short value is not
 *  stranded at the left of a wide, mostly empty box. */
const columnsFor = (n: number) => (n > 24 ? 3 : n > 10 ? 2 : 1);

/**
 * "4 of 122 values match", under a TextInput, and the values themselves.
 *
 * A pattern is a guess until you see what it caught: `^ACG` kept nothing and
 * the dashboard just looked empty. The count is asked of the server, which
 * applies the very predicate the filter does (a JS RegExp would read another
 * dialect), over the column's distinct values in the whole collection. The
 * list opens in a popover and copies as one value per line.
 *
 * It follows what is typed, a beat after the last keystroke and ahead of the
 * dashboard, so the list and its marks update while you write. A pattern with
 * several top-level alternatives (`^CCA|GG$`) marks each in its own colour,
 * with one chip per alternative saying how many of the listed values it
 * catches.
 */
const TextFilterMatches: React.FC<{
  metadata: StoredMetadata;
  /** What is typed in the box, not yet necessarily applied. */
  pattern: string;
}> = ({ metadata, pattern: typed }) => {
  const versionState = useDataVersions();
  const dashboardId = versionState.dashboardId;
  const pins = isDataVersionActive(versionState) ? dataPinBody(versionState) : {};
  const pinKey = JSON.stringify(pins);
  const [settledText, setSettledText] = useState(typed);
  useEffect(() => {
    const timer = setTimeout(() => setSettledText(typed), LIVE_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [typed]);
  const pattern = normalizeTextFilterValue(settledText);
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
  const noun = total === 1 ? 'value' : 'values';
  const summary =
    matching === 0
      ? `No ${column} value matches (${total} checked)`
      : `${matching} of ${total} ${noun} match`;
  const caseSensitive = metadata.case_sensitive === true;
  const alternatives = splitAlternatives(pattern ?? '', metadata.match_mode);
  const hits =
    alternatives.length > 1
      ? countAlternativeHits(values, alternatives, metadata.match_mode, caseSensitive)
      : [];
  const needle = narrow.trim().toLowerCase();
  const shown = needle ? values.filter((v) => v.toLowerCase().includes(needle)) : values;
  const columns = columnsFor(shown.length);

  return (
    <Group gap={6} wrap="nowrap" data-testid="text-filter-matches">
      <Text size="xs" c={matching === 0 ? 'red' : 'dimmed'}>
        {summary}
      </Text>
      {matching > 0 ? (
        <Popover
          width="max-content"
          position="bottom-start"
          shadow="md"
          withArrow
          onClose={() => setNarrow('')}
        >
          <Popover.Target>
            <Anchor component="button" type="button" size="xs">
              show
            </Anchor>
          </Popover.Target>
          <Popover.Dropdown maw="min(720px, 92vw)" miw={240}>
            <Stack gap={8}>
              <Group justify="space-between" wrap="nowrap" gap="lg">
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
              {hits.length > 0 ? (
                <Group gap={6}>
                  {alternatives.map((alternative, i) => (
                    <Badge
                      key={`${i}:${alternative}`}
                      size="sm"
                      variant="light"
                      color={markColor(i)}
                      tt="none"
                      ff="monospace"
                      title={`${hits[i]} of the ${values.length} listed values`}
                    >
                      {alternative} · {hits[i]}
                    </Badge>
                  ))}
                </Group>
              ) : null}
              {values.length > SEARCH_FROM ? (
                <TextInput
                  size="xs"
                  placeholder="Narrow this list"
                  value={narrow}
                  onChange={(e) => setNarrow(e.currentTarget.value)}
                />
              ) : null}
              <ScrollArea.Autosize mah={260}>
                {shown.length === 0 ? (
                  <Text size="xs" c="dimmed">
                    None of the listed values contains that.
                  </Text>
                ) : (
                  <Box
                    style={{
                      display: 'grid',
                      gridAutoFlow: 'column',
                      gridTemplateRows: `repeat(${Math.ceil(shown.length / columns)}, auto)`,
                      gridAutoColumns: 'max-content',
                      columnGap: 20,
                      rowGap: 2,
                    }}
                  >
                    {shown.map((v) => (
                      <MatchRow
                        key={v}
                        pieces={markMatches(v, alternatives, metadata.match_mode, caseSensitive)}
                      />
                    ))}
                  </Box>
                )}
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
