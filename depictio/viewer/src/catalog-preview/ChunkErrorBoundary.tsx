import React from 'react';
import { Alert, Button } from '@mantine/core';

/** True for the errors a failed dynamic `import()` throws (a hashed chunk that
 *  vanished after `latest/` was republished, or a network failure on it). */
export function isChunkLoadError(err: unknown): boolean {
  const e = err as { name?: string; message?: string } | null;
  if (!e) return false;
  if (e.name === 'ChunkLoadError') return true;
  return /Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module|Loading chunk [^ ]+ failed|Unable to preload CSS/i.test(
    String(e.message ?? err),
  );
}

/** Wraps React.lazy subtrees: a chunk-load failure shows a "reload" alert
 *  instead of unmounting the app; any other error is re-thrown to the parent. */
export class ChunkErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { error: unknown; failed: boolean }
> {
  state: { error: unknown; failed: boolean } = { error: null, failed: false };

  static getDerivedStateFromError(error: unknown) {
    return { error, failed: true };
  }

  render() {
    if (this.state.failed) {
      // Not a chunk failure: re-throw so the enclosing boundary handles it.
      if (!isChunkLoadError(this.state.error)) throw this.state.error;
      return (
        <Alert color="yellow" variant="light" title="The catalog was updated, reload the page">
          A part of this page could not be loaded because a newer version was published.
          <div>
            <Button size="xs" mt="xs" variant="light" color="yellow" onClick={() => location.reload()}>
              Reload
            </Button>
          </div>
        </Alert>
      );
    }
    return this.props.children;
  }
}

export default ChunkErrorBoundary;
