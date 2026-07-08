/**
 * Per-batch realtime highlight model.
 *
 * A realtime upsert adds a set of rows/images to a data collection. The backend
 * ships the added ids in the event payload (``new_ids`` / ``id_column``); this
 * module turns that into an ``ActiveHighlight`` the renderers consult to glow
 * exactly the rows a batch added.
 *
 * Two lifetimes:
 *   - ``sticky: false`` — a live arrival. Glows for the transient window, then
 *     fades (gated by ``useTransientFlag(nonce)`` in the renderer).
 *   - ``sticky: true`` — the user re-selected a past batch from the event log.
 *     Stays lit until cleared or another batch is chosen.
 */
export interface ActiveHighlight {
  /** DC the batch belongs to — renderers only react when it matches their
   *  ``metadata.dc_id`` (undefined = apply to any DC). */
  dcId?: string;
  /** Column the ids are values of (e.g. ``index_index``) — the DC-wide column
   *  the backend diffed. Renderers match a row by looking up THIS column on the
   *  row (``row[idColumn]``), so a batch only lights up when the column is
   *  present; undefined disables batch matching (legacy diff still applies). */
  idColumn?: string;
  /** The added row ids, as strings. */
  ids: string[];
  /** Bumps on each (re-)trigger so ``useTransientFlag`` re-arms the fade. */
  nonce: number;
  /** ``true`` = pinned until cleared; ``false`` = auto-fade live arrival. */
  sticky: boolean;
  /** Stable key of the source event log entry, used to mark the lit row in the
   *  journal. Undefined for live arrivals not yet pinned. */
  batchKey?: string;
}

/**
 * Extract the batch id-set from an event payload. Returns ``null`` when the
 * payload carries no usable added-id list (very first commit, no id column,
 * or an empty diff). Falls back to ``new_ids_sample`` when the full
 * ``new_ids`` list is absent (older backend / truncated).
 */
export function batchIdsFromPayload(
  payload: Record<string, unknown> | undefined,
): { idColumn?: string; ids: string[] } | null {
  if (!payload) return null;
  const raw = Array.isArray(payload.new_ids)
    ? (payload.new_ids as unknown[])
    : Array.isArray(payload.new_ids_sample)
      ? (payload.new_ids_sample as unknown[])
      : null;
  if (!raw || raw.length === 0) return null;
  const idColumn =
    typeof payload.id_column === 'string' ? (payload.id_column as string) : undefined;
  return { idColumn, ids: raw.map((v) => String(v)) };
}
