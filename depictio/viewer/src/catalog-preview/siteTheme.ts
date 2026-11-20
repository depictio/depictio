/**
 * The catalog site's light/dark theme. `?theme=` wins (the docs' iframe passes
 * it), then the reader's last choice, then the OS setting. The theme is read
 * once at boot and baked into every render, so switching reloads the page.
 */
const KEY = 'depictio-catalog-theme';

type Theme = 'light' | 'dark';

const valid = (v: string | null): v is Theme => v === 'light' || v === 'dark';

export function resolveCatalogTheme(): Theme {
  try {
    const q = new URLSearchParams(window.location.search).get('theme');
    if (valid(q)) return q;
  } catch {
    /* fall through */
  }
  try {
    const stored = window.localStorage.getItem(KEY);
    if (valid(stored)) return stored;
  } catch {
    /* storage blocked */
  }
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

export function currentCatalogTheme(): Theme {
  return document.documentElement.getAttribute('data-mantine-color-scheme') === 'dark'
    ? 'dark'
    : 'light';
}

export function setCatalogTheme(next: Theme): void {
  try {
    window.localStorage.setItem(KEY, next);
  } catch {
    /* storage blocked: the URL still carries it */
  }
  const url = new URL(window.location.href);
  url.searchParams.set('theme', next);
  window.location.replace(url.toString());
}
