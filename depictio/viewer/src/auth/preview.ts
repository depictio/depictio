import type { AuthStatusResponse } from 'depictio-react-core';

/**
 * Dev server only: `/auth?preview=...` shows sign-in states this instance is
 * not configured for, to review their look (SAML comes with its own PR, so no
 * local backend can offer it yet). The production bundle drops all of it.
 *
 * Flags, comma separated:
 * - `standard`: the sign-in form, whatever mode the server runs in (implied
 *   by every flag but `code`);
 * - `sso`, `google`: add that provider's button;
 * - `nopassword`: no email form, when a provider is on;
 * - `noregister`: no "Create an account";
 * - `code`: the shared access code gate.
 *
 * e.g. `?preview=sso,nopassword` (SSO only), `?preview=sso,google` (all three).
 */
export function withAuthPreview<T extends AuthStatusResponse | null>(status: T): T {
  if (!import.meta.env.DEV || !status) return status;
  const asked = new URLSearchParams(window.location.search).get('preview');
  if (!asked) return status;
  const on = new Set(asked.split(','));
  const gate = on.has('code');
  return {
    ...status,
    is_single_user_mode: false,
    is_public_mode: gate,
    public_access_code_required: gate,
    user: null,
    google_oauth_enabled: on.has('google'),
    saml_enabled: on.has('sso'),
    saml_login_label: status.saml_login_label ?? 'Sign in with SSO',
    password_login_disabled: on.has('nopassword'),
    registration_disabled: on.has('noregister'),
  };
}
