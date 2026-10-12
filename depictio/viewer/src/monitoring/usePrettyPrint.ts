import { useSyncExternalStore } from 'react';

/**
 * Whether the monitoring panes pretty print the dicts and JSON in an open row.
 * One switch for every pane, kept in this browser; on unless turned off.
 */
const KEY = 'depictio-monitoring-pretty';
const listeners = new Set<() => void>();

function read(): boolean {
  try {
    return localStorage.getItem(KEY) !== '0';
  } catch {
    return true;
  }
}

let current = read();

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function setPrettyPrint(on: boolean): void {
  current = on;
  try {
    localStorage.setItem(KEY, on ? '1' : '0');
  } catch {
    // Storage blocked: the choice lasts for this page only.
  }
  listeners.forEach((l) => l());
}

export function usePrettyPrint(): [boolean, (on: boolean) => void] {
  const on = useSyncExternalStore(subscribe, () => current, () => current);
  return [on, setPrettyPrint];
}
