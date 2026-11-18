import { useRef, useState } from 'react';
import { Button } from '@mantine/core';
import { Icon } from '@iconify/react';
import { notifications } from '@mantine/notifications';
import { draftFromCatalogFiles, filesFromZip, normalizeDraft, DRAFT_FORMAT } from '../catalog/draft';
import { useStudioStore } from '../state/useStudioStore';

/** Load a catalog entry back in: the Studio's own zip, a tool folder's files
 *  (module.yaml + <output>.yaml + fixture, selected together), or a draft
 *  JSON. Makes an export round-trip, and lets a committed entry be edited. */
export default function ImportEntryButton({ onLoaded, variant = 'default' }: { onLoaded?: () => void; variant?: string }) {
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const loadDraft = useStudioStore((s) => s.loadDraft);

  const handle = async (list: FileList | null) => {
    if (!list?.length) return;
    setBusy(true);
    try {
      const picked = [...list];
      let files: Record<string, string> = {};
      for (const f of picked) {
        if (/\.zip$/i.test(f.name)) Object.assign(files, await filesFromZip(await f.arrayBuffer()));
        else files[f.name] = await f.text();
      }
      const json = Object.entries(files).find(([p]) => /\.json$/i.test(p));
      if (json) {
        loadDraft(normalizeDraft(JSON.parse(json[1])));
        notifications.show({ color: 'accent', message: `Loaded draft (${DRAFT_FORMAT}).` });
      } else {
        const { draft, notes } = draftFromCatalogFiles(files);
        loadDraft(draft);
        notifications.show({
          color: notes.length ? 'yellow' : 'accent',
          autoClose: notes.length ? 12000 : 4000,
          title: `Loaded ${draft.tool.id} / ${draft.output.slug}`,
          message: notes.length ? notes.join(' ') : `${draft.renders.length} visualization(s).`,
        });
      }
      onLoaded?.();
    } catch (e) {
      notifications.show({ color: 'red', autoClose: 10000, title: 'Could not import', message: (e as Error).message });
    } finally {
      setBusy(false);
      if (input.current) input.current.value = '';
    }
  };

  return (
    <>
      <input
        ref={input}
        type="file"
        multiple
        accept=".zip,.yaml,.yml,.csv,.tsv,.txt,.tab,.json,.py"
        style={{ display: 'none' }}
        data-testid="import-input"
        onChange={(e) => void handle(e.currentTarget.files)}
      />
      <Button
        variant={variant}
        loading={busy}
        leftSection={<Icon icon="mdi:folder-open-outline" width={18} />}
        onClick={() => input.current?.click()}
        data-testid="import-entry"
      >
        Import an entry
      </Button>
    </>
  );
}
