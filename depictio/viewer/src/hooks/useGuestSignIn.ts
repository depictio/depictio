import { useCurrentUser } from './useCurrentUser';
import { canAdminSignIn, canGuestSignIn } from '../auth/guestSignIn';

/** Whether this visitor is a guest who can sign in, and with which providers.
 *  Drives the "Sign in" entry points a public instance shows next to its
 *  read-only view. */
export function useGuestSignIn() {
  const me = useCurrentUser();
  const state = {
    loading: me.loading,
    isPublicMode: me.isPublicMode,
    isDemoMode: me.isDemoMode,
    isGuest: Boolean(me.user?.is_temporary),
    providers: me.ssoProviders,
  };
  return {
    available: canGuestSignIn(state),
    /** The password form as an "Admin sign-in" link (no provider). For the
     *  instance's chrome only, never for a prompt aimed at guests. */
    adminAvailable: canAdminSignIn({ ...state, adminSignIn: me.publicAdminSignIn }),
    providers: me.ssoProviders,
  };
}
