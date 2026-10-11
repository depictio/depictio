/**
 * The run tab's "Private bucket" state, and every way it changes.
 *
 * The connection details belong to `bucket` and are sent with reads of that
 * bucket only; they live in the tab's state, never in browser storage, a URL
 * or the recent folders. The rules sit here in one place: a refusal never
 * reopens a section the reader closed, and another bucket in the field drops
 * the details typed for the previous one.
 */
import { EMPTY_RUN_STORAGE_FIELDS, runStorageFieldsBlank } from 'depictio-react-core';
import type { RunStorageFields } from 'depictio-react-core';

export interface PrivateBucketState {
  /** The bucket the section is for. */
  bucket: string | null;
  open: boolean;
  /** Reading the run folder was refused: the bucket is not public. */
  refused: boolean;
  /** The reader closed the section for this bucket: a refusal leaves it
   *  closed (the switch reopens it). */
  dismissed: boolean;
  fields: RunStorageFields;
}

export const NO_PRIVATE_BUCKET: PrivateBucketState = {
  bucket: null,
  open: false,
  refused: false,
  dismissed: false,
  fields: EMPTY_RUN_STORAGE_FIELDS,
};

export interface OpenPrivateBucketOptions {
  /** A read of the bucket was refused. */
  refused?: boolean;
  /** The reader asked for the section (the switch, a button), rather than a
   *  refusal opening it. */
  byReader?: boolean;
}

/** Open the section for `bucket`. A refusal does not reopen a section the
 *  reader closed for that bucket; the reader always can. Details typed for
 *  the same bucket are kept. */
export function openSection(
  prev: PrivateBucketState,
  bucket: string,
  { refused = false, byReader = false }: OpenPrivateBucketOptions,
): PrivateBucketState {
  const same = prev.bucket === bucket;
  if (same && prev.dismissed && !byReader) return { ...prev, refused: prev.refused || refused };
  return {
    bucket,
    open: true,
    refused: refused || (same && prev.refused),
    dismissed: false,
    fields: same ? prev.fields : EMPTY_RUN_STORAGE_FIELDS,
  };
}

/** A read refused in the folder browser: the section opens for `bucket` as
 *  for a refusal in the field, unless details were typed for another bucket.
 *  Those are not dropped by a folder the reader only looked at; the switch
 *  there opens the section for `bucket` on purpose. */
export function offerSection(prev: PrivateBucketState, bucket: string): PrivateBucketState {
  if (prev.bucket && prev.bucket !== bucket && !runStorageFieldsBlank(prev.fields)) return prev;
  return openSection(prev, bucket, { refused: true });
}

/** Close the section: the details are forgotten, the bucket and its refusal
 *  remembered, and the section stays closed until the reader reopens it. */
export function closeSection(prev: PrivateBucketState): PrivateBucketState {
  return { ...NO_PRIVATE_BUCKET, bucket: prev.bucket, refused: prev.refused, dismissed: true };
}

/** Another bucket in the field: details typed for the previous one are
 *  dropped, never sent to this one. An empty section opened on purpose just
 *  follows the field. */
export function followBucket(prev: PrivateBucketState, bucket: string): PrivateBucketState {
  if (!prev.bucket || prev.bucket === bucket) return prev;
  if (prev.open && !prev.refused && runStorageFieldsBlank(prev.fields)) {
    return { ...prev, bucket };
  }
  return NO_PRIVATE_BUCKET;
}
