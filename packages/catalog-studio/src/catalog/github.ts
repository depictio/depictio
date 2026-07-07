/**
 * Open a pull request against depictio/depictio entirely from the browser using
 * a user-supplied PAT (classic or fine-grained with `repo`/`contents`+`pull_requests`
 * write on a fork). Flow: fork upstream → branch off the fork's default branch →
 * commit the three files via the Git Data API → open a PR from the fork.
 *
 * The PAT never leaves the browser except in Authorization headers to
 * api.github.com. We never persist it.
 */
import { encodeBase64 } from './base64';

const API = 'https://api.github.com';

export interface PrTarget {
  owner: string; // upstream owner, e.g. "depictio"
  repo: string; // upstream repo, e.g. "depictio"
}

export interface PrFile {
  path: string; // repo-relative, e.g. "depictio/catalog/mosdepth/module.yaml"
  content: string; // utf-8 text
}

export interface PrResult {
  html_url: string;
  number: number;
}

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
    let detail = '';
    try {
      detail = (await res.json()).message ?? '';
    } catch {
      /* ignore */
    }
    throw new Error(`GitHub ${method} ${path} → ${res.status} ${detail}`);
  }
  return (res.status === 204 ? (undefined as T) : ((await res.json()) as T));
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function ensureFork(token: string, target: PrTarget, login: string): Promise<string> {
  // POST forks is idempotent — returns the existing fork if present.
  await gh(token, 'POST', `/repos/${target.owner}/${target.repo}/forks`, {});
  // Fork creation is async; poll until the fork repo resolves.
  for (let i = 0; i < 10; i++) {
    try {
      await gh(token, 'GET', `/repos/${login}/${target.repo}`);
      return `${login}/${target.repo}`;
    } catch {
      await sleep(1500);
    }
  }
  throw new Error('Fork did not become available in time — retry in a moment.');
}

export interface OpenPrArgs {
  token: string;
  target: PrTarget;
  branch: string;
  title: string;
  body: string;
  files: PrFile[];
}

export async function openCatalogPr({
  token,
  target,
  branch,
  title,
  body,
  files,
}: OpenPrArgs): Promise<PrResult> {
  const me = await gh<{ login: string }>(token, 'GET', '/user');
  const forkFull = await ensureFork(token, target, me.login);

  // Base off the fork's default branch head.
  const repoInfo = await gh<{ default_branch: string }>(token, 'GET', `/repos/${forkFull}`);
  const baseBranch = repoInfo.default_branch;
  const baseRef = await gh<{ object: { sha: string } }>(
    token,
    'GET',
    `/repos/${forkFull}/git/ref/heads/${baseBranch}`,
  );
  const baseSha = baseRef.object.sha;
  const baseCommit = await gh<{ tree: { sha: string } }>(
    token,
    'GET',
    `/repos/${forkFull}/git/commits/${baseSha}`,
  );

  // Blobs → tree → commit.
  const tree = await Promise.all(
    files.map(async (f) => {
      const blob = await gh<{ sha: string }>(token, 'POST', `/repos/${forkFull}/git/blobs`, {
        content: encodeBase64(f.content),
        encoding: 'base64',
      });
      return { path: f.path, mode: '100644' as const, type: 'blob' as const, sha: blob.sha };
    }),
  );
  const newTree = await gh<{ sha: string }>(token, 'POST', `/repos/${forkFull}/git/trees`, {
    base_tree: baseCommit.tree.sha,
    tree,
  });
  const commit = await gh<{ sha: string }>(token, 'POST', `/repos/${forkFull}/git/commits`, {
    message: title,
    tree: newTree.sha,
    parents: [baseSha],
  });

  // Create the branch ref on the fork (delete-then-create if it exists).
  try {
    await gh(token, 'POST', `/repos/${forkFull}/git/refs`, {
      ref: `refs/heads/${branch}`,
      sha: commit.sha,
    });
  } catch {
    await gh(token, 'PATCH', `/repos/${forkFull}/git/refs/heads/${branch}`, {
      sha: commit.sha,
      force: true,
    });
  }

  // Open the PR against upstream.
  const pr = await gh<PrResult>(token, 'POST', `/repos/${target.owner}/${target.repo}/pulls`, {
    title,
    body,
    head: `${me.login}:${branch}`,
    base: baseBranch,
    maintainer_can_modify: true,
  });
  return pr;
}
