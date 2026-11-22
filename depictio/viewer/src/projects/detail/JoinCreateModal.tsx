import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  Button,
  Code,
  Group,
  Loader,
  Modal,
  MultiSelect,
  ScrollArea,
  SegmentedControl,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { notifications } from '@mantine/notifications';

import { createProjectJoin, previewProjectJoin, useBrandAccents } from 'depictio-react-core';
import type { JoinPreview } from 'depictio-react-core';

import {
  JOIN_NAME_MAX,
  JOIN_TYPE_HELP,
  JOIN_TYPE_OPTIONS,
  defaultJoinName,
  defaultJoinSelection,
  effectiveOnColumns,
  isValidJoinName,
  joinColumnsProblem,
  joinResultTag,
  joinableTables,
  previewSummary,
  readableApiError,
  rightTableOptions,
  unmatchedSentences,
  validateJoinName,
} from './joinForm';
import type { JoinHow } from './joinForm';

interface DataCollectionOption {
  id: string;
  tag: string;
  /** DC type from `config.type`; only tables can be joined. */
  type: string;
}

interface JoinCreateModalProps {
  opened: boolean;
  projectId: string;
  /** All DCs in the project; the modal keeps the tables. */
  dataCollections: DataCollectionOption[];
  /** The project's links: the first one between two tables preselects them. */
  links?: ReadonlyArray<{ source_dc_id?: string; target_dc_id?: string }>;
  /** Names of the project's joins, so the default name does not repeat one. */
  existingJoinNames?: ReadonlyArray<string>;
  onClose: () => void;
  /** Fired after the join was created so the parent can refresh. */
  onCreated: () => void;
}

const PREVIEW_DEBOUNCE_MS = 300;

const cellText = (v: unknown): string => {
  if (v === null || v === undefined) return '';
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
};

const JoinCreateModal: React.FC<JoinCreateModalProps> = ({
  opened,
  projectId,
  dataCollections,
  links = [],
  existingJoinNames = [],
  onClose,
  onCreated,
}) => {
  const accent = useBrandAccents();
  const tables = useMemo(() => joinableTables(dataCollections), [dataCollections]);

  const [name, setName] = useState('');
  // True once the user typed in the name field: from then on the name is theirs
  // (no default refresh, and an empty or bad name is reported).
  const [nameEdited, setNameEdited] = useState(false);
  const [leftId, setLeftId] = useState('');
  const [rightId, setRightId] = useState('');
  // null = the user has not picked columns: the server's suggestion applies.
  const [picked, setPicked] = useState<string[] | null>(null);
  const [how, setHow] = useState<JoinHow>('left');

  const [preview, setPreview] = useState<JoinPreview | null>(null);
  // The inputs `preview` was computed for, to tell a current one from a stale one.
  const [previewFor, setPreviewFor] = useState('');
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const requestSeq = useRef(0);
  // The tables the form last picked by itself: while the user keeps them, a
  // link or a table that arrives after opening may still change the pick.
  const autoPick = useRef<{ leftId: string; rightId: string } | null>(null);

  // Fresh form each time the modal opens.
  useEffect(() => {
    if (!opened) return;
    const d = defaultJoinSelection(tables, links);
    autoPick.current = { leftId: d.leftId, rightId: d.rightId };
    setName('');
    setNameEdited(false);
    setLeftId(d.leftId);
    setRightId(d.rightId);
    setHow(d.how);
    setPicked(d.onColumns);
    setPreview(null);
    setPreviewFor('');
    setPreviewError(null);
    setError(null);
    setSubmitting(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened]);

  // The project's links (or tables) loaded after the form opened.
  const linksKey = links.map((l) => `${l.source_dc_id}>${l.target_dc_id}`).join(',');
  const tablesKey = tables.map((t) => t.id).join(',');
  useEffect(() => {
    const auto = autoPick.current;
    if (!opened || !auto || auto.leftId !== leftId || auto.rightId !== rightId) return;
    const d = defaultJoinSelection(tables, links);
    if (d.leftId === leftId && d.rightId === rightId) return;
    autoPick.current = { leftId: d.leftId, rightId: d.rightId };
    setLeftId(d.leftId);
    setRightId(d.rightId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened, linksKey, tablesKey]);

  // Until the user edits the name, it follows the chosen tables.
  const tagOf = (id: string) => tables.find((t) => t.id === id)?.tag ?? '';
  const defaultName = defaultJoinName(tagOf(leftId), tagOf(rightId), {
    joinNames: existingJoinNames,
    tags: dataCollections.map((d) => d.tag),
  });
  useEffect(() => {
    if (opened && !nameEdited) setName(defaultName);
  }, [opened, nameEdited, defaultName]);

  const columns = effectiveOnColumns(picked, preview);
  // The user emptied the key: nothing to preview or create until one is picked.
  const keyMissing = picked !== null && columns.length === 0;
  // The preview only needs a name that can be used: an unusable one is not sent
  // (the form reports it itself).
  const sentName = isValidJoinName(name) ? name : '';
  const requestKey = JSON.stringify([sentName, leftId, rightId, picked ?? [], how]);

  // Preview whenever an input changes (debounced). Responses to anything but
  // the latest request are dropped.
  useEffect(() => {
    if (!opened || !leftId || !rightId) {
      requestSeq.current += 1;
      setPreview(null);
      setPreviewFor('');
      setPreviewLoading(false);
      setPreviewError(null);
      return;
    }
    if (picked !== null && picked.length === 0) {
      requestSeq.current += 1;
      setPreviewLoading(false);
      return;
    }
    const seq = ++requestSeq.current;
    const controller = new AbortController();
    setPreviewLoading(true);
    const timer = window.setTimeout(() => {
      previewProjectJoin(
        projectId,
        {
          name: sentName,
          left_dc_id: leftId,
          right_dc_id: rightId,
          on_columns: picked ?? [],
          how,
        },
        controller.signal,
      )
        .then((p) => {
          if (seq !== requestSeq.current) return;
          setPreview(p);
          setPreviewFor(requestKey);
          setPreviewError(null);
        })
        .catch((err: Error) => {
          if (seq !== requestSeq.current || err.name === 'AbortError') return;
          setPreview(null);
          setPreviewFor('');
          setPreviewError(readableApiError(err, 'The preview could not be computed.'));
        })
        .finally(() => {
          if (seq === requestSeq.current) setPreviewLoading(false);
        });
    }, PREVIEW_DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened, projectId, requestKey]);

  const previewCurrent = !!preview && previewFor === requestKey;
  // Why the name cannot be used: the client rules first, then what the server
  // found (a name already taken), then "empty".
  const nameProblem =
    validateJoinName(name) ??
    (previewCurrent && sentName ? preview.name_problem : null) ??
    (name === '' ? 'Give the join a name.' : null);
  // An empty name is not an error until the user has touched the field.
  const nameError = name === '' && !nameEdited ? null : nameProblem;
  const canCreate =
    previewCurrent &&
    !previewLoading &&
    !nameProblem &&
    isValidJoinName(name) &&
    columns.length > 0 &&
    !submitting;

  const tableData = tables.map((t) => ({ value: t.id, label: t.tag }));
  const rightData = rightTableOptions(tables, leftId).map((t) => ({
    value: t.id,
    label: t.tag,
  }));

  const onLeftChange = (v: string | null) => {
    setLeftId(v ?? '');
    setPicked(null);
    if (v && v === rightId) setRightId('');
  };
  const onRightChange = (v: string | null) => {
    setRightId(v ?? '');
    setPicked(null);
  };

  const handleSubmit = async () => {
    if (!canCreate) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await createProjectJoin(projectId, {
        name,
        left_dc_id: leftId,
        right_dc_id: rightId,
        on_columns: columns,
        how,
      });
      notifications.show({
        color: 'green',
        title: 'Join created',
        message: `${res.data_collection_tag || joinResultTag(name)}: ${res.rows} ${res.rows === 1 ? 'row' : 'rows'}`,
      });
      onCreated();
      onClose();
    } catch (err) {
      setError(readableApiError(err, 'The join could not be created.'));
    } finally {
      setSubmitting(false);
    }
  };

  const sentences = previewCurrent
    ? unmatchedSentences(preview.how, preview.left, preview.right)
    : [];

  return (
    <Modal
      opened={opened}
      onClose={submitting ? () => {} : onClose}
      title={null}
      size="xl"
      centered
      padding="lg"
      closeOnClickOutside={!submitting}
      closeOnEscape={!submitting}
      withCloseButton={!submitting}
    >
      <Stack gap="md" data-testid="join-create-modal">
        <Group justify="center" gap="sm">
          <Icon
            icon="mdi:table-merge-cells"
            width={32}
            color={`var(--mantine-color-${accent.secondary}-6)`}
          />
          <Title order={3} c={accent.secondary} m={0}>
            Create table join
          </Title>
        </Group>

        <Text size="sm" c="dimmed">
          Combine two tables into a new table. The two tables stay as they are, and the joined
          table is rebuilt whenever one of them changes.
        </Text>

        {error && (
          <Alert color="red" variant="light" icon={<Icon icon="mdi:alert-circle" width={18} />}>
            {error}
          </Alert>
        )}

        <TextInput
          label="Name"
          placeholder="e.g. penguins"
          value={name}
          onChange={(e) => {
            setNameEdited(true);
            setName(e.currentTarget.value);
          }}
          maxLength={JOIN_NAME_MAX + 20}
          error={nameError}
          description={
            isValidJoinName(name) ? (
              <>
                Resulting table: <Code>{joinResultTag(name)}</Code>
              </>
            ) : (
              'Letters, digits, _ and -. The table is named joined_<name>.'
            )
          }
          data-testid="join-name"
          data-autofocus
          required
        />

        <Group grow align="flex-start">
          <Select
            label="Left table"
            placeholder="Pick a table"
            data={tableData}
            value={leftId || null}
            onChange={onLeftChange}
            searchable
            allowDeselect={false}
            nothingFoundMessage="No table"
            comboboxProps={{ withinPortal: true, zIndex: 10000 }}
            data-testid="join-left"
            required
          />
          <Select
            label="Right table"
            placeholder="Pick a table"
            data={rightData}
            value={rightId || null}
            onChange={onRightChange}
            searchable
            allowDeselect={false}
            nothingFoundMessage="No other table"
            comboboxProps={{ withinPortal: true, zIndex: 10000 }}
            data-testid="join-right"
            required
          />
        </Group>

        <MultiSelect
          label="Join column(s)"
          description="Rows are matched where these columns hold the same values in both tables."
          placeholder={leftId && rightId ? 'Pick the columns to match on' : 'Pick both tables first'}
          data={preview?.shared_columns ?? columns}
          value={columns}
          onChange={(v) => setPicked(v)}
          disabled={!leftId || !rightId}
          searchable
          clearable={false}
          error={keyMissing ? joinColumnsProblem(columns) : null}
          nothingFoundMessage="No shared column"
          comboboxProps={{ withinPortal: true, zIndex: 10000 }}
          data-testid="join-columns"
          required
        />

        <Stack gap={6}>
          <Text size="sm" fw={500}>
            Join type
          </Text>
          <SegmentedControl
            value={how}
            onChange={(v) => setHow(v as JoinHow)}
            data={JOIN_TYPE_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
            fullWidth
            data-testid="join-type"
          />
          <Text size="sm" c="dimmed" data-testid="join-type-help">
            {JOIN_TYPE_HELP[how]}
          </Text>
        </Stack>

        <Stack gap="xs" data-testid="join-preview">
          <Group gap="xs">
            <Text fw={600} size="sm">
              Preview
            </Text>
            {previewLoading && <Loader size="xs" />}
          </Group>

          {!leftId || !rightId ? (
            <Text size="sm" c="dimmed">
              Pick both tables to preview the joined table.
            </Text>
          ) : keyMissing ? (
            <Text size="sm" c="dimmed" data-testid="join-preview-no-key">
              {joinColumnsProblem(columns)}
            </Text>
          ) : previewError ? (
            <Alert
              color="red"
              variant="light"
              icon={<Icon icon="mdi:alert-circle" width={18} />}
              data-testid="join-preview-error"
            >
              {previewError}
            </Alert>
          ) : preview ? (
            <Stack gap="xs" opacity={previewCurrent ? 1 : 0.6}>
              <Text size="sm" fw={500} data-testid="join-preview-summary">
                {previewSummary(preview)}
              </Text>
              {sentences.map((s) => (
                <Text key={s} size="sm" c="dimmed">
                  {s}
                </Text>
              ))}
              {preview.warnings.map((w) => (
                <Alert
                  key={w}
                  color="yellow"
                  variant="light"
                  icon={<Icon icon="mdi:alert-outline" width={18} />}
                  p="xs"
                >
                  {w}
                </Alert>
              ))}
              {preview.sample_rows.length > 0 && (
                <ScrollArea.Autosize mah={240} type="auto" offsetScrollbars>
                  <Table verticalSpacing={4} striped fz="xs" stickyHeader>
                    <Table.Thead>
                      <Table.Tr>
                        {preview.joined_columns.map((c) => (
                          <Table.Th key={c} style={{ whiteSpace: 'nowrap' }}>
                            {c}
                          </Table.Th>
                        ))}
                      </Table.Tr>
                    </Table.Thead>
                    <Table.Tbody>
                      {preview.sample_rows.map((row, i) => (
                        <Table.Tr key={i}>
                          {preview.joined_columns.map((c) => (
                            <Table.Td key={c} style={{ whiteSpace: 'nowrap' }}>
                              {cellText(row[c])}
                            </Table.Td>
                          ))}
                        </Table.Tr>
                      ))}
                    </Table.Tbody>
                  </Table>
                </ScrollArea.Autosize>
              )}
            </Stack>
          ) : (
            !previewLoading && (
              <Text size="sm" c="dimmed">
                No preview yet.
              </Text>
            )
          )}
        </Stack>

        <Group justify="flex-end" mt="md" gap="xs">
          <Button variant="default" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button
            color={accent.secondary}
            onClick={handleSubmit}
            loading={submitting}
            disabled={!canCreate}
            leftSection={<Icon icon="mdi:plus" width={16} />}
            data-testid="join-create-btn"
          >
            Create join
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
};

export default JoinCreateModal;
