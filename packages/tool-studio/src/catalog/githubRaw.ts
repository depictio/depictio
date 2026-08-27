/**
 * Rewrite a GitHub web URL (a `…/blob/…` file or `…/tree/…` directory) to its
 * `raw.githubusercontent.com` form. Shared by the tool-source extractors, which
 * all fetch a metadata file from a pasted GitHub URL. An already-raw or
 * non-GitHub URL is returned unchanged (the host substring won't match).
 */
export function githubRawUrl(url: string): string {
  return url
    .replace('github.com', 'raw.githubusercontent.com')
    .replace('/blob/', '/')
    .replace('/tree/', '/');
}
