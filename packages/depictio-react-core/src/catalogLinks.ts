/**
 * Links back to a catalog tool's definition in the depictio repo.
 *
 * The catalog is one folder per tool under `depictio/catalog/`, named after the
 * tool id, and `_load_tool_dir` refuses a `module.yaml` whose id disagrees with
 * its folder — so the id is all this needs.
 *
 * Derived rather than carried on `CatalogSource`: a component's provenance is
 * persisted into its dashboard, and a URL frozen there would go stale the day
 * the repo moves while every stored component kept pointing at the old host.
 */

/** Where the catalog lives, on the branch the docs and the API both link to. */
const CATALOG_TREE_BASE = 'https://github.com/depictio/depictio/tree/main/depictio/catalog';

/**
 * Browsable source for one catalog tool, e.g.
 * `https://github.com/depictio/depictio/tree/main/depictio/catalog/ivar`.
 *
 * Null for a missing id, so callers render no link rather than a broken one.
 */
export function catalogToolUrl(toolId?: string | null): string | null {
  const id = (toolId ?? '').trim();
  return id ? `${CATALOG_TREE_BASE}/${encodeURIComponent(id)}` : null;
}
