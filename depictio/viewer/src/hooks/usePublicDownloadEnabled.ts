import { useServerInfo } from './useServerInfo';

/** Whether visitors of a public project may be offered a pre-built offline
 *  copy (#1480): `DEPICTIO_STATIC_EXPORT_ENABLED` and
 *  `DEPICTIO_STATIC_EXPORT_PUBLIC_DOWNLOAD_ENABLED`. Off, and off while the
 *  answer is pending, so neither the owner's switch nor the visitor's button
 *  shows on a server that would refuse them. */
export function usePublicDownloadEnabled(): boolean {
  const { info } = useServerInfo();
  return info?.features?.static_export_public_download === true;
}

/** What a public project offers its visitors until its owner decides
 *  (`DEPICTIO_STATIC_EXPORT_PUBLIC_DOWNLOAD_DEFAULT`, on unless set off). */
export function usePublicDownloadDefault(): boolean {
  const { info } = useServerInfo();
  return info?.features?.static_export_public_download_default !== false;
}
