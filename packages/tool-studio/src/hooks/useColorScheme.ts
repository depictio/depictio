import { useMantineColorScheme } from '@mantine/core';

/**
 * Thin wrapper over Mantine's color-scheme hook. Tool Studio is a separate
 * origin from the depictio SPA so it can't share the `theme-store` localStorage
 * key at runtime, but Mantine's own persistence (localStorageColorSchemeManager
 * default key `mantine-color-scheme-value`) keeps the choice sticky across
 * reloads. Exposes a simple `toggle` for the header ActionIcon.
 */
export function useColorScheme() {
  const { colorScheme, setColorScheme } = useMantineColorScheme();
  const resolved = colorScheme === 'auto' ? 'light' : colorScheme;
  const toggle = () => setColorScheme(resolved === 'dark' ? 'light' : 'dark');
  return { colorScheme: resolved, toggle, setColorScheme };
}
