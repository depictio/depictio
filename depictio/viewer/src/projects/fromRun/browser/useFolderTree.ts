/**
 * State of the folder browser's tree: every folder seen so far, the children
 * of every folder listed so far, and the Mantine `Tree` data built from them.
 *
 * Children are listed lazily, on expansion (local folders through
 * `listLocalDirs`, S3 prefixes through `listS3Dirs`), at most once per folder
 * per opening, and a folder that is not listed yet shows a "Loading" row so
 * its chevron works. `reveal` opens the tree on any location: it lists the
 * location itself (which also says which allowed root it sits under) and then
 * every folder between that root and it.
 *
 * With a private bucket's connection details, the S3 group also lists that
 * bucket as a root, and every listing inside it is read with them (the POST
 * twin of `s3_dirs`), even where the server lists no S3 location itself.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { TreeNodeData } from '@mantine/core';

import {
  folderAncestors,
  folderName,
  folderSource,
  isS3Location,
  listLocalDirs,
  listS3Dirs,
  normalizeFolder,
  shortenHome,
  storageForLocation,
} from 'depictio-react-core';
import type { FolderSource, LocalDirListing, RunStorageBinding } from 'depictio-react-core';

/** Tree values of the two top-level groups. Never a folder path: those start
 *  with `/`, `~` or `s3://`. */
export const GROUP_KEY: Record<FolderSource, string> = {
  local: '__group__:local',
  s3: '__group__:s3',
};

const PLACEHOLDER_PREFIX = '__placeholder__:';

export type PlaceholderKind = 'loading' | 'error' | 'empty' | 'truncated';

export interface FolderNode {
  path: string;
  name: string;
  source: FolderSource;
  looksLikeRun: boolean;
  hasChildren: boolean;
  /** One of the allowed roots, listed under its group. */
  isRoot: boolean;
}

export interface ChildrenState {
  status: 'loading' | 'loaded' | 'error';
  paths: string[];
  truncated: boolean;
  error: string | null;
}

export type RevealResult =
  | { ok: true; path: string; expand: string[] }
  /** `error` is empty when the browser closed meanwhile (nothing to say). */
  | { ok: false; error: string };

export interface TreeNodeProps {
  kind: 'group' | 'folder' | 'placeholder';
  source?: FolderSource;
  placeholder?: PlaceholderKind;
  /** The folder a placeholder row stands in for. */
  parent?: string;
}

const NO_LISTING: LocalDirListing = { path: null, root: null, parent: null, entries: [], truncated: false };

/** The S3 roots: the locations the server lists (when it may browse S3) and
 *  the private bucket, first, when its connection details were given. */
async function listS3Roots(
  listed: boolean,
  privateBucket: RunStorageBinding | null,
): Promise<LocalDirListing> {
  const listing = listed ? await listS3Dirs(null) : NO_LISTING;
  if (!privateBucket) return listing;
  const path = `s3://${privateBucket.bucket}/`;
  return {
    ...listing,
    entries: [
      { name: privateBucket.bucket, path, looks_like_run: false, has_children: true },
      ...listing.entries,
    ],
  };
}

function fetchListing(
  key: string,
  s3Listed: boolean,
  privateBucket: RunStorageBinding | null,
): Promise<LocalDirListing> {
  if (key === GROUP_KEY.local) return listLocalDirs(null);
  if (key === GROUP_KEY.s3) return listS3Roots(s3Listed, privateBucket);
  return isS3Location(key)
    ? listS3Dirs(key, { storage: storageForLocation(key, privateBucket) })
    : listLocalDirs(key);
}

function placeholder(parent: string, kind: PlaceholderKind, label = ''): TreeNodeData {
  const props: TreeNodeProps = { kind: 'placeholder', placeholder: kind, parent };
  return { value: `${PLACEHOLDER_PREFIX}${kind}:${parent}`, label, nodeProps: props };
}

export function useFolderTree({
  opened,
  localEnabled,
  s3Enabled,
  privateBucket = null,
}: {
  opened: boolean;
  localEnabled: boolean;
  /** The server may browse the S3 locations it lists. */
  s3Enabled: boolean;
  /** A private bucket and its connection details, browsed with them. */
  privateBucket?: RunStorageBinding | null;
}) {
  /** The S3 group is shown for the listed locations, a private bucket, or both. */
  const s3Shown = s3Enabled || Boolean(privateBucket);
  /** Read at request time, so `load` stays the same function: the details
   *  cannot change while the browser is open (it sits above the form). */
  const privateRef = useRef(privateBucket);
  privateRef.current = privateBucket;
  const privateKey = privateBucket?.bucket ?? null;
  const [nodes, setNodes] = useState<Record<string, FolderNode>>({});
  const [children, setChildren] = useState<Record<string, ChildrenState>>({});
  /** Mirrors `children` synchronously, so a load can tell "already listed"
   *  between two awaits of the same reveal, before React re-renders. */
  const childrenRef = useRef<Record<string, ChildrenState>>({});
  const inflight = useRef(new Map<string, Promise<boolean>>());
  /** Bumped on close: a listing that lands after it is dropped. */
  const epoch = useRef(0);

  const setChildState = useCallback((key: string, state: ChildrenState | null) => {
    const next = { ...childrenRef.current };
    if (state) next[key] = state;
    else delete next[key];
    childrenRef.current = next;
    setChildren(next);
  }, []);

  const register = useCallback(
    (key: string, listing: LocalDirListing) => {
      const isGroup = key === GROUP_KEY.local || key === GROUP_KEY.s3;
      const added: FolderNode[] = [];
      const seen = new Set<string>();
      for (const entry of listing.entries) {
        const path = normalizeFolder(entry.path);
        if (!path || seen.has(path)) continue;
        seen.add(path);
        added.push({
          path,
          name: entry.name || folderName(path),
          source: folderSource(path),
          looksLikeRun: Boolean(entry.looks_like_run),
          hasChildren: entry.has_children ?? true,
          isRoot: isGroup,
        });
      }
      setNodes((prev) => {
        const next = { ...prev };
        for (const node of added) {
          const known = prev[node.path];
          // An S3 entry always says "not a run"; keep what an inspection learnt.
          next[node.path] = known
            ? { ...node, looksLikeRun: node.looksLikeRun || known.looksLikeRun, isRoot: node.isRoot || known.isRoot }
            : node;
        }
        if (next[key]) {
          next[key] = {
            ...next[key],
            hasChildren: added.length > 0,
            looksLikeRun: next[key].looksLikeRun || Boolean(listing.looks_like_run),
          };
        }
        return next;
      });
      setChildState(key, {
        status: 'loaded',
        paths: added.map((n) => n.path),
        truncated: Boolean(listing.truncated),
        error: null,
      });
    },
    [setChildState],
  );

  const load = useCallback(
    (key: string): Promise<boolean> => {
      if (childrenRef.current[key]?.status === 'loaded') return Promise.resolve(true);
      const pending = inflight.current.get(key);
      if (pending) return pending;
      const run = epoch.current;
      setChildState(key, { status: 'loading', paths: [], truncated: false, error: null });
      const promise = fetchListing(key, s3Enabled, privateRef.current)
        .then((listing) => {
          if (run !== epoch.current) return false;
          register(key, listing);
          return true;
        })
        .catch((err: Error) => {
          if (run !== epoch.current) return false;
          setChildState(key, {
            status: 'error',
            paths: [],
            truncated: false,
            error: err.message || 'This folder could not be listed.',
          });
          return false;
        })
        .finally(() => {
          if (inflight.current.get(key) === promise) inflight.current.delete(key);
        });
      inflight.current.set(key, promise);
      return promise;
    },
    [register, setChildState, s3Enabled],
  );

  /** Forget a failed listing and try it again. */
  const retry = useCallback(
    (key: string) => {
      setChildState(key, null);
      void load(key);
    },
    [load, setChildState],
  );

  // A fresh tree on every opening: the roots of each enabled source, nothing
  // below them until a folder is expanded.
  useEffect(() => {
    if (!opened) return undefined;
    childrenRef.current = {};
    setChildren({});
    setNodes({});
    if (localEnabled) void load(GROUP_KEY.local);
    if (s3Shown) void load(GROUP_KEY.s3);
    return () => {
      epoch.current += 1;
      inflight.current.clear();
    };
  }, [opened, localEnabled, s3Shown, privateKey, load]);

  /** Record what an inspection learnt about a folder's run markers. */
  const markRun = useCallback((path: string, looksLikeRun: boolean) => {
    setNodes((prev) =>
      prev[path] && prev[path].looksLikeRun !== looksLikeRun
        ? { ...prev, [path]: { ...prev[path], looksLikeRun } }
        : prev,
    );
  }, []);

  const reveal = useCallback(
    async (location: string): Promise<RevealResult> => {
      const target = normalizeFolder(location);
      if (!target) return { ok: false, error: 'Type a folder path first.' };
      const source = folderSource(target);
      if (source === 's3' && !s3Shown) {
        return { ok: false, error: 'Browsing S3 is not available on this server.' };
      }
      if (source === 'local') {
        if (!localEnabled) {
          return {
            ok: false,
            error: 'Browsing folders on this computer is not available on this server.',
          };
        }
        if (!target.startsWith('/') && !target.startsWith('~')) {
          return {
            ok: false,
            error: 'Type a full path (starting with / or ~/) or an s3:// location.',
          };
        }
      }
      const run = epoch.current;
      await load(GROUP_KEY[source]);
      let listing: LocalDirListing;
      try {
        listing = await fetchListing(target, s3Enabled, privateRef.current);
      } catch (err) {
        if (run !== epoch.current) return { ok: false, error: '' };
        return { ok: false, error: (err as Error).message || 'This folder could not be opened.' };
      }
      if (run !== epoch.current) return { ok: false, error: '' };
      const resolved = normalizeFolder(listing.path ?? target);
      const root = listing.root ? normalizeFolder(listing.root) : null;
      const chain = root ? folderAncestors(root, resolved) : null;
      setNodes((prev) =>
        prev[resolved]
          ? prev
          : {
              ...prev,
              [resolved]: {
                path: resolved,
                name: folderName(resolved),
                source,
                looksLikeRun: Boolean(listing.looks_like_run),
                hasChildren: listing.entries.length > 0,
                isRoot: false,
              },
            },
      );
      if (childrenRef.current[resolved]?.status !== 'loaded') register(resolved, listing);
      if (chain) {
        for (const ancestor of chain.slice(0, -1)) {
          await load(ancestor);
          if (run !== epoch.current) return { ok: false, error: '' };
        }
      }
      const expand = [GROUP_KEY[source], ...(chain ? chain.slice(0, -1) : [])];
      if (listing.entries.length > 0) expand.push(resolved);
      return { ok: true, path: resolved, expand };
    },
    [load, register, localEnabled, s3Enabled, s3Shown],
  );

  const treeData = useMemo<TreeNodeData[]>(() => {
    const build = (path: string, depth: number): TreeNodeData => {
      const node = nodes[path];
      const state = children[path];
      let kids: TreeNodeData[] | undefined;
      if (depth > 64) {
        kids = undefined;
      } else if (state?.status === 'loaded') {
        kids = state.paths.map((p) => build(p, depth + 1));
        if (state.truncated) kids.push(placeholder(path, 'truncated'));
      } else if (state?.status === 'error') {
        kids = [placeholder(path, 'error', state.error ?? '')];
      } else if (state?.status === 'loading' || node?.hasChildren) {
        kids = [placeholder(path, 'loading')];
      }
      const label =
        node?.isRoot && node.source === 'local' ? shortenHome(path) : (node?.name ?? folderName(path));
      const props: TreeNodeProps = { kind: 'folder', source: node?.source ?? folderSource(path) };
      return { value: path, label, nodeProps: props, children: kids };
    };

    const groups: TreeNodeData[] = [];
    for (const source of ['local', 's3'] as const) {
      if (source === 'local' ? !localEnabled : !s3Shown) continue;
      const key = GROUP_KEY[source];
      const state = children[key];
      let kids: TreeNodeData[];
      if (!state || state.status === 'loading') kids = [placeholder(key, 'loading')];
      else if (state.status === 'error') kids = [placeholder(key, 'error', state.error ?? '')];
      else if (state.paths.length === 0) kids = [placeholder(key, 'empty')];
      else kids = state.paths.map((p) => build(p, 0));
      const props: TreeNodeProps = { kind: 'group', source };
      groups.push({
        value: key,
        label: source === 'local' ? 'This computer' : 'S3',
        nodeProps: props,
        children: kids,
      });
    }
    return groups;
  }, [nodes, children, localEnabled, s3Shown]);

  /** The allowed roots listed so far, local then S3. */
  const roots = useMemo(
    () =>
      [GROUP_KEY.local, GROUP_KEY.s3].flatMap((key) =>
        (children[key]?.paths ?? []).map((p) => nodes[p]).filter(Boolean),
      ),
    [children, nodes],
  );

  return { nodes, children, treeData, roots, load, retry, reveal, markRun };
}

export type FolderTreeState = ReturnType<typeof useFolderTree>;
