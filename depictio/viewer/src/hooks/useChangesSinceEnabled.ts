import { useServerInfo } from './useServerInfo';

/** Whether this instance offers "changed since your last visit" (#1397). Set by
 *  `DEPICTIO_DASHBOARD_VERSIONS_CHANGES_SINCE_ENABLED`; off, and off while the
 *  answer is pending, so nothing renders or is requested until the server says
 *  yes. The API 404s every changes route while the setting is off. */
export function useChangesSinceEnabled(): boolean {
  const { info } = useServerInfo();
  return info?.features?.changes_since === true;
}
