import React, { useState } from 'react';
import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Divider,
  Group,
  List,
  Menu,
  Paper,
  Stack,
  Switch,
  Text,
  Textarea,
  Tooltip,
  UnstyledButton,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { notifications } from '@mantine/notifications';
import {
  addThreadComment,
  deleteCommentThread,
  deleteThreadComment,
  editThreadComment,
  numberBadge,
  reviewCommentThread,
  updateCommentThread,
  Z_LAYERS,
} from 'depictio-react-core';
import type { CommentAuthor, CommentThread, ThreadComment } from 'depictio-react-core';

import type { CurrentUser } from '../../hooks/useCurrentUser';
import { formatDateTime, formatRelativeTime } from '../../lib/datetime';
import { selectionHint } from './viewState';

export interface ThreadCardProps {
  thread: CommentThread;
  currentUser: CurrentUser | null;
  focused: boolean;
  /** Header click: scroll to the component and restore the thread's view. */
  onFocus: (thread: CommentThread) => void;
  /** The server's updated copy of the thread after a mutation. */
  onChange: (thread: CommentThread) => void;
  onDeleted: (threadId: string) => void;
}

function notifyError(title: string, err: unknown) {
  notifications.show({
    color: 'red',
    title,
    message: err instanceof Error ? err.message : String(err),
  });
}

function isOwn(author: CommentAuthor, user: CurrentUser | null): boolean {
  if (!user || author.kind !== 'human') return false;
  if (user.id && author.user_id === user.id) return true;
  return Boolean(author.email && author.email === user.email);
}

const AuthorLine: React.FC<{ author: CommentAuthor; at: string; editedAt?: string | null }> = ({
  author,
  at,
  editedAt,
}) => (
  <Group gap={6} wrap="wrap">
    {author.kind === 'agent' && author.agent ? (
      <>
        <Badge size="xs" color="violet" variant="light" leftSection={<Icon icon="mdi:robot-outline" width={11} />}>
          Agent
        </Badge>
        <Text size="xs" fw={600}>
          {author.agent.name}
        </Text>
        <Text size="xs" c="dimmed">
          on behalf of {author.email || author.agent.on_behalf_of || author.user_id}
        </Text>
      </>
    ) : (
      <Text size="xs" fw={600}>
        {author.email || author.user_id}
      </Text>
    )}
    <Tooltip label={formatDateTime(at)} withArrow zIndex={Z_LAYERS.tooltip}>
      <Text size="xs" c="dimmed">
        {formatRelativeTime(at)}
        {editedAt ? ' (edited)' : ''}
      </Text>
    </Tooltip>
  </Group>
);

const CommentItem: React.FC<{
  thread: CommentThread;
  comment: ThreadComment;
  own: boolean;
  onChange: (thread: CommentThread) => void;
}> = ({ thread, comment, own, onChange }) => {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(comment.body);
  const [busy, setBusy] = useState(false);

  const save = async () => {
    const body = draft.trim();
    if (!body) return;
    setBusy(true);
    try {
      onChange(await editThreadComment(thread.id, comment.id, body));
      setEditing(false);
    } catch (err) {
      notifyError('Could not edit comment', err);
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    try {
      const updated = await deleteThreadComment(thread.id, comment.id);
      onChange(
        updated ?? {
          ...thread,
          comments: thread.comments.map((c) => (c.id === comment.id ? { ...c, deleted: true } : c)),
        },
      );
    } catch (err) {
      notifyError('Could not delete comment', err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Box>
      <Group justify="space-between" wrap="nowrap" align="flex-start" gap={4}>
        <AuthorLine author={comment.author} at={comment.created_at} editedAt={comment.edited_at} />
        {own && !comment.deleted && !editing && (
          <Menu position="bottom-end" withinPortal zIndex={Z_LAYERS.tooltip}>
            <Menu.Target>
              <ActionIcon variant="subtle" color="gray" size="xs" aria-label="Comment actions" loading={busy}>
                <Icon icon="mdi:dots-horizontal" width={14} />
              </ActionIcon>
            </Menu.Target>
            <Menu.Dropdown>
              <Menu.Item
                leftSection={<Icon icon="mdi:pencil-outline" width={14} />}
                onClick={() => {
                  setDraft(comment.body);
                  setEditing(true);
                }}
              >
                Edit
              </Menu.Item>
              <Menu.Item
                color="red"
                leftSection={<Icon icon="mdi:delete-outline" width={14} />}
                onClick={remove}
              >
                Delete
              </Menu.Item>
            </Menu.Dropdown>
          </Menu>
        )}
      </Group>
      {comment.deleted ? (
        <Text size="sm" c="dimmed" fs="italic">
          Comment deleted
        </Text>
      ) : editing ? (
        <Stack gap={4} mt={4}>
          <Textarea
            size="xs"
            autosize
            minRows={2}
            maxRows={8}
            value={draft}
            onChange={(e) => setDraft(e.currentTarget.value)}
            maxLength={4000}
            autoFocus
          />
          <Group gap={6} justify="flex-end">
            <Button size="compact-xs" variant="subtle" color="gray" onClick={() => setEditing(false)}>
              Cancel
            </Button>
            <Button size="compact-xs" onClick={save} loading={busy} disabled={!draft.trim()}>
              Save
            </Button>
          </Group>
        </Stack>
      ) : (
        <Text size="sm" style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
          {comment.body}
        </Text>
      )}
    </Box>
  );
};

/**
 * One comment thread in the drawer: its annotation dot, author, staleness
 * flags, the discussion, and the actions that apply to its status.
 */
const ThreadCard: React.FC<ThreadCardProps> = ({
  thread,
  currentUser,
  focused,
  onFocus,
  onChange,
  onDeleted,
}) => {
  const [reply, setReply] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const [rejecting, setRejecting] = useState(false);
  const [rejectReason, setRejectReason] = useState('');
  const [confirmDelete, setConfirmDelete] = useState(false);

  const run = async (key: string, title: string, fn: () => Promise<void>) => {
    setBusy(key);
    try {
      await fn();
    } catch (err) {
      notifyError(title, err);
    } finally {
      setBusy(null);
    }
  };

  const { annotation, staleness, status } = thread;
  const proposed = status === 'proposed';
  const hint = selectionHint(thread.anchor.view_state?.selection);
  const filterCount = thread.anchor.view_state?.filters?.length ?? 0;

  const postReply = () =>
    run('reply', 'Could not post reply', async () => {
      const body = reply.trim();
      if (!body) return;
      onChange(await addThreadComment(thread.id, body));
      setReply('');
    });

  return (
    <Paper
      withBorder
      radius="md"
      p="sm"
      shadow={focused ? 'sm' : undefined}
      style={
        focused ? { borderColor: 'var(--mantine-primary-color-filled)' } : undefined
      }
      data-thread-id={thread.id}
    >
      <Stack gap="xs">
        <UnstyledButton
          onClick={() => onFocus(thread)}
          aria-label="Show this comment on the dashboard"
          style={{ display: 'block', width: '100%' }}
        >
          <Stack gap={6}>
            {annotation && (
              <Group gap={6} wrap="nowrap">
                <Badge
                  color={annotation.color ?? 'yellow'}
                  variant="filled"
                  size="md"
                  radius="xl"
                  style={{ flexShrink: 0 }}
                >
                  {thread.number != null ? numberBadge(thread.number) : '•'}
                </Badge>
                <Text size="sm" fw={600} lineClamp={2}>
                  {annotation.label}
                </Text>
              </Group>
            )}
            <AuthorLine author={thread.created_by} at={thread.created_at} />
            <Group gap={4} wrap="wrap">
              {status === 'resolved' && (
                <Badge size="xs" color="teal" variant="light">
                  Resolved
                </Badge>
              )}
              {proposed && (
                <Badge size="xs" color="violet" variant="light">
                  Proposed
                </Badge>
              )}
              {status === 'rejected' && (
                <Badge size="xs" color="red" variant="light">
                  Rejected
                </Badge>
              )}
              {staleness?.component_missing && (
                <Badge size="xs" color="gray" variant="light">
                  Component removed
                </Badge>
              )}
              {!staleness?.component_missing && staleness?.component_changed && (
                <Tooltip label="The component was edited since this comment" withArrow zIndex={Z_LAYERS.tooltip}>
                  <Badge size="xs" color="orange" variant="light">
                    Component changed
                  </Badge>
                </Tooltip>
              )}
              {staleness?.data_changed && (
                <Tooltip label="The data was re-ingested since this comment" withArrow zIndex={Z_LAYERS.tooltip}>
                  <Badge size="xs" color="orange" variant="light">
                    Data changed
                  </Badge>
                </Tooltip>
              )}
              {hint && (
                <Badge
                  size="xs"
                  color="gray"
                  variant="outline"
                  leftSection={<Icon icon="mdi:selection-drag" width={11} />}
                >
                  {hint}
                </Badge>
              )}
              {filterCount > 0 && (
                <Badge
                  size="xs"
                  color="gray"
                  variant="outline"
                  leftSection={<Icon icon="mdi:filter-outline" width={11} />}
                >
                  {filterCount} filter{filterCount === 1 ? '' : 's'}
                </Badge>
              )}
            </Group>
          </Stack>
        </UnstyledButton>

        {thread.evidence && thread.evidence.length > 0 && (
          <Box>
            <Text size="xs" c="dimmed" fw={600}>
              Evidence
            </Text>
            <List size="xs" spacing={2}>
              {thread.evidence.map((ev, i) => (
                <List.Item key={i}>{ev.claim}</List.Item>
              ))}
            </List>
          </Box>
        )}

        {thread.review?.decision === 'rejected' && thread.review.reason && (
          <Text size="xs" c="dimmed">
            Rejected: {thread.review.reason}
          </Text>
        )}

        {thread.comments.length > 0 && (
          <Stack gap="xs">
            {thread.comments.map((c, i) => (
              <React.Fragment key={c.id}>
                {i > 0 && <Divider variant="dashed" />}
                <CommentItem
                  thread={thread}
                  comment={c}
                  own={isOwn(c.author, currentUser)}
                  onChange={onChange}
                />
              </React.Fragment>
            ))}
          </Stack>
        )}

        {status !== 'rejected' && (
          <Group gap={6} align="flex-end" wrap="nowrap">
            <Textarea
              size="xs"
              autosize
              minRows={1}
              maxRows={6}
              placeholder="Reply…"
              value={reply}
              onChange={(e) => setReply(e.currentTarget.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) void postReply();
              }}
              maxLength={4000}
              style={{ flex: 1 }}
              aria-label="Reply"
            />
            <Button
              size="xs"
              variant="light"
              onClick={postReply}
              loading={busy === 'reply'}
              disabled={!reply.trim()}
            >
              Reply
            </Button>
          </Group>
        )}

        {annotation && (
          <Tooltip
            label="Accept the proposal before showing it to viewers"
            disabled={!proposed}
            withArrow
            zIndex={Z_LAYERS.tooltip}
          >
            <Box>
              <Switch
                size="xs"
                label="Visible to viewers"
                checked={Boolean(annotation.published)}
                disabled={proposed || status === 'rejected' || busy === 'publish'}
                onChange={(e) => {
                  const published = e.currentTarget.checked;
                  void run('publish', 'Could not change visibility', async () => {
                    onChange(await updateCommentThread(thread.id, { annotation: { published } }));
                  });
                }}
              />
            </Box>
          </Tooltip>
        )}

        {rejecting && (
          <Stack gap={4}>
            <Textarea
              size="xs"
              autosize
              minRows={2}
              maxRows={5}
              placeholder="Reason (optional)"
              value={rejectReason}
              onChange={(e) => setRejectReason(e.currentTarget.value)}
              maxLength={1000}
              autoFocus
            />
            <Group gap={6} justify="flex-end">
              <Button size="compact-xs" variant="subtle" color="gray" onClick={() => setRejecting(false)}>
                Cancel
              </Button>
              <Button
                size="compact-xs"
                color="red"
                loading={busy === 'reject'}
                onClick={() =>
                  run('reject', 'Could not reject proposal', async () => {
                    onChange(
                      await reviewCommentThread(thread.id, 'rejected', rejectReason.trim() || undefined),
                    );
                    setRejecting(false);
                    setRejectReason('');
                  })
                }
              >
                Reject
              </Button>
            </Group>
          </Stack>
        )}

        {confirmDelete && (
          <Group gap={6} justify="space-between" wrap="nowrap">
            <Text size="xs" c="red">
              Delete this thread and all its replies?
            </Text>
            <Group gap={6} wrap="nowrap">
              <Button size="compact-xs" variant="subtle" color="gray" onClick={() => setConfirmDelete(false)}>
                Cancel
              </Button>
              <Button
                size="compact-xs"
                color="red"
                loading={busy === 'delete'}
                onClick={() =>
                  run('delete', 'Could not delete thread', async () => {
                    await deleteCommentThread(thread.id);
                    onDeleted(thread.id);
                  })
                }
              >
                Delete
              </Button>
            </Group>
          </Group>
        )}

        <Group gap={6} justify="space-between">
          <Group gap={6}>
            {proposed && !rejecting && (
              <>
                <Button
                  size="compact-xs"
                  color="teal"
                  variant="light"
                  leftSection={<Icon icon="mdi:check" width={12} />}
                  loading={busy === 'accept'}
                  onClick={() =>
                    run('accept', 'Could not accept proposal', async () => {
                      onChange(await reviewCommentThread(thread.id, 'accepted'));
                    })
                  }
                >
                  Accept
                </Button>
                <Button
                  size="compact-xs"
                  color="red"
                  variant="subtle"
                  leftSection={<Icon icon="mdi:close" width={12} />}
                  onClick={() => setRejecting(true)}
                >
                  Reject
                </Button>
              </>
            )}
            {(status === 'open' || status === 'resolved') && (
              <Button
                size="compact-xs"
                variant="subtle"
                color={status === 'open' ? 'teal' : 'gray'}
                leftSection={
                  <Icon
                    icon={status === 'open' ? 'mdi:check-circle-outline' : 'mdi:restore'}
                    width={12}
                  />
                }
                loading={busy === 'status'}
                onClick={() =>
                  run('status', 'Could not update thread', async () => {
                    onChange(
                      await updateCommentThread(thread.id, {
                        status: status === 'open' ? 'resolved' : 'open',
                      }),
                    );
                  })
                }
              >
                {status === 'open' ? 'Resolve' : 'Reopen'}
              </Button>
            )}
          </Group>
          <Menu position="bottom-end" withinPortal zIndex={Z_LAYERS.tooltip}>
            <Menu.Target>
              <ActionIcon variant="subtle" color="gray" size="sm" aria-label="Thread actions">
                <Icon icon="mdi:dots-vertical" width={14} />
              </ActionIcon>
            </Menu.Target>
            <Menu.Dropdown>
              <Menu.Item
                leftSection={<Icon icon="mdi:crosshairs-gps" width={14} />}
                onClick={() => onFocus(thread)}
              >
                Show on dashboard
              </Menu.Item>
              <Menu.Item
                color="red"
                leftSection={<Icon icon="mdi:delete-outline" width={14} />}
                onClick={() => setConfirmDelete(true)}
              >
                Delete thread
              </Menu.Item>
            </Menu.Dropdown>
          </Menu>
        </Group>
      </Stack>
    </Paper>
  );
};

export default ThreadCard;
