import React, { useState } from 'react';
import {
  ActionIcon,
  Avatar,
  Badge,
  Box,
  Button,
  Divider,
  Group,
  List,
  Paper,
  Stack,
  Switch,
  Text,
  Textarea,
  Tooltip,
  UnstyledButton,
  useComputedColorScheme,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { notifications } from '@mantine/notifications';
import {
  addThreadComment,
  AnnotationEditor,
  annotationColorValue,
  annotationSummary,
  DEFAULT_COLOR,
  deleteCommentThread,
  deleteThreadComment,
  editThreadComment,
  numberBadge,
  reviewCommentThread,
  updateCommentThread,
  useAnnotationLayer,
  Z_LAYERS,
} from 'depictio-react-core';
import type {
  AnnotationPatchInput,
  AnnotationStats,
  CommentAuthor,
  CommentThread,
  ThreadComment,
} from 'depictio-react-core';

import type { CurrentUser } from '../../hooks/useCurrentUser';
import { useUiStore } from '../../store/useUiStore';
import { formatDateTime, formatRelativeTime } from '../../lib/datetime';
import { selectionHint } from './viewState';

export interface ThreadCardProps {
  thread: CommentThread;
  currentUser: CurrentUser | null;
  focused: boolean;
  /** What the chart measured of this thread's annotation, once drawn. */
  stats?: AnnotationStats;
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

function sameAuthor(a: CommentAuthor, b: CommentAuthor): boolean {
  return a.kind === b.kind && a.user_id === b.user_id && a.agent?.name === b.agent?.name;
}

/** Tooltips inside the drawer: portalled, below and wrapped, so a long label
 *  near the drawer's edge never runs off it. */
const DRAWER_TOOLTIP = {
  withArrow: true,
  withinPortal: true,
  multiline: true,
  w: 220,
  position: 'bottom' as const,
  zIndex: Z_LAYERS.tooltip,
};

/** Initials from the email's local part ("jane.doe@x" gives "JD"). */
function avatarName(author: CommentAuthor): string {
  const base = (author.email || author.user_id || '?').split('@')[0];
  return base.replace(/[._-]+/g, ' ').trim() || '?';
}

const AuthorAvatar: React.FC<{ author: CommentAuthor }> = ({ author }) =>
  author.kind === 'agent' ? (
    <Avatar size="sm" radius="xl" color="violet" variant="light" aria-hidden>
      <Icon icon="mdi:robot-outline" width={16} />
    </Avatar>
  ) : (
    <Avatar size="sm" radius="xl" name={avatarName(author)} color="initials" aria-hidden />
  );

/** Avatar, author and relative time on one line; `right` sits at its end. */
const AuthorLine: React.FC<{
  author: CommentAuthor;
  at: string;
  editedAt?: string | null;
  right?: React.ReactNode;
}> = ({ author, at, editedAt, right }) => {
  const agent = author.kind === 'agent' && author.agent ? author.agent : null;
  return (
    <Group gap="xs" wrap="nowrap" align="center">
      <AuthorAvatar author={author} />
      <Box style={{ flex: 1, minWidth: 0 }}>
        <Group gap={6} wrap="nowrap">
          <Text size="xs" fw={600} truncate>
            {agent ? agent.name : author.email || author.user_id}
          </Text>
          <Tooltip label={formatDateTime(at)} {...DRAWER_TOOLTIP} w="auto">
            <Text size="xs" c="dimmed" style={{ flexShrink: 0 }}>
              {formatRelativeTime(at)}
              {editedAt ? ' (edited)' : ''}
            </Text>
          </Tooltip>
        </Group>
        {agent && (
          <Text size="xs" c="dimmed" truncate>
            Agent on behalf of {author.email || agent.on_behalf_of || author.user_id}
          </Text>
        )}
      </Box>
      {right}
    </Group>
  );
};

/** Left inset of comment bodies, so they line up with the author's name
 *  rather than with the avatar (sm avatar + xs gap). */
const BODY_INSET = 36;

const CommentItem: React.FC<{
  thread: CommentThread;
  comment: ThreadComment;
  own: boolean;
  /** The thread's header already names this author (its opening comment). */
  hideAuthor?: boolean;
  onChange: (thread: CommentThread) => void;
}> = ({ thread, comment, own, hideAuthor = false, onChange }) => {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(comment.body);
  const [busy, setBusy] = useState(false);
  const [hovered, setHovered] = useState(false);

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

  // Own-comment actions stay dimmed until the row is hovered or focused, so
  // they are always reachable (keyboard, touch) without cluttering the thread.
  const showActions = own && !comment.deleted && !editing;
  const actions = showActions ? (
    <Group
      gap={2}
      wrap="nowrap"
      style={{ opacity: hovered || busy ? 1 : 0.35, transition: 'opacity 120ms ease', flexShrink: 0 }}
    >
      <Tooltip label="Edit comment" {...DRAWER_TOOLTIP} w="auto">
        <ActionIcon
          variant="subtle"
          color="gray"
          size="xs"
          aria-label="Edit comment"
          disabled={busy}
          onClick={() => {
            setDraft(comment.body);
            setEditing(true);
          }}
        >
          <Icon icon="mdi:pencil-outline" width={13} />
        </ActionIcon>
      </Tooltip>
      <Tooltip label="Delete comment" {...DRAWER_TOOLTIP} w="auto">
        <ActionIcon
          variant="subtle"
          color="red"
          size="xs"
          aria-label="Delete comment"
          loading={busy}
          onClick={remove}
        >
          <Icon icon="mdi:delete-outline" width={13} />
        </ActionIcon>
      </Tooltip>
    </Group>
  ) : null;

  return (
    <Box
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onFocus={() => setHovered(true)}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setHovered(false);
      }}
    >
      {!hideAuthor && (
        <AuthorLine
          author={comment.author}
          at={comment.created_at}
          editedAt={comment.edited_at}
          right={actions}
        />
      )}
      <Group gap={4} wrap="nowrap" align="flex-start" pl={BODY_INSET} mt={hideAuthor ? 0 : 2}>
        <Box style={{ flex: 1, minWidth: 0 }}>
          {comment.deleted ? (
            <Text size="sm" c="dimmed" fs="italic">
              Comment deleted
            </Text>
          ) : editing ? (
            <Stack gap={4}>
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
              {hideAuthor && comment.edited_at && (
                <Text span size="xs" c="dimmed">
                  {' '}
                  (edited)
                </Text>
              )}
            </Text>
          )}
        </Box>
        {hideAuthor && actions}
      </Group>
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
  stats,
  onFocus,
  onChange,
  onDeleted,
}) => {
  const [reply, setReply] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const [rejecting, setRejecting] = useState(false);
  const [rejectReason, setRejectReason] = useState('');
  const [confirmDelete, setConfirmDelete] = useState(false);
  // In the store so that clicking the annotation on its chart opens this
  // editor; one annotation editor is open at a time.
  const editingAnnotation = useUiStore((s) => s.editingAnnotationThreadId === thread.id);
  const setEditingId = useUiStore((s) => s.setEditingAnnotation);
  const closeEditor = () => {
    if (useUiStore.getState().editingAnnotationThreadId === thread.id) setEditingId(null);
  };
  // The editor's unsaved changes are drawn live on the chart; it clears them
  // itself when it closes.
  const setEditDraft = useAnnotationLayer()?.setEditDraft;
  const colorScheme = useComputedColorScheme('light');

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
  // The drawer is only shown to editors and owners, so any of them may edit.
  const canEditAnnotation = Boolean(annotation) && status !== 'rejected';
  const summary = annotation ? annotationSummary(annotation, stats) : '';
  // Same default-palette value as the mark on the chart (a brand theme may
  // remap the Mantine palette names onto data colours).
  const annotationColor = annotation
    ? annotationColorValue(annotation.color ?? DEFAULT_COLOR, colorScheme)
    : undefined;
  const missing =
    stats?.expected != null && stats.found != null && stats.found < stats.expected
      ? `${stats.found} of ${stats.expected} found`
      : null;

  // Rethrows so the editor stays open (with the user's changes) on failure.
  const saveAnnotation = async (patch: AnnotationPatchInput) => {
    try {
      onChange(await updateCommentThread(thread.id, { annotation: patch }));
      closeEditor();
    } catch (err) {
      notifyError('Could not update annotation', err);
      throw err;
    }
  };

  // The thread's author already heads the card: when they also wrote the
  // opening comment, its body goes straight under that header.
  const first = thread.comments[0];
  const opening = first && sameAuthor(first.author, thread.created_by) ? first : null;
  const replies = opening ? thread.comments.slice(1) : thread.comments;

  const statusBadge =
    status === 'resolved' ? (
      <Badge size="xs" color="teal" variant="light" style={{ flexShrink: 0 }}>
        Resolved
      </Badge>
    ) : proposed ? (
      <Badge size="xs" color="violet" variant="light" style={{ flexShrink: 0 }}>
        Proposed
      </Badge>
    ) : status === 'rejected' ? (
      <Badge size="xs" color="red" variant="light" style={{ flexShrink: 0 }}>
        Rejected
      </Badge>
    ) : null;

  // Staleness first (it changes how the thread should be read), then what
  // the thread captured of the view.
  const contextBadges: React.ReactNode[] = [];
  if (staleness?.component_missing) {
    contextBadges.push(
      <Tooltip key="missing" label="The component was removed from the dashboard" {...DRAWER_TOOLTIP}>
        <Badge
          size="xs"
          color="gray"
          variant="light"
          leftSection={<Icon icon="mdi:puzzle-remove-outline" width={11} />}
        >
          Component removed
        </Badge>
      </Tooltip>,
    );
  } else if (staleness?.component_changed) {
    contextBadges.push(
      <Tooltip key="component" label="The component was edited since this comment" {...DRAWER_TOOLTIP}>
        <Badge
          size="xs"
          color="orange"
          variant="light"
          leftSection={<Icon icon="mdi:pencil-ruler" width={11} />}
        >
          Component changed
        </Badge>
      </Tooltip>,
    );
  }
  if (staleness?.data_changed) {
    contextBadges.push(
      <Tooltip key="data" label="The data was re-ingested since this comment" {...DRAWER_TOOLTIP}>
        <Badge
          size="xs"
          color="orange"
          variant="light"
          leftSection={<Icon icon="mdi:database-refresh-outline" width={11} />}
        >
          Data changed
        </Badge>
      </Tooltip>,
    );
  }
  if (thread.created_by.kind === 'agent' && thread.human_edited) {
    contextBadges.push(
      <Tooltip key="edited" label="A person changed this agent proposal" {...DRAWER_TOOLTIP}>
        <Badge
          size="xs"
          color="blue"
          variant="light"
          leftSection={<Icon icon="mdi:account-edit-outline" width={11} />}
        >
          Edited by a human
        </Badge>
      </Tooltip>,
    );
  }
  if (hint) {
    contextBadges.push(
      <Badge
        key="selection"
        size="xs"
        color="gray"
        variant="outline"
        leftSection={<Icon icon="mdi:selection-drag" width={11} />}
      >
        {hint}
      </Badge>,
    );
  }
  if (filterCount > 0) {
    contextBadges.push(
      <Badge
        key="filters"
        size="xs"
        color="gray"
        variant="outline"
        leftSection={<Icon icon="mdi:filter-outline" width={11} />}
      >
        {filterCount} filter{filterCount === 1 ? '' : 's'}
      </Badge>,
    );
  }

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
      style={{
        // Room for the drawer's sticky group header when scrolled into view.
        scrollMarginTop: 40,
        ...(focused ? { borderColor: 'var(--mantine-primary-color-filled)' } : null),
        // Annotations carry their colour down the card's edge, so a card and
        // its mark on the chart read as one thing.
        ...(annotationColor ? { borderLeft: `3px solid ${annotationColor}` } : null),
      }}
      data-thread-id={thread.id}
    >
      <Stack gap="xs">
        {annotation && (
          <Group gap={6} wrap="nowrap" justify="space-between" align="flex-start">
            <UnstyledButton
              onClick={() => onFocus(thread)}
              aria-label="Show this annotation on the dashboard"
              style={{ minWidth: 0, flex: 1 }}
            >
              <Group gap="xs" wrap="nowrap" align="flex-start">
                <Badge
                  color={annotationColor}
                  autoContrast
                  variant="filled"
                  size="md"
                  radius="xl"
                  style={{ flexShrink: 0 }}
                >
                  {thread.number != null ? numberBadge(thread.number) : '•'}
                </Badge>
                <Stack gap={2} style={{ minWidth: 0 }}>
                  <Text size="sm" fw={600} lineClamp={2}>
                    {annotation.label}
                  </Text>
                  {(summary || missing) && (
                    <Group gap={6} wrap="wrap">
                      {summary && (
                        <Text size="xs" c="dimmed">
                          {summary}
                        </Text>
                      )}
                      {missing && (
                        <Tooltip
                          label="Some annotated points are not in the chart's current data"
                          {...DRAWER_TOOLTIP}
                        >
                          <Badge size="xs" color="orange" variant="light">
                            {missing}
                          </Badge>
                        </Tooltip>
                      )}
                    </Group>
                  )}
                </Stack>
              </Group>
            </UnstyledButton>
            {canEditAnnotation && !editingAnnotation && (
              <Button
                size="compact-xs"
                variant="subtle"
                color="gray"
                leftSection={<Icon icon="mdi:pencil-outline" width={12} />}
                onClick={() => setEditingId(thread.id)}
                style={{ flexShrink: 0 }}
              >
                Edit annotation
              </Button>
            )}
          </Group>
        )}
        {annotation && editingAnnotation && (
          <AnnotationEditor
            annotation={annotation}
            onSave={saveAnnotation}
            onCancel={closeEditor}
            onDraftChange={setEditDraft ? (patch) => setEditDraft(thread.id, patch) : undefined}
          />
        )}
        <UnstyledButton
          onClick={() => onFocus(thread)}
          aria-label="Show this comment on the dashboard"
          style={{ display: 'block', width: '100%' }}
        >
          <Stack gap={4}>
            <AuthorLine
              author={thread.created_by}
              at={thread.created_at}
              right={statusBadge}
            />
            {contextBadges.length > 0 && (
              <Group gap={4} wrap="wrap" pl={BODY_INSET}>
                {contextBadges}
              </Group>
            )}
          </Stack>
        </UnstyledButton>

        {opening && (
          <CommentItem
            thread={thread}
            comment={opening}
            own={isOwn(opening.author, currentUser)}
            hideAuthor
            onChange={onChange}
          />
        )}

        {thread.evidence && thread.evidence.length > 0 && (
          <Box pl={BODY_INSET}>
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
          <Text size="xs" c="dimmed" pl={BODY_INSET}>
            Rejected: {thread.review.reason}
          </Text>
        )}

        {replies.length > 0 && (
          <Stack gap="xs">
            {replies.map((c, i) => (
              <React.Fragment key={c.id}>
                {(i > 0 || opening) && <Divider variant="dashed" />}
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
            {...DRAWER_TOOLTIP}
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

        <Group gap={6} justify="space-between" wrap="nowrap" align="flex-start">
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
            <Button
              size="compact-xs"
              variant="subtle"
              color="gray"
              leftSection={<Icon icon="mdi:crosshairs-gps" width={12} />}
              onClick={() => onFocus(thread)}
            >
              Show on dashboard
            </Button>
          </Group>
          <Tooltip label="Delete thread" {...DRAWER_TOOLTIP} w="auto">
            <ActionIcon
              variant="subtle"
              color="red"
              size="sm"
              aria-label="Delete thread"
              disabled={confirmDelete}
              onClick={() => setConfirmDelete(true)}
            >
              <Icon icon="mdi:delete-outline" width={14} />
            </ActionIcon>
          </Tooltip>
        </Group>
      </Stack>
    </Paper>
  );
};

export default ThreadCard;
