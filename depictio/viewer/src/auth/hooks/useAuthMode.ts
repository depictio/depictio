import { useEffect, useState } from 'react';
import { fetchAuthStatus, type AuthStatusResponse } from 'depictio-react-core';

export interface AuthModeState {
  loading: boolean;
  status: AuthStatusResponse | null;
  error: string | null;
}

/** Fetch /auth/me/optional once on mount. Drives /auth UI mode selection. */
export function useAuthMode(): AuthModeState {
  const [state, setState] = useState<AuthModeState>({
    loading: true,
    status: null,
    error: null,
  });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const status = await fetchAuthStatus();
        if (!cancelled) setState({ loading: false, status, error: null });
      } catch (err) {
        if (!cancelled) {
          setState({
            loading: false,
            status: null,
            error: err instanceof Error ? err.message : 'Failed to load auth state',
          });
        }
      }
    })();
    return () => { cancelled = true; };
  }, []);

  return state;
}
