import type { MantineColorScheme, MantineColorSchemeManager } from '@mantine/core';

/**
 * A colour-scheme manager for a nested MantineProvider that owns no scheme of
 * its own: it reads the app provider's scheme and writes back to it.
 *
 * `forceColorScheme` would keep the nested provider in step with the app, but
 * it also turns the nested `setColorScheme` into a no-op, so a theme toggle
 * rendered inside a dashboard (the static runtime's tab sidebar, a settings
 * field) never reached the app. With this manager the toggle writes through to
 * the app provider, and `follow` pushes every change of the app's scheme
 * (header toggle, `?theme=`, an embed) into the nested one.
 */
export interface SchemeBridge extends MantineColorSchemeManager {
  /** The app's scheme changed: tell the nested provider. */
  follow: (scheme: MantineColorScheme) => void;
}

export function createSchemeBridge(
  read: () => MantineColorScheme,
  write: (scheme: MantineColorScheme) => void,
): SchemeBridge {
  let listener: ((scheme: MantineColorScheme) => void) | null = null;
  return {
    get: () => read(),
    set: (scheme) => {
      if (scheme !== read()) write(scheme);
    },
    subscribe: (onUpdate) => {
      listener = onUpdate;
    },
    unsubscribe: () => {
      listener = null;
    },
    clear: () => {},
    follow: (scheme) => listener?.(scheme),
  };
}
