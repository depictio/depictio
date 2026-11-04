import { Button } from '@mantine/core';
import { KeyRound } from 'lucide-react';
import { oidcLoginUrl } from 'depictio-react-core';
import type { SsoProvider } from 'depictio-react-core';

import { returnPathOrDefault } from '../guestSignIn';
import { rememberReturnTo } from '../postAuthTarget';

interface Props {
  /** Enabled OpenID Connect providers, rendered in the order given. */
  providers: SsoProvider[];
}

/**
 * The identity-provider buttons, one place for them: one per OpenID Connect
 * provider the server lists. The sign-in form, the guest prompts and the
 * profile page all render these, so a restyle reaches every door at once.
 *
 * Starting a provider remembers the page the visitor is on, so they come back
 * to it afterwards (a no-op on `/auth`, which is never a destination).
 */
export default function SignInProviders({ providers }: Props) {
  return (
    <>
      {providers.map((p) => (
        <Button
          key={p.id}
          id={`sso-login-${p.id}`}
          data-testid={`sso-login-button-${p.id}`}
          variant="default"
          radius="md"
          fullWidth
          leftSection={
            p.id === 'google' ? (
              <img
                src={`${import.meta.env.BASE_URL}logos/google_g.svg`}
                alt=""
                width={18}
                height={18}
                style={{ display: 'block' }}
              />
            ) : (
              <KeyRound size={18} strokeWidth={1.8} aria-hidden />
            )
          }
          onClick={() => {
            rememberReturnTo();
            window.location.assign(oidcLoginUrl(p.id, returnPathOrDefault()));
          }}
        >
          {p.label}
        </Button>
      ))}
    </>
  );
}
