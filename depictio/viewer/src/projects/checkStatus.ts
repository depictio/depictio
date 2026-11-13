/**
 * How a check's outcome looks, wherever a folder or a run is checked (the
 * Checks table, the "What Depictio found" cards): one icon and one colour per
 * outcome. Only the icon carries the colour; the text next to it stays the
 * page's own, so a colour always means the same outcome.
 */
export type CheckOutcome = 'ok' | 'differs' | 'warn' | 'fail' | 'info' | 'unknown';

export const CHECK_STATUS: Record<CheckOutcome, { icon: string; color: string; label: string }> = {
  ok: { icon: 'mdi:check-circle', color: 'green', label: 'Passes' },
  differs: { icon: 'mdi:approximately-equal', color: 'yellow', label: 'Differs' },
  warn: { icon: 'mdi:alert-circle', color: 'orange', label: 'Needs a look' },
  fail: { icon: 'mdi:close-circle', color: 'red', label: 'Fails' },
  info: { icon: 'mdi:minus-circle-outline', color: 'gray', label: 'Optional, absent' },
  unknown: { icon: 'mdi:help-circle-outline', color: 'gray', label: 'Cannot be checked' },
};
