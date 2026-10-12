/**
 * Paths of the builder: the builder routes speak in paths relative to the
 * data root (POSIX), the run-file preview in real locations under it.
 */

/** The real location of `relative` under `dataRoot` (a local path or an
 *  `s3://` location). */
export function joinRoot(dataRoot: string, relative: string): string {
  const base = dataRoot.trim().replace(/\/+$/, '');
  const rel = relative.replace(/^\/+/, '');
  return rel ? `${base}/${rel}` : base;
}

/** The last segment of a relative path. */
export function baseName(path: string): string {
  const parts = path.split('/').filter(Boolean);
  return parts[parts.length - 1] ?? path;
}

/** The folder holding a relative path (`''` at the top). */
export function parentPath(path: string): string {
  const parts = path.split('/').filter(Boolean);
  parts.pop();
  return parts.join('/');
}

/** Every folder above a relative path, outermost first: `a/b/c.csv` gives
 *  `['a', 'a/b']`. */
export function ancestorFolders(path: string): string[] {
  const parts = path.split('/').filter(Boolean);
  parts.pop();
  return parts.map((_, i) => parts.slice(0, i + 1).join('/'));
}

/** A download name for a template id such as `custom/my-survey`. */
export function templateFileName(templateId: string | null | undefined): string {
  const slug = (templateId ?? '').split('/').filter(Boolean).pop() || 'depictio-template';
  return `${slug.replace(/[^A-Za-z0-9._-]+/g, '-')}.yaml`;
}
