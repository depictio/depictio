import { useCurrentUser } from '../../hooks/useCurrentUser';
import { useMyAvatar } from './avatar';

/**
 * Who the reader is, as the Glass account surfaces word it (the sidebar and
 * page avatars, the phone sheet's row). One place for the labels, so they
 * cannot drift apart. Each of them links to Account settings.
 */

/** Two letters from the part of an email before the `@`. */
export function initialsOf(email: string): string {
  const local = (email.split('@')[0] || email).replace(/[^a-zA-Z0-9._-]/g, '');
  const parts = local.split(/[._-]+/).filter(Boolean);
  if (parts.length === 0) return '?';
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

export interface AccountIdentity {
  loading: boolean;
  /** Anonymous on an instance that has a login: offer Sign in instead. */
  signIn: boolean;
  /** The line that names the reader: the email, or the mode they run in. */
  name: string;
  /** Initials for an avatar, or null when there is no one to initial. */
  mono: string | null;
  /** The reader's profile picture (an object URL), or null: draw `mono`. */
  avatarUrl: string | null;
}

export function useAccountIdentity(): AccountIdentity {
  const { user, authMode, isPublicMode, isDemoMode, loading } = useCurrentUser();
  const avatarUrl = useMyAvatar();
  const signIn = !loading && !user && authMode === 'standard' && !isPublicMode && !isDemoMode;
  const name =
    authMode === 'single_user'
      ? 'Single user mode'
      : authMode === 'unauthenticated'
        ? 'Unauthenticated mode'
        : (user?.email ?? 'Guest');
  return {
    loading,
    signIn,
    name,
    mono: user && authMode === 'standard' ? initialsOf(user.email) : null,
    avatarUrl: user ? avatarUrl : null,
  };
}
