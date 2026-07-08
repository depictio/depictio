/**
 * Open a pull request against depictio/depictio that adds a catalog tool entry,
 * entirely from the browser using an OAuth user token (obtained via
 * `githubOAuth.signIn()` — no PAT pasting). Uses the CORS-enabled GitHub REST
 * API: fork → create branch → blobs → tree → commit → PR. The three files land
 * under `depictio/catalog/<tool>/`.
 */
import type { GeneratedEntry } from './yamlGen';

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

/** Fork, commit the entry's files on a new branch, and open the PR. Returns the
 *  PR URL. `onProgress` receives short status strings for the UI. */
export async function openCatalogPr(
  token: string,
  entry: GeneratedEntry,
  target: PrTarget = DEFAULT_TARGET,
  onProgress: (msg: string) => void = () => {},
): Promise<OpenPrResult> {
  const { owner, repo, base } = target;
  const dir = `depictio/catalog/${entry.toolId}`;
  const files: { path: string; content: string }[] = [
    { path: `${dir}/module.yaml`, content: entry.moduleYaml },
    { path: `${dir}/${entry.outputYamlName}`, content: entry.outputYaml },
    { path: `${dir}/${entry.fixtureName}`, content: entry.fixtureContent },
  ];

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

  const branch = `tools-studio/${entry.toolId}-${Date.now().toString(36)}`;
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
    message: `feat(catalog): add ${entry.toolId}`,
    tree: newTree.sha,
    parents: [baseSha],
  });
  await gh(token, 'PATCH', `/repos/${login}/${repo}/git/refs/heads/${branch}`, {
    sha: commit.sha,
  });

  onProgress('Opening the pull request…');
  const pr = await gh<{ html_url: string }>(token, 'POST', `/repos/${owner}/${repo}/pulls`, {
    title: `Add catalog tool: ${entry.toolId}`,
    head: `${login}:${branch}`,
    base,
    body:
      `Adds \`${dir}/\` via [Depictio Tools Studio](https://depictio.github.io/depictio/).\n\n` +
      `- \`module.yaml\`, \`${entry.outputYamlName}\`, fixture \`${entry.fixtureName}\`\n\n` +
      `CI \`dev catalog validate\` is the authoritative check.`,
  });

  return { prUrl: pr.html_url, branch };
}
