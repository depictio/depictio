import { useCurrentUser } from './useCurrentUser';
import { canGuestSignIn } from '../auth/guestSignIn';

/** Whether this visitor is a guest who can sign in, and with which providers.
 *  Drives the "Sign in" entry points a public instance shows next to its
 *  read-only view. */
export function useGuestSignIn() {
  const me = useCurrentUser();
  const available = canGuestSignIn({
    loading: me.loading,
    isPublicMode: me.isPublicMode,
    isDemoMode: me.isDemoMode,
    isGuest: Boolean(me.user?.is_temporary),
    providers: me.ssoProviders,
  });
  return {
    available,
    providers: me.ssoProviders,
  };
}
