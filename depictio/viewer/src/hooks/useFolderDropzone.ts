import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

/**
 * Browser folder/file dropzone with `webkitGetAsEntry` recursion.
 *
 * Why this hook exists: the React viewer needs to upload MultiQC reports
 * grouped by parent folder, just like the Dash UI. The browser delivers a
 * folder drop as a flat list of `File`s with relative paths in
 * `webkitRelativePath`. We rebind each File's effective `name` to that
 * relative path so the FormData append carries the path through to the
 * backend, which then groups by `<folder>/multiqc_data/multiqc.parquet`.
 *
 * Filter is opt-in: `filterFilename: 'multiqc.parquet'` matches the MultiQC
 * pipeline; pass `undefined` (default) to accept everything.
 *
 * No new deps — `react-dropzone` would be ~30 KB plus transitive deps for a
 * single use. The Dash assets/multiqc_folder_upload.js is ~150 lines of
 * Dash plumbing wrapping ~60 lines of portable logic; that core lives here.
 */

interface UseFolderDropzoneOptions {
  /** Only retain files whose basename matches. */
  filterFilename?: string;
  /** Only retain files whose lowercase extension is in this list (e.g.
   *  ['csv', 'tsv']). Tested after `filterFilename` if both are set, so the
   *  combined filter is intersection. */
  filterExtensions?: string[];
  /** Per-file size cap (bytes). Files exceeding it are dropped + reported. */
  maxPerFile?: number;
  /** Total size cap (bytes). Hook reports an error and clears the batch on exceed. */
  maxTotal?: number;
}

interface UseFolderDropzoneResult {
  /** Bind to the visible drop target (`<div ref={rootRef} ...>`). */
  rootRef: React.MutableRefObject<HTMLDivElement | null>;
  /** Bind to the hidden `<input>` used by the click-to-pick path. The owner
   *  controls whether it's a file picker or folder picker via attributes. */
  inputRef: React.MutableRefObject<HTMLInputElement | null>;
  files: File[];
  totalBytes: number;
  /** True while a drag is currently over the root element. */
  isDragOver: boolean;
  /** Last validation error from a drop or filter. Cleared on next drop / clear. */
  error: string | null;
  /** File names that were ignored by the filter (basename ≠ filterFilename). */
  skipped: string[];
  removeFile: (file: File) => void;
  clear: () => void;
  /** Programmatically open the OS picker bound to `inputRef`. */
  openPicker: () => void;
  /** Accept a `FileList` directly (e.g. from a parent `<input>`). Useful for tests. */
  addFromFileList: (files: FileList | File[] | null) => void;
}

function rebindRelativeName(file: File): File {
  // `webkitRelativePath` is read-only and absent on plain drag-drop entries;
  // `_relativePath` is what `traverseEntry` stamps below. Either way we
  // override the effective `name` so FormData carries the path through.
  const rel =
    (file as unknown as { _relativePath?: string })._relativePath ??
    file.webkitRelativePath ??
    file.name;
  if (!rel || rel === file.name) return file;
  try {
    Object.defineProperty(file, 'name', { value: rel, configurable: true });
  } catch {
    // Some browsers freeze File.name; fall back to a no-op clone.
  }
  return file;
}

async function readEntryAsFile(entry: FileSystemFileEntry, relativePath: string): Promise<File> {
  return new Promise((resolve, reject) => {
    entry.file(
      (file) => {
        Object.defineProperty(file, '_relativePath', {
          value: relativePath,
          configurable: true,
        });
        resolve(file);
      },
      (err) => reject(err),
    );
  });
}

async function readDirEntries(
  reader: FileSystemDirectoryReader,
): Promise<FileSystemEntry[]> {
  return new Promise((resolve, reject) => {
    const entries: FileSystemEntry[] = [];
    const pump = () => {
      reader.readEntries((batch) => {
        if (!batch.length) {
          resolve(entries);
          return;
        }
        entries.push(...batch);
        pump();
      }, reject);
    };
    pump();
  });
}

async function traverseEntry(
  entry: FileSystemEntry,
  prefix: string,
): Promise<File[]> {
  if (entry.isFile) {
    const fileEntry = entry as FileSystemFileEntry;
    return [await readEntryAsFile(fileEntry, prefix + entry.name)];
  }
  if (entry.isDirectory) {
    const dirEntry = entry as FileSystemDirectoryEntry;
    const reader = dirEntry.createReader();
    const children = await readDirEntries(reader);
    // Kick off every child read in parallel. Sequential awaits leave sibling
    // FileSystemEntry handles pending while we wait on the first; on macOS
    // Chrome those handles can go stale before we get to them, so a drop of
    // ten run folders only ingests one. Promise.all forces all reads to
    // start synchronously.
    const childResults = await Promise.all(
      children.map((child) => traverseEntry(child, prefix + entry.name + '/')),
    );
    return childResults.flat();
  }
  return [];
}

export function useFolderDropzone(
  options: UseFolderDropzoneOptions = {},
): UseFolderDropzoneResult {
  const { filterFilename, filterExtensions, maxPerFile, maxTotal } = options;
  const normalizedExtensions = useMemo(
    () => filterExtensions?.map((e) => e.toLowerCase().replace(/^\./, '')),
    [filterExtensions],
  );
  const rootRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [skipped, setSkipped] = useState<string[]>([]);
  const [isDragOver, setDragOver] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const ingest = useCallback(
    (incoming: File[]) => {
      setError(null);
      const skippedNames: string[] = [];
      const oversized: string[] = [];
      const accepted: File[] = [];

      for (const raw of incoming) {
        const f = rebindRelativeName(raw);
        // Pull basename from the (possibly path-rewritten) name.
        const segments = f.name.replace(/\\/g, '/').split('/');
        const basename = segments[segments.length - 1] || f.name;
        if (filterFilename && basename !== filterFilename) {
          skippedNames.push(f.name);
          continue;
        }
        if (normalizedExtensions && normalizedExtensions.length > 0) {
          const dotIdx = basename.lastIndexOf('.');
          const ext = dotIdx >= 0 ? basename.slice(dotIdx + 1).toLowerCase() : '';
          if (!normalizedExtensions.includes(ext)) {
            skippedNames.push(f.name);
            continue;
          }
        }
        if (maxPerFile && f.size > maxPerFile) {
          oversized.push(`${f.name} (${(f.size / (1024 * 1024)).toFixed(1)}MB)`);
          continue;
        }
        accepted.push(f);
      }

      if (oversized.length) {
        setError(
          `Per-file cap is ${(maxPerFile! / (1024 * 1024)).toFixed(0)}MB. ` +
            `Skipped: ${oversized.join(', ')}.`,
        );
      }

      if (!accepted.length) {
        setSkipped((prev) => [...prev, ...skippedNames]);
        return;
      }

      const merged = [...files, ...accepted];
      const total = merged.reduce((acc, f) => acc + f.size, 0);
      if (maxTotal && total > maxTotal) {
        setError(
          `Total upload would be ${(total / (1024 * 1024)).toFixed(1)}MB; cap is ${(
            maxTotal / (1024 * 1024)
          ).toFixed(0)}MB. Drop fewer files.`,
        );
        return;
      }
      setFiles(merged);
      setSkipped((prev) => [...prev, ...skippedNames]);
    },
    [filterFilename, normalizedExtensions, files, maxPerFile, maxTotal],
  );

  const handleDrop = useCallback(
    async (event: DragEvent) => {
      event.preventDefault();
      event.stopPropagation();
      setDragOver(false);

      const items = event.dataTransfer?.items;
      if (items?.length) {
        // The DataTransferItemList is only valid for the synchronous lifetime
        // of this drop event. Snapshot every entry / fallback File NOW —
        // awaiting before extracting them silently drops everything past the
        // first item (the bug behind "only one folder shows up when dropping
        // run_01..run_10 at once").
        const entries: FileSystemEntry[] = [];
        const flatFiles: File[] = [];
        for (let i = 0; i < items.length; i++) {
          const item = items[i];
          if (item.kind !== 'file') continue;
          const entry =
            typeof item.webkitGetAsEntry === 'function'
              ? item.webkitGetAsEntry()
              : null;
          if (entry) {
            entries.push(entry);
          } else {
            const file = item.getAsFile();
            if (file) flatFiles.push(file);
          }
        }

        const collected: File[] = [...flatFiles];
        const traversed = await Promise.all(
          entries.map((entry) =>
            traverseEntry(entry, '').catch((err) => {
              console.warn('useFolderDropzone: traverseEntry failed', err);
              return [] as File[];
            }),
          ),
        );
        for (const files of traversed) collected.push(...files);
        if (collected.length) ingest(collected);
        return;
      }

      const fallback = event.dataTransfer?.files;
      if (fallback?.length) {
        ingest(Array.from(fallback));
      }
    },
    [ingest],
  );

  // Document-level drop handler: while this hook is mounted (i.e. while the
  // upload modal is open), file drops anywhere in this hook's enclosing
  // modal are captured — landing on the small dropzone target is fragile
  // and missing it lets Chrome navigate away. preventDefault on document-
  // level dragover is required so the browser allows the drop at all.
  //
  // Modal-scoped guard: if two dropzone hooks are mounted simultaneously
  // (e.g. Manage and Create modals open in the same render cycle), both
  // document listeners would otherwise ingest the same File once each.
  // Restrict each hook's drop to its own enclosing dialog so cross-modal
  // drops don't double-fire. Drops outside any modal (with no enclosing
  // dialog) fall back to the original "anywhere on the page" behavior.
  useEffect(() => {
    const onDocDragOver = (e: DragEvent) => {
      if (!e.dataTransfer?.types?.includes('Files')) return;
      e.preventDefault();
    };
    const onDocDrop = (e: DragEvent) => {
      if (!e.dataTransfer?.types?.includes('Files')) return;
      const node = rootRef.current;
      const target = e.target as HTMLElement | null;
      if (node && target) {
        const modal = node.closest('[role="dialog"]');
        if (modal && !modal.contains(target)) return;
      }
      handleDrop(e);
    };
    document.addEventListener('dragover', onDocDragOver);
    document.addEventListener('drop', onDocDrop);
    return () => {
      document.removeEventListener('dragover', onDocDragOver);
      document.removeEventListener('drop', onDocDrop);
    };
  }, [handleDrop]);

  // Root-level drag tracking just for the visual highlight.
  useEffect(() => {
    const node = rootRef.current;
    if (!node) return;
    const onDragEnter = (e: DragEvent) => {
      if (!e.dataTransfer?.types?.includes('Files')) return;
      setDragOver(true);
    };
    const onDragLeave = (e: DragEvent) => {
      if (e.target === node) setDragOver(false);
    };
    node.addEventListener('dragenter', onDragEnter);
    node.addEventListener('dragleave', onDragLeave);
    return () => {
      node.removeEventListener('dragenter', onDragEnter);
      node.removeEventListener('dragleave', onDragLeave);
    };
  }, []);

  // Hook the click-to-pick input — owner attaches via `inputRef` and chooses
  // file-picker vs folder-picker semantics by setting `webkitdirectory`.
  useEffect(() => {
    const input = inputRef.current;
    if (!input) return;
    const onChange = (event: Event) => {
      const target = event.target as HTMLInputElement;
      if (target.files?.length) ingest(Array.from(target.files));
      target.value = '';
    };
    input.addEventListener('change', onChange);
    return () => input.removeEventListener('change', onChange);
  }, [ingest]);

  const removeFile = useCallback((file: File) => {
    setFiles((prev) => prev.filter((f) => f !== file));
  }, []);

  const clear = useCallback(() => {
    setFiles([]);
    setSkipped([]);
    setError(null);
  }, []);

  const openPicker = useCallback(() => {
    inputRef.current?.click();
  }, []);

  const addFromFileList = useCallback(
    (incoming: FileList | File[] | null) => {
      if (!incoming) return;
      const arr = Array.from(incoming as ArrayLike<File>);
      ingest(arr);
    },
    [ingest],
  );

  const totalBytes = useMemo(() => files.reduce((acc, f) => acc + f.size, 0), [files]);

  return {
    rootRef,
    inputRef,
    files,
    totalBytes,
    isDragOver,
    error,
    skipped,
    removeFile,
    clear,
    openPicker,
    addFromFileList,
  };
}

export default useFolderDropzone;
