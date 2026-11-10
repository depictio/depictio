/**
 * The location field shared by the "From a folder or bucket" and "Add a run"
 * dialogs: a path or `s3://` location, a Browse button opening the folder
 * browser, and the private bucket section for a bucket the server cannot read
 * on its own. It wires `FolderBrowserModal`, `PrivateBucketSection` and the
 * `privateBucket.ts` helpers the way `fromRun/RunFolderTab.tsx` does, without
 * the run tab's template detection.
 *
 * The hook holds the state; the dialog renders `field` (input, Browse, bucket
 * section) and `browser` (the folder browser), and reads `target`, the
 * location after typing paused, to decide what to fetch.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Anchor, Box, Button, Group, TextInput } from '@mantine/core';
import { Icon } from '@iconify/react';

import {
  EMPTY_RUN_STORAGE_FIELDS,
  isPrivateBucketRefusal,
  isLocalFolderPath,
  isS3Location,
  runStorageFieldErrors,
  runStorageFromFields,
  s3BucketOf,
  storageForLocation,
} from 'depictio-react-core';
import type { RunStorageBinding, RunStorageIn } from 'depictio-react-core';

import { useAuthMode } from '../../../auth/hooks/useAuthMode';
import { useCurrentUser } from '../../../hooks/useCurrentUser';
import FolderBrowserModal from '../../fromRun/browser/FolderBrowserModal';
import {
  closeSection,
  followBucket,
  NO_PRIVATE_BUCKET,
  offerSection,
  openSection,
} from '../../fromRun/privateBucket';
import type { OpenPrivateBucketOptions, PrivateBucketState } from '../../fromRun/privateBucket';
import { PrivateBucketSection } from '../../fromRun/PrivateBucketSection';

/** How long typing pauses before the location is read. */
export const READ_DELAY_MS = 450;

/** The server has no credentials of its own for an admin-configured bucket:
 *  the user's keys would not help, the administrator has to fix it. */
export const SERVER_CREDENTIALS_MISSING = 's3_server_credentials_missing';

/** A refusal's text for the user: the server's message, and for a bucket the
 *  server itself cannot read, who can fix it. */
export function refusalText(message: string, code: string | null | undefined): string {
  return code === SERVER_CREDENTIALS_MISSING
    ? `${message.trim()} Ask the administrator of this server.`
    : message;
}

export interface LocationPicker {
  /** The input's value. */
  location: string;
  trimmed: string;
  /** `trimmed`, once typing paused (at once for a folder picked in the browser). */
  target: string;
  /** The server cannot read `trimmed` (not an s3:// location, nor a local path
   *  where the server allows them). */
  invalid: boolean;
  /** Bumped when the location should be read again with other connection details. */
  epoch: number;
  /** The private bucket's details when they apply to `location`, else null. */
  storageFor: (location: string) => RunStorageIn | null;
  /** Why the details typed in the bucket section cannot be sent yet. */
  storageProblem: string | null;
  /** The server refused to read `location` with `code`. Opens the section
   *  asking for the bucket's credentials only for a code that means the user's
   *  credentials are needed (never `cannot_attach` or
   *  `s3_server_credentials_missing`, which no key can fix). */
  noteRefusal: (location: string, code: string | null | undefined) => void;
  /** Whether the bucket section is available to this caller. */
  bucketDisabledReason: string | null;
  field: React.ReactNode;
  browser: React.ReactNode;
}

interface Options {
  opened: boolean;
  /** Named for screen readers: the box around the field titles it. */
  label: string;
  description?: string;
  placeholder?: string;
  /** Prefix of the data-testids: `<prefix>-input`, `<prefix>-browse`. */
  testIdPrefix: string;
}

export function useLocationPicker({
  opened,
  label,
  description,
  placeholder,
  testIdPrefix,
}: Options): LocationPicker {
  const { user, localDataRootsEnabled, remoteBrowseEnabled } = useCurrentUser();
  const { status: authStatus, loading: authLoading } = useAuthMode();
  // Mirrored server-side: private bucket details are refused to non-admins
  // in public mode. Fail closed while the auth status loads.
  const restricted = (authLoading || Boolean(authStatus?.is_public_mode)) && !user?.is_admin;
  const bucketDisabledReason = restricted
    ? 'Private buckets are disabled in public/demo mode for non-admin users.'
    : null;

  const [location, setLocation] = useState('');
  const [target, setTarget] = useState('');
  const [browseOpened, setBrowseOpened] = useState(false);
  const [privateBucket, setPrivateBucket] = useState<PrivateBucketState>(NO_PRIVATE_BUCKET);
  const [epoch, setEpoch] = useState(0);
  const [browseBinding, setBrowseBinding] = useState<RunStorageBinding | null>(null);
  const [browseEpoch, setBrowseEpoch] = useState(0);

  useEffect(() => {
    if (!opened) return;
    setLocation('');
    setTarget('');
    setBrowseOpened(false);
    setPrivateBucket(NO_PRIVATE_BUCKET);
    setBrowseBinding(null);
  }, [opened]);

  const trimmed = location.trim();
  useEffect(() => {
    const timer = window.setTimeout(() => setTarget(trimmed), READ_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [trimmed]);

  const invalid =
    trimmed.length > 0 && !(isS3Location(trimmed) || (localDataRootsEnabled && isLocalFolderPath(trimmed)));

  const rootBucket = s3BucketOf(trimmed);
  const fieldErrors = useMemo(
    () => runStorageFieldErrors(privateBucket.fields),
    [privateBucket.fields],
  );
  const storageProblem = Object.values(fieldErrors)[0] ?? null;
  const binding = useMemo<RunStorageBinding | null>(() => {
    if (bucketDisabledReason || !privateBucket.open || !privateBucket.bucket) return null;
    if (storageProblem) return null;
    const storage = runStorageFromFields(privateBucket.fields);
    return storage ? { bucket: privateBucket.bucket, storage } : null;
  }, [bucketDisabledReason, privateBucket, storageProblem]);
  const bindingRef = useRef(binding);
  bindingRef.current = binding;
  const storageFor = useCallback(
    (loc: string) => storageForLocation(loc, bindingRef.current),
    [],
  );
  const ownStorage = storageForLocation(trimmed, binding);
  const browseEnabled = localDataRootsEnabled || remoteBrowseEnabled || Boolean(ownStorage);

  const openBucket = useCallback((loc: string, options: OpenPrivateBucketOptions) => {
    const bucket = s3BucketOf(loc);
    if (bucket) setPrivateBucket((prev) => openSection(prev, bucket, options));
  }, []);
  const noteRefusal = useCallback(
    (loc: string, code: string | null | undefined) => {
      if (isPrivateBucketRefusal(code)) openBucket(loc, { refused: true });
    },
    [openBucket],
  );

  const toggleBucket = (open: boolean, loc: string) => {
    if (open) {
      openBucket(loc, { byReader: true });
      return;
    }
    if (ownStorage) setEpoch((n) => n + 1);
    setPrivateBucket(closeSection);
  };

  useEffect(() => {
    setBrowseBinding((prev) =>
      prev && (!privateBucket.open || prev.bucket !== privateBucket.bucket) ? null : prev,
    );
  }, [privateBucket.open, privateBucket.bucket]);
  useEffect(() => {
    if (browseEpoch > 0) setBrowseBinding(bindingRef.current);
  }, [browseEpoch]);

  const targetBucket = s3BucketOf(target);
  useEffect(() => {
    if (targetBucket) setPrivateBucket((prev) => followBucket(prev, targetBucket));
  }, [targetBucket]);

  const renderBucket = (loc: string, inBrowser: boolean) => {
    const bucket = s3BucketOf(loc);
    if (!bucket) return null;
    const mine = !inBrowser || privateBucket.bucket === bucket;
    // In the field the credentials show only once the server refused the read
    // for lack of them, the reader asked for them, or details are filled in.
    // Otherwise a small link offers them: most buckets are read by the server.
    if (!inBrowser && !privateBucket.open) {
      if (bucketDisabledReason) return null;
      return (
        <Anchor
          component="button"
          type="button"
          size="xs"
          onClick={() => openBucket(loc, { byReader: true })}
          style={{ alignSelf: 'flex-start' }}
          data-testid="use-own-credentials"
        >
          Use my own credentials
        </Anchor>
      );
    }
    return (
      <PrivateBucketSection
        location={loc}
        bucket={inBrowser ? bucket : privateBucket.bucket ?? bucket}
        open={mine && privateBucket.open}
        refused={mine ? privateBucket.refused : true}
        onOpenChange={(open) => toggleBucket(open, loc)}
        fields={mine ? privateBucket.fields : EMPTY_RUN_STORAGE_FIELDS}
        onFieldsChange={(fields) => setPrivateBucket((prev) => ({ ...prev, fields }))}
        fieldErrors={mine ? fieldErrors : {}}
        onRegionDetected={(region) =>
          setPrivateBucket((prev) => ({ ...prev, fields: { ...prev.fields, region } }))
        }
        onConnected={() => {
          if (bucket === rootBucket) setEpoch((n) => n + 1);
          if (inBrowser) setBrowseEpoch((n) => n + 1);
        }}
        disabledReason={bucketDisabledReason}
      />
    );
  };

  const openBrowser = () => {
    const own = binding && (!rootBucket || binding.bucket === rootBucket);
    setBrowseBinding(own ? binding : null);
    setBrowseOpened(true);
  };
  const closeBrowser = () => {
    setBrowseOpened(false);
    if (rootBucket) setPrivateBucket((prev) => followBucket(prev, rootBucket));
  };

  const rootError = invalid
    ? localDataRootsEnabled
      ? 'Enter a full folder path, a path starting with ~/, or an s3:// location.'
      : 'Enter an s3:// location.'
    : undefined;

  const field = (
    <>
      <TextInput
        aria-label={label}
        description={description}
        placeholder={placeholder ?? (localDataRootsEnabled ? '~/data/survey' : 's3://bucket/folder/')}
        value={location}
        onChange={(e) => setLocation(e.currentTarget.value)}
        leftSection={<Icon icon="mdi:folder-search-outline" width={16} />}
        error={rootError}
        spellCheck={false}
        inputContainer={(input) =>
          browseEnabled ? (
            <Group gap="xs" wrap="nowrap" align="flex-start">
              <Box style={{ flex: 1, minWidth: 0 }}>{input}</Box>
              <Button
                variant="default"
                leftSection={<Icon icon="mdi:folder-open-outline" width={16} />}
                onClick={openBrowser}
                data-testid={`${testIdPrefix}-browse`}
              >
                Browse
              </Button>
            </Group>
          ) : (
            input
          )
        }
        data-testid={`${testIdPrefix}-input`}
      />
      {renderBucket(trimmed, false)}
    </>
  );

  const browser = (
    <FolderBrowserModal
      opened={opened && browseOpened}
      onClose={closeBrowser}
      onSelect={(path) => {
        const bucket = s3BucketOf(path);
        if (bucket) setPrivateBucket((prev) => followBucket(prev, bucket));
        setLocation(path);
        setTarget(path.trim());
        if (storageForLocation(path, binding)) setEpoch((n) => n + 1);
        setBrowseOpened(false);
      }}
      initialLocation={trimmed}
      localEnabled={localDataRootsEnabled}
      s3Enabled={remoteBrowseEnabled}
      privateBucket={browseBinding}
      credentialsForm={(loc) => renderBucket(loc, true)}
      onCredentialsNeeded={(loc) => {
        const bucket = s3BucketOf(loc);
        if (bucket) setPrivateBucket((prev) => offerSection(prev, bucket));
      }}
      templates={[]}
    />
  );

  return {
    location,
    trimmed,
    target,
    invalid,
    epoch,
    storageFor,
    storageProblem: privateBucket.open && privateBucket.bucket === rootBucket ? storageProblem : null,
    noteRefusal,
    bucketDisabledReason,
    field,
    browser,
  };
}
