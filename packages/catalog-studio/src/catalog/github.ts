/**
 * Open a pull request against depictio/depictio that adds a catalog tool entry,
 * entirely from the browser using an OAuth user token (obtained via
 * `githubOAuth.signIn()` — no PAT pasting). Uses the CORS-enabled GitHub REST
 * API: fork → create branch → blobs → tree → commit → PR. The three files land
 * under `depictio/catalog/<tool>/`.
 */
import { appendRenders } from './yamlGen';
import type { GeneratedEntry } from './yamlGen';
import { decodeBase64 } from './base64';
import type { RenderSpec } from '../types';

export interface PrTarget {
  owner: string;
  repo: string;
  base: string;
}

export const DEFAULT_TARGET: PrTarget = { owner: 'depictio', repo: 'depictio', base: 'main' };

/** The PR target, overridable via `VITE_GH_TARGET` ("owner/repo" or
 *  "owner/repo@branch") — handy for local testing against a throwaway repo so a
 *  test run doesn't hit depictio/depictio. */
export function resolveTarget(): PrTarget {
  const raw = import.meta.env.VITE_GH_TARGET as string | undefined;
  if (raw) {
    const [repoPart, branch] = raw.split('@');
    const [owner, repo] = repoPart.split('/');
    if (owner && repo) return { owner, repo, base: branch || 'main' };
  }
  return DEFAULT_TARGET;
}

const API = 'https://api.github.com';

async function gh<T>(token: string, method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      ...(body ? { 'Content-Type': 'application/json' } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    if (res.status === 401) {
      throw new Error(
        'GitHub rejected the token (401 Bad credentials). Sign in again, or if using a local ' +
          'VITE_GH_TOKEN make sure it is the actual token value (not a literal `$(gh auth token)`).',
      );
    }
    throw new Error(`GitHub ${method} ${path} → ${res.status} ${detail.slice(0, 200)}`);
  }
  return (res.status === 204 ? (undefined as T) : ((await res.json()) as T));
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Poll the fork until its git data is ready (fork creation is async — the repo
 *  record appears before refs/objects exist, so we poll a git ref, not the repo
 *  metadata, to avoid a first-run race when creating the branch). */
async function waitForFork(token: string, login: string, repo: string, base: string): Promise<void> {
  let lastErr: unknown;
  for (let i = 0; i < 12; i++) {
    try {
      await gh(token, 'GET', `/repos/${login}/${repo}/git/ref/heads/${base}`);
      return;
    } catch (e) {
      lastErr = e;
      await sleep(1500);
    }
  }
  throw new Error(`Timed out waiting for your fork's git data to be ready: ${(lastErr as Error)?.message ?? ''}`);
}

export interface OpenPrResult {
  prUrl: string;
  branch: string;
}

export interface PrFile {
  path: string;
  content: string;
}

/** What a late-bound file resolver gets: a reader bound to the exact commit the
 *  PR is about to branch from. */
export interface PrBaseContext {
  baseSha: string;
  /** Upstream file content at `baseSha`, or null when the path doesn't exist. */
  readFile(path: string): Promise<string | null>;
}

export interface PrSpec {
  /** Fixed content — for PRs that only add files. */
  files?: PrFile[];
  /** Content computed once the base commit is known. A PR that MODIFIES an
   *  existing file must use this: committing a blob built from a build-time
   *  snapshot silently reverts everything merged into that file since the
   *  snapshot was taken, and a full-file overwrite produces no git conflict to
   *  warn anyone. May also refine the PR body from the resolved content. */
  resolveFiles?: (ctx: PrBaseContext) => Promise<{ files: PrFile[]; body?: string }>;
  /** Branch name stem, e.g. the tool id. */
  branchSlug: string;
  commitMessage: string;
  title: string;
  body: string;
}

/** Fork, commit `spec.files` on a new branch, and open the PR. The generic core
 *  behind both "new tool" and "add a visualization to an existing tool".
 *  `onProgress` receives short status strings for the UI. */
export async function openFilesPr(
  token: string,
  spec: PrSpec,
  target: PrTarget = DEFAULT_TARGET,
  onProgress: (msg: string) => void = () => {},
): Promise<OpenPrResult> {
  const { owner, repo, base } = target;

  onProgress('Signing in…');
  const user = await gh<{ login: string }>(token, 'GET', '/user');
  const login = user.login;

  onProgress(`Forking ${owner}/${repo}…`);
  await gh(token, 'POST', `/repos/${owner}/${repo}/forks`);
  await waitForFork(token, login, repo, base);

  onProgress('Reading the base branch…');
  const baseRef = await gh<{ object: { sha: string } }>(
    token,
    'GET',
    `/repos/${owner}/${repo}/git/ref/heads/${base}`,
  );
  const baseSha = baseRef.object.sha;
  const baseCommit = await gh<{ tree: { sha: string } }>(
    token,
    'GET',
    `/repos/${owner}/${repo}/git/commits/${baseSha}`,
  );

  // Resolve late-bound content against baseSha, BEFORE the branch exists, so an
  // append is rebased on exactly the commit it will be parented on.
  let files = spec.files ?? [];
  let body = spec.body;
  if (spec.resolveFiles) {
    onProgress('Reading the current file from GitHub…');
    const readFile = async (path: string): Promise<string | null> => {
      try {
        const res = await gh<{ content?: string; encoding?: string }>(
          token,
          'GET',
          `/repos/${owner}/${repo}/contents/${path.split('/').map(encodeURIComponent).join('/')}?ref=${baseSha}`,
        );
        if (!res.content) return null;
        return res.encoding === 'base64' ? decodeBase64(res.content) : res.content;
      } catch {
        return null;
      }
    };
    const resolved = await spec.resolveFiles({ baseSha, readFile });
    files = resolved.files;
    if (resolved.body) body = resolved.body;
  }
  if (!files.length) throw new Error('Nothing to commit — no files resolved for this PR.');

  const branch = `tools-studio/${spec.branchSlug}-${Date.now().toString(36)}`;
  onProgress('Creating a branch…');
  await gh(token, 'POST', `/repos/${login}/${repo}/git/refs`, {
    ref: `refs/heads/${branch}`,
    sha: baseSha,
  });

  onProgress('Committing files…');
  const tree = [];
  for (const f of files) {
    const blob = await gh<{ sha: string }>(token, 'POST', `/repos/${login}/${repo}/git/blobs`, {
      content: f.content,
      encoding: 'utf-8',
    });
    tree.push({ path: f.path, mode: '100644', type: 'blob', sha: blob.sha });
  }
  const newTree = await gh<{ sha: string }>(token, 'POST', `/repos/${login}/${repo}/git/trees`, {
    base_tree: baseCommit.tree.sha,
    tree,
  });
  const commit = await gh<{ sha: string }>(token, 'POST', `/repos/${login}/${repo}/git/commits`, {
    message: spec.commitMessage,
    tree: newTree.sha,
    parents: [baseSha],
  });
  await gh(token, 'PATCH', `/repos/${login}/${repo}/git/refs/heads/${branch}`, {
    sha: commit.sha,
  });

  onProgress('Opening the pull request…');
  const pr = await gh<{ html_url: string }>(token, 'POST', `/repos/${owner}/${repo}/pulls`, {
    title: spec.title,
    head: `${login}:${branch}`,
    base,
    body,
  });

  return { prUrl: pr.html_url, branch };
}

/** New-tool PR: the three files under `depictio/catalog/<tool>/`. */
export async function openCatalogPr(
  token: string,
  entry: GeneratedEntry,
  target: PrTarget = DEFAULT_TARGET,
  onProgress: (msg: string) => void = () => {},
): Promise<OpenPrResult> {
  const dir = `depictio/catalog/${entry.toolId}`;
  const body = [
    '## Summary',
    `Adds the **${entry.toolId}** tool to the catalog, authored with [Depictio Tools Studio](https://depictio.github.io/depictio/).`,
    '',
    `## Files (\`${dir}/\`)`,
    '| File | Purpose |',
    '| --- | --- |',
    '| `module.yaml` | Tool identity (id, name, links). |',
    `| \`${entry.outputYamlName}\` | Output definition + \`renders_as\` (the dashboard components). |`,
    `| \`${entry.fixtureName}\` | Fixture — grounds the bindings in CI (nothing computed server-side). |`,
    '',
    '## Validation',
    'CI `dev catalog validate` is the authoritative check for this entry.',
    '',
    '<details><summary>module.yaml</summary>',
    '',
    '```yaml',
    entry.moduleYaml.trimEnd(),
    '```',
    '</details>',
    '',
    `<details><summary>${entry.outputYamlName}</summary>`,
    '',
    '```yaml',
    entry.outputYaml.trimEnd(),
    '```',
    '</details>',
  ].join('\n');
  return openFilesPr(
    token,
    {
      files: [
        { path: `${dir}/module.yaml`, content: entry.moduleYaml },
        { path: `${dir}/${entry.outputYamlName}`, content: entry.outputYaml },
        { path: `${dir}/${entry.fixtureName}`, content: entry.fixtureContent },
      ],
      branchSlug: entry.toolId,
      commitMessage: `feat(catalog): add ${entry.toolId}`,
      title: `Add catalog tool: ${entry.toolId}`,
      body,
    },
    target,
    onProgress,
  );
}

/** New-output PR: a new `<slug>.yaml` + fixture under an existing tool's folder
 *  (`module.yaml` is left untouched — the tool already exists). */
export async function openNewOutputPr(
  token: string,
  entry: GeneratedEntry,
  dir: string,
  target: PrTarget = DEFAULT_TARGET,
  onProgress: (msg: string) => void = () => {},
): Promise<OpenPrResult> {
  const body = [
    '## Summary',
    `Adds a new output **${entry.outputSlug}** to the existing **${entry.toolId}** tool, ` +
      'authored with [Depictio Tools Studio](https://depictio.github.io/depictio/).',
    '',
    `## Files (\`${dir}/\`)`,
    '| File | Purpose |',
    '| --- | --- |',
    `| \`${entry.outputYamlName}\` | New output definition + \`renders_as\` (the dashboard components). |`,
    `| \`${entry.fixtureName}\` | Fixture — grounds the bindings in CI (nothing computed server-side). |`,
    '',
    '`module.yaml` is unchanged — this only adds an output to the tool.',
    '',
    '## Validation',
    'CI `dev catalog validate` is the authoritative check for this entry.',
    '',
    `<details><summary>${entry.outputYamlName}</summary>`,
    '',
    '```yaml',
    entry.outputYaml.trimEnd(),
    '```',
    '</details>',
  ].join('\n');
  return openFilesPr(
    token,
    {
      files: [
        { path: `${dir}/${entry.outputYamlName}`, content: entry.outputYaml },
        { path: `${dir}/${entry.fixtureName}`, content: entry.fixtureContent },
      ],
      branchSlug: `${entry.toolId}-${entry.outputSlug}`,
      commitMessage: `feat(catalog): add ${entry.outputSlug} output to ${entry.toolId}`,
      title: `Add ${entry.outputSlug} output to ${entry.toolId}`,
      body,
    },
    target,
    onProgress,
  );
}

/** Render ids already present in a raw output YAML (`- id: foo` / `{ id: foo,`). */
export function renderIdsIn(rawYaml: string): Set<string> {
  const ids = new Set<string>();
  for (const m of rawYaml.matchAll(/(?:^\s*-\s*(?:\{\s*)?|,\s*)id:\s*["']?([A-Za-z0-9_.-]+)/gm)) {
    ids.add(m[1]);
  }
  return ids;
}

/**
 * Append-to-existing PR: one modified output YAML at `yamlPath`.
 *
 * The file content is built INSIDE the PR flow, from the upstream file at the
 * exact commit we branch from — never from `catalog.json`'s build-time snapshot.
 * Committing a snapshot-derived blob overwrites whatever landed in that file
 * since the snapshot, and because it is a whole-file write git reports no
 * conflict: the renders simply disappear.
 */
export async function openAddRendersPr(
  token: string,
  args: {
    toolId: string;
    outputSlug: string;
    yamlPath: string;
    renders: RenderSpec[];
    /** What the app previewed the append against, for the drift note. */
    snapshotYaml?: string;
  },
  target: PrTarget = DEFAULT_TARGET,
  onProgress: (msg: string) => void = () => {},
): Promise<OpenPrResult> {
  const count = args.renders.length;
  const plural = count > 1 ? 's' : '';
  return openFilesPr(
    token,
    {
      resolveFiles: async ({ readFile }) => {
        const live = await readFile(args.yamlPath);
        if (live == null) {
          throw new Error(
            `\`${args.yamlPath}\` no longer exists on the target branch — it was probably ` +
              'renamed or removed. Reload the Studio to pick up the current catalog.',
          );
        }
        // Ids must be unique within the tool; the ones we deduped against came
        // from the snapshot, so re-check against what is actually upstream.
        const taken = renderIdsIn(live);
        const clashing = args.renders.map((r) => r.id).filter((id): id is string => !!id && taken.has(id));
        if (clashing.length) {
          throw new Error(
            `Render id${clashing.length > 1 ? 's' : ''} ${clashing.join(', ')} already exist${clashing.length > 1 ? '' : 's'} ` +
              `in ${args.yamlPath} upstream. Rename the render${clashing.length > 1 ? 's' : ''} and try again.`,
          );
        }
        const updatedYaml = appendRenders(live, args.renders).yaml;
        const drifted = args.snapshotYaml != null && args.snapshotYaml.trim() !== live.trim();
        const body = [
          '## Summary',
          `Adds ${count} visualization${plural} to the existing **${args.toolId}** tool ` +
            `(output \`${args.outputSlug}\`), authored with [Depictio Tools Studio](https://depictio.github.io/depictio/).`,
          '',
          `Only \`${args.yamlPath}\` changes — new item${plural} appended under \`renders_as\`.`,
          ...(drifted
            ? [
                '',
                `> The file had changed upstream since this Studio build's snapshot; the new ` +
                  `render${plural} were re-appended to the current version, so nothing is reverted.`,
              ]
            : []),
          '',
          '## Validation',
          'CI `dev catalog validate` is the authoritative check for this entry.',
          '',
          `<details><summary>${args.yamlPath}</summary>`,
          '',
          '```yaml',
          updatedYaml.trimEnd(),
          '```',
          '</details>',
        ].join('\n');
        return { files: [{ path: args.yamlPath, content: updatedYaml }], body };
      },
      branchSlug: `${args.toolId}-${args.outputSlug}`,
      commitMessage: `feat(catalog): add ${count} render${plural} to ${args.toolId}`,
      title: `Add ${count} visualization${plural} to ${args.toolId}`,
      body: '',
    },
    target,
    onProgress,
  );
}
