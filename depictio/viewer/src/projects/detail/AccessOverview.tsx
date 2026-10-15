import React, { useEffect, useState } from 'react';
import { Badge, Loader, Text, Title } from '@mantine/core';
import { Globe, UserRound, Users, UsersRound } from 'lucide-react';

import { fetchProjectEffectiveAccess, previewGroupMembers } from 'depictio-react-core';
import type { AccessSource, EffectiveAccess, GroupMemberPreview } from 'depictio-react-core';

import { STROKE } from '../../chrome/variants/glass/pages';

const ROLE_LABEL = { owner: 'Owner', editor: 'Editor', viewer: 'Viewer' } as const;
type RoleKey = keyof typeof ROLE_LABEL;

const roleBadge = (role: RoleKey) => (
  <Badge
    color={role === 'owner' ? undefined : role === 'editor' ? 'indigo' : 'gray'}
    size="sm"
    className={role === 'viewer' ? 'gp-tag-plain' : undefined}
  >
    {ROLE_LABEL[role]}
  </Badge>
);

const sourceLabel = (s: AccessSource) =>
  s.kind === 'direct' ? `Direct · ${ROLE_LABEL[s.role]}` : `${s.group_name} · ${ROLE_LABEL[s.role]}`;

/** Effective access of a project, refetched when `refreshKey` changes. Only for
 *  callers who may manage sharing: the endpoint answers 403 to anyone else. */
export function useEffectiveAccess(projectId: string | null, enabled: boolean, refreshKey: number) {
  const [access, setAccess] = useState<EffectiveAccess | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!projectId || !enabled) return;
    let cancelled = false;
    setError(null);
    fetchProjectEffectiveAccess(projectId)
      .then((a) => !cancelled && setAccess(a))
      .catch((e: Error) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [projectId, enabled, refreshKey]);

  return { access, error };
}

/** Everyone the project's grants reach, one row per person. Users and groups are
 *  edited in two lists above, so this is the only place their sum shows: the net
 *  role of someone on both sides, and who a group actually brings in. */
export const AccessOverview: React.FC<{ access: EffectiveAccess | null; error: string | null }> = ({
  access,
  error,
}) => {
  return (
    <section aria-label="Everyone with access" data-testid="permissions-effective-access">
      <div className="pm-head">
        <Users size={18} strokeWidth={STROKE} aria-hidden />
        <Title order={4}>Everyone with access</Title>
        <span className="pm-count">{access ? access.users.length : '…'}</span>
      </div>
      <p className="pm-hint">
        Direct members and the members of each group, added up. Someone listed twice keeps the
        highest role, and every grant behind it is shown.
      </p>
      <ul className="pm-members">
        {error && <li className="pm-empty">{error}</li>}
        {!error && !access && (
          <li className="pm-empty">
            <Loader size="xs" />
          </li>
        )}
        {access?.everyone_can_view && (
          <li className="pm-member" data-testid="permissions-effective-everyone">
            <Globe size={17} strokeWidth={STROKE} className="pm-member-icon" aria-hidden />
            <div className="pm-member-who">
              <span className="pm-member-email">All signed-in users</span>
              <Badge color="gray" size="sm" className="gp-tag-plain">
                Direct · Viewer
              </Badge>
            </div>
            {roleBadge('viewer')}
            <div className="pm-member-end" />
          </li>
        )}
        {access && access.users.length === 0 && !access.everyone_can_view && (
          <li className="pm-empty">Nobody yet.</li>
        )}
        {access?.users.map((u) => (
          <li
            key={u.id}
            className="pm-member"
            data-testid="permissions-effective-row"
            data-email={u.email}
          >
            <UserRound size={17} strokeWidth={STROKE} className="pm-member-icon" aria-hidden />
            <div className="pm-member-who pm-sources">
              <span className="pm-member-email">{u.email}</span>
              {u.sources.map((s, i) => (
                <Badge
                  key={`${s.kind}-${s.group_id ?? ''}-${s.role}-${i}`}
                  color="gray"
                  size="sm"
                  className="gp-tag-plain"
                  leftSection={
                    s.kind === 'group' ? <UsersRound size={12} strokeWidth={STROKE} /> : undefined
                  }
                >
                  {sourceLabel(s)}
                </Badge>
              ))}
            </div>
            {roleBadge(u.role)}
            <div className="pm-member-end" />
          </li>
        ))}
        {access && (
          <li className="pm-empty" style={{ textAlign: 'left' }}>
            <Text size="xs" c="dimmed">
              Sysadmins can always open every project.
            </Text>
          </li>
        )}
      </ul>
    </section>
  );
};

/** Who a group brings in, shown while its name is typed and before Add group:
 *  the grant reaches every member, so the page says who they are first. */
export const GroupMembersPreview: React.FC<{
  projectId: string;
  groupId: string;
  groupName: string;
  /** Effective access today, to flag people who already have it. */
  access: EffectiveAccess | null;
}> = ({ projectId, groupId, groupName, access }) => {
  const [members, setMembers] = useState<GroupMemberPreview[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setMembers(null);
    setError(null);
    previewGroupMembers(projectId, groupId)
      .then((g) => !cancelled && setMembers(g.members))
      .catch((e: Error) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [projectId, groupId]);

  const existing = new Map((access?.users ?? []).map((u) => [u.id, u]));
  const fresh = members?.filter((m) => !existing.has(m.id)).length ?? 0;

  return (
    <li className="pm-preview" data-testid="permissions-group-preview">
      {error ? (
        <Text size="sm" c="red">
          {error}
        </Text>
      ) : !members ? (
        <Loader size="xs" />
      ) : (
        <>
          <Text size="sm" fw={550}>
            {groupName}: {members.length} {members.length === 1 ? 'person' : 'people'}
            {members.length > 0 && ` (${fresh} new to this project)`}
          </Text>
          <div className="pm-preview-people">
            {members.map((m) => {
              const has = existing.get(m.id);
              return (
                <Badge
                  key={m.id}
                  color="gray"
                  size="sm"
                  className="gp-tag-plain"
                  title={has ? `Already ${ROLE_LABEL[has.role]} on this project` : 'Gains access'}
                >
                  {m.email}
                  {has ? ` · already ${ROLE_LABEL[has.role]}` : ''}
                </Badge>
              );
            })}
            {members.length === 0 && (
              <Text size="xs" c="dimmed">
                This group has no members yet.
              </Text>
            )}
          </div>
        </>
      )}
    </li>
  );
};
