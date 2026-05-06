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
  /** Per-file size cap (bytes). Files exceeding it are dropped + reported. */
  maxPerFile?: number;
  /** Total size cap (bytes). Hook reports an error and clears the batch on exceed. */
  maxTotal?: number;
}

interface UseFolderDropzoneResult {
  /** Bind to the visible drop target (`<div ref={rootRef} ...>`). */
  rootRef: React.MutableRefObject<HTMLDivElement | null>;
  /** Bind to the hidden `<input type="file" multiple webkitdirectory>`. */
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
  /** Programmatically open the OS folder picker. */
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
    const out: File[] = [];
    for (const child of children) {
      out.push(...(await traverseEntry(child, prefix + entry.name + '/')));
    }
    return out;
  }
  return [];
}

export function useFolderDropzone(
  options: UseFolderDropzoneOptions = {},
): UseFolderDropzoneResult {
  const { filterFilename, maxPerFile, maxTotal } = options;
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
    [filterFilename, files, maxPerFile, maxTotal],
  );

  const handleDrop = useCallback(
    async (event: DragEvent) => {
      event.preventDefault();
      event.stopPropagation();
      setDragOver(false);

      const items = event.dataTransfer?.items;
      if (items?.length) {
        const collected: File[] = [];
        for (let i = 0; i < items.length; i++) {
          const item = items[i];
          if (item.kind !== 'file') continue;
          const entry =
            typeof item.webkitGetAsEntry === 'function' ? item.webkitGetAsEntry() : null;
          if (entry) {
            try {
              collected.push(...(await traverseEntry(entry, '')));
            } catch (err) {
              console.warn('useFolderDropzone: traverseEntry failed', err);
            }
          } else {
            const file = item.getAsFile();
            if (file) collected.push(file);
          }
        }
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

  useEffect(() => {
    const node = rootRef.current;
    if (!node) return;
    const onDragOver = (e: DragEvent) => {
      e.preventDefault();
      setDragOver(true);
    };
    const onDragLeave = (e: DragEvent) => {
      // Only flip off when leaving the root, not a child.
      if (e.target === node) setDragOver(false);
    };
    node.addEventListener('dragover', onDragOver);
    node.addEventListener('dragleave', onDragLeave);
    node.addEventListener('drop', handleDrop);
    return () => {
      node.removeEventListener('dragover', onDragOver);
      node.removeEventListener('dragleave', onDragLeave);
      node.removeEventListener('drop', handleDrop);
    };
  }, [handleDrop]);

  // Hook the click-to-pick input — owner attaches via `inputRef`. We listen
  // for change events so the parent doesn't have to wire its own handler.
  useEffect(() => {
    const input = inputRef.current;
    if (!input) return;
    const onChange = (event: Event) => {
      const target = event.target as HTMLInputElement;
      if (target.files?.length) ingest(Array.from(target.files));
      // Allow re-picking the same folder.
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
