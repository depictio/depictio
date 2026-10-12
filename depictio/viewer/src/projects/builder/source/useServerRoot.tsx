/**
 * The data root of the server-mode builder: a folder on the server's disk
 * (when it allows local folders) or an `s3://` location, typed or picked in
 * the run-folder wizard's folder browser, with a private bucket's connection
 * details when it needs them.
 *
 * The root is read (`POST /projects/builder/tree`) a moment after typing
 * stops; it becomes the builder's root once that read succeeds. The private
 * bucket follows the rules of the run-folder tab (`privateBucket.ts`): a
 * refusal opens the section, another bucket drops details typed for the
 * previous one, and the details live in this state only.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  apiErrorCode,
  builderTree,
  EMPTY_RUN_STORAGE_FIELDS,
  isLocalFolderPath,
  isPrivateBucketRefusal,
  isS3Location,
  runStorageFieldErrors,
  runStorageFromFields,
  s3BucketOf,
  storageForLocation,
} from 'depictio-react-core';
import type {
  BuilderHandoff,
  BuilderRootSpec,
  BuilderTreeListing,
  RunStorageBinding,
  RunStorageIn,
} from 'depictio-react-core';

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

const READ_DELAY_MS = 450;

export type RootProbe =
  | { status: 'idle' }
  | { status: 'loading'; location: string }
  | { status: 'ready'; location: string; listing: BuilderTreeListing }
  | { status: 'error'; location: string; error: string; code: string | null };

export interface ServerRoot {
  value: string;
  setValue: (value: string) => void;
  trimmed: string;
  /** Why the typed location cannot be read; undefined when it can. */
  inputError: string | undefined;
  probe: RootProbe;
  /** Set once the root was read. */
  rootSpec: BuilderRootSpec | null;
  /** Why the root is not ready to build on; null when it is. */
  notReadyReason: string | null;
  /** What to say beside a read refused for want of the bucket's details. */
  refusalHint: string | null;
  browseEnabled: boolean;
  openBrowser: () => void;
  /** The private bucket section under the field. */
  privateBucket: React.ReactNode;
  /** The folder browser (a modal). */
  browser: React.ReactNode;
  /** A listing refused later (in the file tree). */
  onRefused: (code: string | null) => void;
}

function isReadableRoot(location: string, localEnabled: boolean): boolean {
  return isS3Location(location) || (localEnabled && isLocalFolderPath(location));
}

function fieldsFromStorage(storage: RunStorageIn | null) {
  if (!storage) return EMPTY_RUN_STORAGE_FIELDS;
  return {
    endpointUrl: storage.endpoint_url ?? '',
    region: storage.region ?? '',
    accessKeyId: storage.access_key_id ?? '',
    secretAccessKey: storage.secret_access_key ?? '',
  };
}

function initialBucket(handoff: BuilderHandoff | null): PrivateBucketState {
  const bucket = handoff ? s3BucketOf(handoff.dataRoot) : null;
  if (!handoff?.storage || !bucket) return NO_PRIVATE_BUCKET;
  return { ...NO_PRIVATE_BUCKET, bucket, open: true, fields: fieldsFromStorage(handoff.storage) };
}

export function useServerRoot(options: {
  localDataRootsEnabled: boolean;
  remoteBrowseEnabled: boolean;
  privateBucketDisabledReason: string | null;
  handoff: BuilderHandoff | null;
}): ServerRoot {
  const { localDataRootsEnabled, remoteBrowseEnabled, privateBucketDisabledReason, handoff } = options;
  const [value, setValueRaw] = useState(handoff?.dataRoot ?? '');
  const [target, setTarget] = useState(handoff?.dataRoot ?? '');
  const [probe, setProbe] = useState<RootProbe>({ status: 'idle' });
  const [privateBucket, setPrivateBucket] = useState<PrivateBucketState>(() => initialBucket(handoff));
  const [storageEpoch, setStorageEpoch] = useState(0);
  const [browseOpened, setBrowseOpened] = useState(false);
  const [browseBinding, setBrowseBinding] = useState<RunStorageBinding | null>(null);
  const [browseEpoch, setBrowseEpoch] = useState(0);

  const trimmed = value.trim();
  const invalid = trimmed.length > 0 && !isReadableRoot(trimmed, localDataRootsEnabled);

  useEffect(() => {
    const timer = window.setTimeout(() => setTarget(trimmed), READ_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [trimmed]);

  const rootBucket = s3BucketOf(trimmed);
  const fieldErrors = useMemo(() => runStorageFieldErrors(privateBucket.fields), [privateBucket.fields]);
  const storageProblem = Object.values(fieldErrors)[0] ?? null;
  const storageBinding = useMemo<RunStorageBinding | null>(() => {
    if (privateBucketDisabledReason || !privateBucket.open || !privateBucket.bucket) return null;
    if (storageProblem) return null;
    const storage = runStorageFromFields(privateBucket.fields);
    return storage ? { bucket: privateBucket.bucket, storage } : null;
  }, [privateBucketDisabledReason, privateBucket, storageProblem]);
  const storageBindingRef = useRef(storageBinding);
  storageBindingRef.current = storageBinding;
  const rootStorage = storageForLocation(trimmed, storageBinding);
  const browseEnabled = localDataRootsEnabled || remoteBrowseEnabled || Boolean(rootStorage);

  const openPrivateBucket = useCallback((location: string, opts: OpenPrivateBucketOptions) => {
    const bucket = s3BucketOf(location);
    if (bucket) setPrivateBucket((prev) => openSection(prev, bucket, opts));
  }, []);

  const targetBucket = s3BucketOf(target);
  useEffect(() => {
    if (targetBucket) setPrivateBucket((prev) => followBucket(prev, targetBucket));
  }, [targetBucket]);

  useEffect(() => {
    setBrowseBinding((prev) =>
      prev && (!privateBucket.open || prev.bucket !== privateBucket.bucket) ? null : prev,
    );
  }, [privateBucket.open, privateBucket.bucket]);

  useEffect(() => {
    if (browseEpoch > 0) setBrowseBinding(storageBindingRef.current);
  }, [browseEpoch]);

  // Read the root's top level: it says the folder exists and can be read.
  useEffect(() => {
    const location = target;
    if (!location || !isReadableRoot(location, localDataRootsEnabled)) {
      setProbe({ status: 'idle' });
      return undefined;
    }
    const controller = new AbortController();
    setProbe({ status: 'loading', location });
    const storage = storageForLocation(location, storageBindingRef.current);
    builderTree({ data_root: location, storage }, '', { signal: controller.signal })
      .then((listing) => {
        if (controller.signal.aborted) return;
        setProbe({ status: 'ready', location, listing });
      })
      .catch((err: Error) => {
        if (controller.signal.aborted) return;
        const code = apiErrorCode(err);
        setProbe({ status: 'error', location, error: err.message || 'This folder could not be read.', code });
        if (isPrivateBucketRefusal(code)) openPrivateBucket(location, { refused: true });
      });
    return () => controller.abort();
    // The connection details are read through a ref (see `storageEpoch`).
  }, [target, localDataRootsEnabled, storageEpoch, openPrivateBucket]);

  const setValue = useCallback((next: string) => setValueRaw(next), []);

  const handleToggle = (open: boolean, location: string) => {
    if (open) {
      openPrivateBucket(location, { byReader: true });
      return;
    }
    if (rootStorage) setStorageEpoch((n) => n + 1);
    setPrivateBucket(closeSection);
  };

  const renderPrivateBucket = (location: string, inBrowser: boolean) => {
    const bucket = s3BucketOf(location);
    if (!bucket) return null;
    const mine = !inBrowser || privateBucket.bucket === bucket;
    return (
      <PrivateBucketSection
        location={location}
        bucket={inBrowser ? bucket : privateBucket.bucket ?? bucket}
        open={mine && privateBucket.open}
        refused={mine ? privateBucket.refused : true}
        onOpenChange={(open) => handleToggle(open, location)}
        fields={mine ? privateBucket.fields : EMPTY_RUN_STORAGE_FIELDS}
        onFieldsChange={(fields) => setPrivateBucket((prev) => ({ ...prev, fields }))}
        fieldErrors={mine ? fieldErrors : {}}
        onRegionDetected={(region) =>
          setPrivateBucket((prev) => ({ ...prev, fields: { ...prev.fields, region } }))
        }
        onConnected={() => {
          if (bucket === rootBucket) setStorageEpoch((n) => n + 1);
          if (inBrowser) setBrowseEpoch((n) => n + 1);
        }}
        disabledReason={privateBucketDisabledReason}
      />
    );
  };

  const openBrowser = () => {
    const own = storageBinding && (!rootBucket || storageBinding.bucket === rootBucket);
    setBrowseBinding(own ? storageBinding : null);
    setBrowseOpened(true);
  };

  const closeBrowser = () => {
    setBrowseOpened(false);
    if (rootBucket) setPrivateBucket((prev) => followBucket(prev, rootBucket));
  };

  const browser = browseEnabled ? (
    <FolderBrowserModal
      opened={browseOpened}
      onClose={closeBrowser}
      onSelect={(path) => {
        const bucket = s3BucketOf(path);
        if (bucket) setPrivateBucket((prev) => followBucket(prev, bucket));
        setValueRaw(path);
        setTarget(path.trim());
        if (storageForLocation(path, storageBinding)) setStorageEpoch((n) => n + 1);
        setBrowseOpened(false);
      }}
      initialLocation={trimmed}
      localEnabled={localDataRootsEnabled}
      s3Enabled={remoteBrowseEnabled}
      privateBucket={browseBinding}
      credentialsForm={(location) => renderPrivateBucket(location, true)}
      onCredentialsNeeded={(location) => {
        const bucket = s3BucketOf(location);
        if (bucket) setPrivateBucket((prev) => offerSection(prev, bucket));
      }}
      templates={[]}
    />
  ) : null;

  const ready = probe.status === 'ready' && probe.location === trimmed;
  const storageKey = JSON.stringify(rootStorage);
  const rootSpec = useMemo<BuilderRootSpec | null>(
    () => (ready ? { data_root: trimmed, storage: rootStorage } : null),
    // `rootStorage` is a fresh object per render; its key decides.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [ready, trimmed, storageKey],
  );

  let inputError: string | undefined;
  if (invalid) {
    inputError = localDataRootsEnabled
      ? 'Enter a full folder path, a path starting with ~/, or an s3:// location.'
      : 'The data root must be an s3:// location.';
  }

  let refusalHint: string | null = null;
  if (probe.status === 'error' && isPrivateBucketRefusal(probe.code)) {
    if (privateBucketDisabledReason) {
      refusalHint = 'This bucket is not public, and reading a private bucket is not available to you here.';
    } else if (privateBucket.open) {
      refusalHint = 'This bucket is not public: give its connection details above, then test the connection.';
    } else {
      refusalHint =
        'This bucket is not public: turn on “This bucket needs credentials” above to give its connection details.';
    }
  }

  let notReadyReason: string | null = null;
  if (!trimmed) {
    notReadyReason = browseEnabled ? 'Enter or browse to the folder holding the data.' : 'Enter the location of the data.';
  } else if (invalid) {
    notReadyReason = inputError ?? 'This location cannot be read.';
  } else if (
    !privateBucketDisabledReason &&
    privateBucket.open &&
    privateBucket.bucket === rootBucket &&
    storageProblem
  ) {
    notReadyReason = `Private bucket: ${storageProblem}`;
  } else if (probe.status === 'error' && probe.location === trimmed) {
    notReadyReason = 'The folder could not be read.';
  } else if (!ready) {
    notReadyReason = 'Reading the folder.';
  }

  const onRefused = useCallback(
    (code: string | null) => {
      if (isPrivateBucketRefusal(code)) openPrivateBucket(trimmed, { refused: true });
    },
    [openPrivateBucket, trimmed],
  );

  return {
    value,
    setValue,
    trimmed,
    inputError,
    probe,
    rootSpec,
    notReadyReason,
    refusalHint,
    browseEnabled,
    openBrowser,
    privateBucket: renderPrivateBucket(trimmed, false),
    browser,
    onRefused,
  };
}
