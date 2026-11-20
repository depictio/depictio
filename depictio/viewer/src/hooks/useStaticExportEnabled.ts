import { useServerInfo } from './useServerInfo';

/** Whether this instance offers the static (serverless) dashboard export, and
 *  with it the combined report + dashboard file. Set by
 *  `DEPICTIO_STATIC_EXPORT_ENABLED`; off, and off while the answer is pending,
 *  so nothing renders or is requested until the server says yes. The API 404s
 *  every `/serverless` route while the setting is off. */
export function useStaticExportEnabled(): boolean {
  const { info } = useServerInfo();
  return info?.features?.static_export === true;
}
