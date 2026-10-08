/**
 * Connection settings for a run folder in a private bucket, as the "From a
 * run folder" flow collects them before the project exists.
 *
 * The settings belong to one bucket, the one the run folder's `s3://`
 * location names: they are sent with every read of a location in that bucket
 * and with nothing else. They live in component state only (never in browser
 * storage, a URL or the recent folders) and are stored server-side only when
 * the project is created, as its storage settings.
 *
 * They always include an access key and its secret: a bucket read without
 * credentials is one the server's administrator lists, never one named here.
 */

import type { RunStorageIn } from './api';
import { isS3Location } from './runFolderPaths';

/** The fields of the "Private bucket" form, as typed. */
export interface RunStorageFields {
  /** Empty for Amazon S3. */
  endpointUrl: string;
  /** Empty for the default region; the connection test detects it. */
  region: string;
  accessKeyId: string;
  secretAccessKey: string;
}

export const EMPTY_RUN_STORAGE_FIELDS: RunStorageFields = {
  endpointUrl: '',
  region: '',
  accessKeyId: '',
  secretAccessKey: '',
};

/** The bucket of an `s3://` location; null for anything else, and for an
 *  `s3://` with no bucket yet. */
export function s3BucketOf(location: string): string | null {
  const value = location.trim();
  if (!isS3Location(value)) return null;
  const bucket = value.slice(5).split('/')[0]?.trim() ?? '';
  return bucket || null;
}

/** Server codes saying the bucket cannot be read without its own settings:
 *  not one this server may read (`s3_refused`), or one that refused the
 *  read (`s3_access_denied`). */
const PRIVATE_BUCKET_CODES = new Set(['s3_refused', 's3_access_denied']);

/** True when a read refused with `code` calls for the bucket's connection
 *  settings. */
export function isPrivateBucketRefusal(code: string | null | undefined): boolean {
  return Boolean(code && PRIVATE_BUCKET_CODES.has(code));
}

/** True when no field holds anything but spaces. */
export function runStorageFieldsBlank(fields: RunStorageFields): boolean {
  return (
    !fields.endpointUrl.trim() &&
    !fields.region.trim() &&
    !fields.accessKeyId.trim() &&
    !fields.secretAccessKey.trim()
  );
}

/** The request body for the fields: trimmed, an empty field sent as null.
 *  Null without the access key or without its secret: the server refuses
 *  settings that lack either, so none are sent. */
export function runStorageFromFields(fields: RunStorageFields): RunStorageIn | null {
  const value = (text: string) => text.trim() || null;
  const accessKeyId = value(fields.accessKeyId);
  const secretAccessKey = value(fields.secretAccessKey);
  if (!accessKeyId || !secretAccessKey) return null;
  return {
    endpoint_url: value(fields.endpointUrl),
    region: value(fields.region),
    access_key_id: accessKeyId,
    secret_access_key: secretAccessKey,
  };
}

/** A region the server takes: a plain name (letters, digits, `.`, `-`, `_`),
 *  since with no endpoint it becomes part of the Amazon host name. */
const REGION_NAME = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;

export type RunStorageFieldErrors = Partial<Record<keyof RunStorageFields, string>>;

/** What the server would refuse in the fields, per field, in the words the
 *  form shows. Empty when they can be sent. The access key and its secret
 *  are both required, so empty fields are refused too: check them only
 *  while the section is in use. The first error says what is missing, both
 *  keys at once when neither is given. */
export function runStorageFieldErrors(fields: RunStorageFields): RunStorageFieldErrors {
  const errors: RunStorageFieldErrors = {};
  const endpoint = fields.endpointUrl.trim();
  if (endpoint && !/^https?:\/\/\S+$/i.test(endpoint)) {
    errors.endpointUrl = 'Enter the full address, starting with https://, or leave it empty for Amazon S3.';
  }
  const region = fields.region.trim();
  if (region && !REGION_NAME.test(region)) {
    errors.region = 'The region is a plain name, such as eu-west-1.';
  }
  const key = fields.accessKeyId.trim();
  const secret = fields.secretAccessKey.trim();
  if (!key && !secret) {
    errors.accessKeyId = 'Enter the access key and its secret.';
    errors.secretAccessKey = 'Enter the secret that goes with the access key.';
  } else if (!secret) {
    errors.secretAccessKey = 'Enter the secret that goes with this access key.';
  } else if (!key) {
    errors.accessKeyId = 'Enter the access key this secret goes with.';
  }
  return errors;
}

/** Settings bound to the bucket they were typed in for. */
export interface RunStorageBinding {
  bucket: string;
  storage: RunStorageIn;
}

/** The settings to send with a read of `location`: the bound ones when the
 *  location is in their bucket, else none. */
export function storageForLocation(
  location: string | null | undefined,
  binding: RunStorageBinding | null | undefined,
): RunStorageIn | null {
  if (!binding || !location) return null;
  return s3BucketOf(location) === binding.bucket ? binding.storage : null;
}
