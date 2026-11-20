/**
 * `localStorage`, for the conveniences a static file remembers (the view a
 * reader left a combined file on, the colour scheme, the rail). A file opened
 * from disk with site data blocked throws on any access: reads come back
 * null and writes are dropped, and the page works the same without them.
 */
export function storageGet(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function storageSet(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* storage blocked: the value is simply not remembered */
  }
}
