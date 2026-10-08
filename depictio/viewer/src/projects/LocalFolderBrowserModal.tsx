/**
 * Folder picker for the "From a run folder" tab when the server reads run
 * folders from its own disk (`local_data_roots_enabled`, i.e. `depictio local`).
 *
 * It walks the folders the server allows, one level at a time: each row is a
 * sub-folder, fetched only when its parent is opened, and the breadcrumbs lead
 * back up to the allowed root and the list of roots. A folder that holds a
 * pipeline's own records (`pipeline_info/` or `multiqc/`) carries a "run
 * folder" badge, since that is the level the run tab wants.
 *
 * Rendered inside the create dialog's `Modal.Stack`, so it opens above that
 * dialog and Escape closes only this one.
 */
import React, { useEffect, useRef, useState } from 'react';
import {
  Alert,
  Anchor,
  Badge,
  Box,
  Breadcrumbs,
  Button,
  Center,
  Group,
  Loader,
  Modal,
  NavLink,
  ScrollArea,
  Stack,
  Text,
  ThemeIcon,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { listLocalDirs, Z_LAYERS } from 'depictio-react-core';
import type { LocalDirListing } from 'depictio-react-core';

import { DisabledReason, GatedButton } from '../components/settings/SettingsSections';

interface Crumb {
  label: string;
  /** Folder to list; null for the list of allowed roots. */
  path: string | null;
}

/** "All folders", then the allowed root, then every folder between the root
 *  and the one being listed. */
function crumbsOf(listing: LocalDirListing | null): Crumb[] {
  const crumbs: Crumb[] = [{ label: 'All folders', path: null }];
  if (!listing?.path) return crumbs;
  const root = listing.root;
  if (!root || !listing.path.startsWith(root)) {
    crumbs.push({ label: listing.path, path: listing.path });
    return crumbs;
  }
  crumbs.push({ label: root, path: root });
  let current = root.replace(/\/+$/, '');
  for (const segment of listing.path.slice(root.length).split('/').filter(Boolean)) {
    current = `${current}/${segment}`;
    crumbs.push({ label: segment, path: current });
  }
  return crumbs;
}

interface LocalFolderBrowserModalProps {
  opened: boolean;
  onClose: () => void;
  /** Called with the absolute path of the folder the reader picked. */
  onSelect: (path: string) => void;
  /** Folder to open on. Anything but an absolute path (empty, `~/...`, an
   *  `s3://` location) opens on the list of allowed roots, and so does an
   *  absolute path the server refuses. */
  initialPath?: string | null;
  /** Id inside the enclosing `Modal.Stack`. Without one the modal stacks by
   *  z-index alone. */
  stackId?: string;
}

const LocalFolderBrowserModal: React.FC<LocalFolderBrowserModalProps> = ({
  opened,
  onClose,
  onSelect,
  initialPath,
  stackId,
}) => {
  const [listing, setListing] = useState<LocalDirListing | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** `looks_like_run` of every folder seen so far, by path, so the folder
   *  being listed can say whether it is a run folder itself. */
  const [runFolders, setRunFolders] = useState<Record<string, boolean>>({});
  /** Bumped per request: a response that lands after a newer request, or
   *  after the modal closed, is dropped. */
  const requestRef = useRef(0);

  const load = async (path: string | null, fallbackToRoots = false): Promise<void> => {
    const request = ++requestRef.current;
    setLoading(true);
    setError(null);
    try {
      const next = await listLocalDirs(path);
      if (request !== requestRef.current) return;
      setListing(next);
      setRunFolders((seen) => {
        const merged = { ...seen };
        for (const entry of next.entries) merged[entry.path] = entry.looks_like_run;
        return merged;
      });
    } catch (err) {
      if (request !== requestRef.current) return;
      if (fallbackToRoots && path) {
        // The field held a path the server will not list (moved, outside the
        // allowed folders): start from the roots rather than on an error.
        await load(null);
        return;
      }
      setError((err as Error).message || 'This folder could not be listed.');
    } finally {
      if (request === requestRef.current) setLoading(false);
    }
  };

  useEffect(() => {
    if (!opened) {
      requestRef.current += 1;
      return;
    }
    const start = initialPath && initialPath.startsWith('/') ? initialPath : null;
    void load(start, true);
    // Only opening matters: the field cannot change while this modal is on top.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened]);

  const crumbs = crumbsOf(listing);
  const currentPath = listing?.path ?? null;
  const currentIsRun = currentPath ? Boolean(runFolders[currentPath]) : false;
  const selectReason = loading
    ? 'Wait for the folder to load.'
    : currentPath
      ? null
      : 'Open one of the folders first.';

  return (
    <Modal
      stackId={stackId}
      opened={opened}
      onClose={onClose}
      centered
      size="lg"
      zIndex={stackId ? undefined : Z_LAYERS.nestedOverlay}
      overlayProps={{ blur: 3, backgroundOpacity: 0.55 }}
      title={
        <Group gap="xs" wrap="nowrap">
          <Icon icon="mdi:folder-open-outline" width={20} />
          <Text fw={600}>Choose the run folder</Text>
        </Group>
      }
    >
      <Stack gap="sm" data-testid="local-browse-modal">
        <Text size="sm" c="dimmed">
          Folders on this computer that Depictio is allowed to read. Open folders until
          you reach the output folder of one pipeline run, then select it.
        </Text>

        <Group gap="xs" wrap="nowrap" align="center">
          <Breadcrumbs
            separator={<Icon icon="mdi:chevron-right" width={14} />}
            separatorMargin={4}
            style={{ flexWrap: 'wrap', rowGap: 4, minWidth: 0 }}
            data-testid="local-browse-breadcrumbs"
          >
            {crumbs.map((crumb, index) =>
              index === crumbs.length - 1 ? (
                <Text
                  key={crumb.path ?? 'roots'}
                  size="sm"
                  fw={600}
                  ff={crumb.path ? 'monospace' : undefined}
                  style={{ wordBreak: 'break-all' }}
                  aria-current="page"
                >
                  {crumb.label}
                </Text>
              ) : (
                <Anchor
                  key={crumb.path ?? 'roots'}
                  component="button"
                  type="button"
                  size="sm"
                  ff={crumb.path ? 'monospace' : undefined}
                  style={{ wordBreak: 'break-all' }}
                  onClick={() => void load(crumb.path)}
                  disabled={loading}
                  data-testid={`local-browse-crumb-${index}`}
                >
                  {crumb.label}
                </Anchor>
              ),
            )}
          </Breadcrumbs>
          {loading && listing && <Loader size="xs" data-testid="local-browse-loading" />}
        </Group>

        {error && (
          <Alert
            color="red"
            variant="light"
            icon={<Icon icon="mdi:alert-circle-outline" width={18} />}
            title="This folder could not be opened"
            data-testid="local-browse-error"
          >
            {error}
          </Alert>
        )}

        <Box aria-live="polite" aria-busy={loading}>
          {loading && !listing ? (
            <Center mih={160}>
              <Group gap="xs">
                <Loader size="sm" />
                <Text size="sm" c="dimmed">
                  Listing folders...
                </Text>
              </Group>
            </Center>
          ) : listing && listing.entries.length === 0 ? (
            <Group gap="sm" wrap="nowrap" py="md" data-testid="local-browse-empty">
              <ThemeIcon variant="light" color="gray" size="lg" radius="md">
                <Icon icon="mdi:folder-off-outline" width={20} />
              </ThemeIcon>
              <Text size="sm" c="dimmed">
                {currentPath
                  ? 'No sub-folder here. Select this folder, or go back up.'
                  : 'No folder is available to browse on this computer.'}
              </Text>
            </Group>
          ) : (
            listing && (
              <ScrollArea.Autosize mah={360} type="auto" offsetScrollbars>
                <Stack gap={0} data-testid="local-browse-entries">
                  {listing.entries.map((entry) => (
                    <NavLink
                      key={entry.path}
                      component="button"
                      type="button"
                      label={entry.name}
                      description={currentPath ? undefined : entry.path}
                      leftSection={
                        <Icon
                          icon={entry.looks_like_run ? 'mdi:folder-check-outline' : 'mdi:folder-outline'}
                          width={18}
                        />
                      }
                      rightSection={
                        <Group gap={6} wrap="nowrap">
                          {entry.looks_like_run && (
                            <Badge size="xs" variant="light" color="green" radius="sm">
                              run folder
                            </Badge>
                          )}
                          <Icon icon="mdi:chevron-right" width={16} />
                        </Group>
                      }
                      disabled={loading}
                      onClick={() => void load(entry.path)}
                      data-testid={`local-browse-entry-${entry.name}`}
                      data-path={entry.path}
                      data-run-folder={entry.looks_like_run || undefined}
                    />
                  ))}
                </Stack>
              </ScrollArea.Autosize>
            )
          )}
        </Box>

        {listing?.truncated && (
          <Group gap={6} wrap="nowrap" c="dimmed" data-testid="local-browse-truncated">
            <Icon icon="mdi:information-outline" width={14} style={{ flexShrink: 0 }} />
            <Text size="xs" c="dimmed">
              Only the first 500 sub-folders are listed. Type the path in the run folder
              field to reach one further down.
            </Text>
          </Group>
        )}

        <Group justify="space-between" align="flex-start" wrap="nowrap" pt="xs">
          <Stack gap={2} style={{ minWidth: 0 }}>
            {currentPath && (
              <Text
                size="xs"
                ff="monospace"
                style={{ wordBreak: 'break-all' }}
                data-testid="local-browse-current"
              >
                {currentPath}
              </Text>
            )}
            {currentIsRun && (
              <Group gap={6} wrap="nowrap">
                <ThemeIcon variant="light" color="green" size="xs" radius="xl">
                  <Icon icon="mdi:check-circle" width={10} />
                </ThemeIcon>
                <Text size="xs" c="dimmed">
                  This looks like the output folder of a pipeline run.
                </Text>
              </Group>
            )}
            <DisabledReason reason={selectReason} icon="mdi:information-outline" />
          </Stack>
          <Group gap="xs" wrap="nowrap">
            <Button variant="default" onClick={onClose} data-testid="local-browse-cancel">
              Cancel
            </Button>
            <GatedButton
              leftSection={<Icon icon="mdi:folder-check-outline" width={16} />}
              reason={selectReason}
              onClick={() => {
                if (currentPath) onSelect(currentPath);
              }}
              data-testid="local-browse-select"
            >
              Select this folder
            </GatedButton>
          </Group>
        </Group>
      </Stack>
    </Modal>
  );
};

export default LocalFolderBrowserModal;
