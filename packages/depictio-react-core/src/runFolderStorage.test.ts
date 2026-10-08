import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  createProjectFromRun,
  findRunFolders,
  inspectFolder,
  listS3Dirs,
  testRunStorage,
} from './api';
import type { RunStorageIn } from './api';
import {
  EMPTY_RUN_STORAGE_FIELDS,
  isPrivateBucketRefusal,
  runStorageFieldErrors,
  runStorageFieldsBlank,
  runStorageFromFields,
  s3BucketOf,
  storageForLocation,
} from './runFolderStorage';

const STORAGE: RunStorageIn = {
  endpoint_url: 'https://s3.example.org',
  region: null,
  access_key_id: 'AKIAEXAMPLE',
  secret_access_key: 'very-secret',
};

describe('s3BucketOf', () => {
  it('names the bucket of an s3:// location, whatever follows it', () => {
    expect(s3BucketOf('s3://runs/ampliseq/run-42/')).toBe('runs');
    expect(s3BucketOf('  S3://runs ')).toBe('runs');
    expect(s3BucketOf('s3://runs/')).toBe('runs');
  });

  it('is null for a local path and for a bucket not typed yet', () => {
    expect(s3BucketOf('/data/run42')).toBeNull();
    expect(s3BucketOf('~/results')).toBeNull();
    expect(s3BucketOf('s3://')).toBeNull();
    expect(s3BucketOf('')).toBeNull();
  });
});

describe('isPrivateBucketRefusal', () => {
  it('is true for the refusals a bucket of its own settings would lift', () => {
    expect(isPrivateBucketRefusal('s3_refused')).toBe(true);
    expect(isPrivateBucketRefusal('s3_access_denied')).toBe(true);
  });

  it('is false for other failures and for none', () => {
    expect(isPrivateBucketRefusal('s3_unreachable')).toBe(false);
    expect(isPrivateBucketRefusal('template_not_detected')).toBe(false);
    expect(isPrivateBucketRefusal(null)).toBe(false);
  });
});

describe('runStorageFromFields', () => {
  it('is null while every field is empty', () => {
    expect(runStorageFieldsBlank(EMPTY_RUN_STORAGE_FIELDS)).toBe(true);
    expect(runStorageFromFields({ ...EMPTY_RUN_STORAGE_FIELDS, region: '   ' })).toBeNull();
  });

  it('is null without the access key or its secret, whatever else is given', () => {
    const endpoint = { ...EMPTY_RUN_STORAGE_FIELDS, endpointUrl: 'https://s3.example.org' };
    expect(runStorageFieldsBlank(endpoint)).toBe(false);
    expect(runStorageFromFields(endpoint)).toBeNull();
    expect(runStorageFromFields({ ...endpoint, accessKeyId: 'AKIAEXAMPLE' })).toBeNull();
    expect(runStorageFromFields({ ...endpoint, secretAccessKey: 'very-secret' })).toBeNull();
    expect(
      runStorageFromFields({ ...endpoint, accessKeyId: '  ', secretAccessKey: ' \t ' }),
    ).toBeNull();
  });

  it('trims every field and sends an empty one as null', () => {
    expect(
      runStorageFromFields({
        endpointUrl: ' https://s3.example.org ',
        region: '',
        accessKeyId: 'AKIAEXAMPLE ',
        secretAccessKey: ' very-secret',
      }),
    ).toEqual(STORAGE);
  });

  it('sends the endpoint and region as null when left empty (Amazon S3, default region)', () => {
    expect(
      runStorageFromFields({
        ...EMPTY_RUN_STORAGE_FIELDS,
        accessKeyId: 'AKIAEXAMPLE',
        secretAccessKey: 'very-secret',
      }),
    ).toEqual({ ...STORAGE, endpoint_url: null });
  });
});

describe('runStorageFieldErrors', () => {
  it('accepts a key and its secret, with or without an endpoint and region', () => {
    expect(
      runStorageFieldErrors({
        endpointUrl: 'https://s3.example.org',
        region: 'eu-west-1',
        accessKeyId: 'AKIA',
        secretAccessKey: 'secret',
      }),
    ).toEqual({});
    expect(
      runStorageFieldErrors({
        ...EMPTY_RUN_STORAGE_FIELDS,
        accessKeyId: 'AKIA',
        secretAccessKey: 'secret',
      }),
    ).toEqual({});
  });

  it('wants the access key and its secret, and says first that both are missing', () => {
    for (const fields of [
      EMPTY_RUN_STORAGE_FIELDS,
      { ...EMPTY_RUN_STORAGE_FIELDS, endpointUrl: 'https://s3.example.org', region: 'eu-west-1' },
      { ...EMPTY_RUN_STORAGE_FIELDS, accessKeyId: '  ', secretAccessKey: ' ' },
    ]) {
      const errors = runStorageFieldErrors(fields);
      expect(Object.keys(errors)).toEqual(['accessKeyId', 'secretAccessKey']);
      expect(Object.values(errors)[0]).toBe('Enter the access key and its secret.');
    }
  });

  it('says which of the two is missing', () => {
    expect(runStorageFieldErrors({ ...EMPTY_RUN_STORAGE_FIELDS, accessKeyId: 'AKIA' })).toEqual({
      secretAccessKey: 'Enter the secret that goes with this access key.',
    });
    expect(
      runStorageFieldErrors({ ...EMPTY_RUN_STORAGE_FIELDS, secretAccessKey: 'secret' }),
    ).toEqual({ accessKeyId: 'Enter the access key this secret goes with.' });
  });

  it('refuses an endpoint without its scheme and a region that is not a plain name', () => {
    const errors = runStorageFieldErrors({
      endpointUrl: 's3.example.org',
      region: 'eu west 1',
      accessKeyId: 'AKIA',
      secretAccessKey: 'secret',
    });
    expect(Object.keys(errors)).toEqual(['endpointUrl', 'region']);
  });
});

describe('storageForLocation', () => {
  const binding = { bucket: 'runs', storage: STORAGE };

  it('sends the settings with a location in their bucket only', () => {
    expect(storageForLocation('s3://runs/', binding)).toBe(STORAGE);
    expect(storageForLocation('s3://runs/ampliseq/run-42/', binding)).toBe(STORAGE);
    expect(storageForLocation('s3://other/runs/', binding)).toBeNull();
    expect(storageForLocation('s3://runs-2/', binding)).toBeNull();
    expect(storageForLocation('/runs/ampliseq', binding)).toBeNull();
  });

  it('sends nothing without settings or a location', () => {
    expect(storageForLocation('s3://runs/', null)).toBeNull();
    expect(storageForLocation(null, binding)).toBeNull();
  });
});

describe('folder calls with storage settings', () => {
  const calls: Array<{ url: string; init: RequestInit }> = [];

  beforeEach(() => {
    calls.length = 0;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init: RequestInit = {}) => {
        calls.push({ url, init });
        return new Response(JSON.stringify({ entries: [], runs: [] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const only = () => {
    expect(calls).toHaveLength(1);
    const [{ url, init }] = calls;
    return { url, method: init.method ?? 'GET', body: init.body ? JSON.parse(String(init.body)) : null };
  };

  it('read without settings through the GET routes, as before', async () => {
    await inspectFolder('s3://runs/run-42/', { detect: false });
    const call = only();
    expect(call.method).toBe('GET');
    expect(call.url).toContain('/projects/folder_inspect?');
    expect(call.url).toContain('detect=false');
  });

  it('send the settings in a POST body, never in the URL', async () => {
    await inspectFolder('s3://runs/run-42/', { storage: STORAGE });
    let call = only();
    expect(call.method).toBe('POST');
    expect(call.url).toMatch(/\/projects\/folder_inspect$/);
    expect(call.body).toEqual({ location: 's3://runs/run-42/', detect: true, storage: STORAGE });

    calls.length = 0;
    await listS3Dirs('s3://runs/', { storage: STORAGE });
    call = only();
    expect(call.method).toBe('POST');
    expect(call.url).toMatch(/\/projects\/s3_dirs$/);
    expect(call.body).toEqual({ url: 's3://runs/', storage: STORAGE });

    calls.length = 0;
    await findRunFolders('s3://runs/', { storage: STORAGE });
    call = only();
    expect(call.method).toBe('POST');
    expect(call.url).toMatch(/\/projects\/find_runs$/);
    expect(call.body).toEqual({ location: 's3://runs/', storage: STORAGE });

    calls.length = 0;
    await testRunStorage('s3://runs/run-42/', STORAGE);
    call = only();
    expect(call.method).toBe('POST');
    expect(call.url).toMatch(/\/projects\/storage_test$/);
    expect(call.body).toEqual({ location: 's3://runs/run-42/', storage: STORAGE });

    expect(calls.every(({ url }) => !url.includes('very-secret'))).toBe(true);
  });

  it('list the allowed locations through the GET route, settings or not', async () => {
    await listS3Dirs(null, { storage: STORAGE });
    const call = only();
    expect(call.method).toBe('GET');
    expect(call.url).toMatch(/\/projects\/s3_dirs$/);
  });

  it('carry the settings into from_run only when there are some', async () => {
    await createProjectFromRun({ dataRoot: 's3://runs/run-42/', dryRun: true });
    expect(only().body).not.toHaveProperty('storage');

    calls.length = 0;
    await createProjectFromRun({ dataRoot: 's3://runs/run-42/', storage: STORAGE });
    expect(only().body).toMatchObject({ data_root: 's3://runs/run-42/', storage: STORAGE });
  });
});
