import React, { useEffect, useRef, useState } from 'react';
import { Alert, Button, Group, List, Modal, Progress, ScrollArea, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

export interface BulkDeleteItem {
  id: string;
  /** What the user sees in the list (a name or an email). */
  label: string;
}

interface Failure {
  item: BulkDeleteItem;
  message: string;
}

interface BulkDeleteModalProps {
  opened: boolean;
  /** Plural noun for the title and the button, e.g. 'projects'. */
  noun: string;
  /** Singular noun, used when exactly one item is selected. */
  nounSingular: string;
  items: BulkDeleteItem[];
  /** Extra consequence shown under the warning (e.g. what a project delete takes with it). */
  note?: React.ReactNode;
  /** Deletes one item; throws on failure. Called sequentially. */
  onDelete: (id: string) => Promise<void>;
  /** Always called once the run ends (success or not) so the panel reloads. */
  onDone: () => void;
  onClose: () => void;
}

/**
 * Confirm-then-run modal for deleting several rows at once. Deletions run one
 * after the other; failures are listed with the server message and keep the
 * modal open, a clean run closes it.
 */
const BulkDeleteModal: React.FC<BulkDeleteModalProps> = ({
  opened,
  noun,
  nounSingular,
  items,
  note,
  onDelete,
  onDone,
  onClose,
}) => {
  const [running, setRunning] = useState(false);
  const [finished, setFinished] = useState(false);
  const [progress, setProgress] = useState(0);
  const [deleted, setDeleted] = useState(0);
  const [failures, setFailures] = useState<Failure[]>([]);
  // The list is frozen at open: the panel reloads (and prunes the selection)
  // mid-run, which must not change what the summary talks about.
  const [frozen, setFrozen] = useState<BulkDeleteItem[]>([]);
  const wasOpened = useRef(false);

  useEffect(() => {
    if (opened && !wasOpened.current) {
      setRunning(false);
      setFinished(false);
      setProgress(0);
      setDeleted(0);
      setFailures([]);
      setFrozen(items);
    }
    wasOpened.current = opened;
  }, [opened, items]);

  const list = frozen.length > 0 ? frozen : items;
  const count = list.length;
  const label = count === 1 ? nounSingular : noun;

  const run = async () => {
    setRunning(true);
    setFailures([]);
    setDeleted(0);
    const failed: Failure[] = [];
    let ok = 0;
    for (let i = 0; i < list.length; i += 1) {
      setProgress(i + 1);
      try {
        // eslint-disable-next-line no-await-in-loop
        await onDelete(list[i].id);
        ok += 1;
        setDeleted(ok);
      } catch (err) {
        failed.push({
          item: list[i],
          message: err instanceof Error ? err.message : 'Delete failed',
        });
      }
    }
    setFailures(failed);
    setRunning(false);
    setFinished(true);
    onDone();
    if (failed.length === 0) onClose();
  };

  const closeable = !running;

  return (
    <Modal
      opened={opened}
      onClose={closeable ? onClose : () => undefined}
      title={`Delete ${count} ${label}`}
      size="md"
      centered
      closeOnClickOutside={false}
      closeOnEscape={closeable}
      withCloseButton={closeable}
    >
      <Stack gap="sm">
        {!finished && (
          <>
            <Alert
              color="red"
              variant="light"
              icon={<Icon icon="mdi:alert" />}
              title="This cannot be undone."
            >
              {count === 1 ? 'This' : 'These'} {count} {label} will be deleted permanently.
            </Alert>
            {note && (
              <Text size="sm" c="dimmed">
                {note}
              </Text>
            )}
            <ScrollArea.Autosize mah={220} type="auto">
              <List size="sm" spacing={2}>
                {list.map((it) => (
                  <List.Item key={it.id}>{it.label}</List.Item>
                ))}
              </List>
            </ScrollArea.Autosize>
          </>
        )}

        {running && (
          <Stack gap={4}>
            <Text size="sm">
              Deleting {progress} of {count}
            </Text>
            <Progress value={(progress / count) * 100} animated />
          </Stack>
        )}

        {finished && (
          <>
            <Text size="sm">
              {deleted} of {count} {count === 1 ? nounSingular : noun} deleted.
            </Text>
            {failures.length > 0 && (
              <Alert
                color="red"
                variant="light"
                icon={<Icon icon="mdi:alert-circle" />}
                title={`${failures.length} failed`}
              >
                <ScrollArea.Autosize mah={200} type="auto">
                  <List size="sm" spacing={4}>
                    {failures.map((f) => (
                      <List.Item key={f.item.id}>
                        <Text span fw={600} size="sm">
                          {f.item.label}
                        </Text>
                        : {f.message}
                      </List.Item>
                    ))}
                  </List>
                </ScrollArea.Autosize>
              </Alert>
            )}
          </>
        )}

        <Group justify="flex-end" gap="xs" mt="sm">
          {finished ? (
            <Button variant="default" onClick={onClose}>
              Close
            </Button>
          ) : (
            <>
              <Button variant="subtle" onClick={onClose} disabled={running}>
                Cancel
              </Button>
              <Button
                className="gp-danger"
                color="red"
                variant="filled"
                leftSection={<Icon icon="tabler:trash" width={14} />}
                onClick={run}
                loading={running}
                disabled={count === 0}
              >
                Delete {count} {label}
              </Button>
            </>
          )}
        </Group>
      </Stack>
    </Modal>
  );
};

export default BulkDeleteModal;
