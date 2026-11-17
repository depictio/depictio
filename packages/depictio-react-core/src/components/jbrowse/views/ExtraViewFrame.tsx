import React, { Suspense, useEffect, useMemo } from 'react';
import { Box, useComputedColorScheme, useMantineTheme } from '@mantine/core';
import { LoadingEllipses, createJBrowseTheme } from '@jbrowse/core/ui';
import { useWidthSetter } from '@jbrowse/core/util';
import { ModalWidget } from '@jbrowse/embedded-core';
import { getEnv } from '@jbrowse/mobx-state-tree';
import { Paper, ScopedCssBaseline, ThemeProvider, createTheme } from '@mui/material';
import { observer } from 'mobx-react';

import { jbrowseThemeFromMantine } from './sessions';

/** MUI renders JBrowse's dialogs and menus in portals on `document.body`;
 *  while the tile is in native fullscreen only the fullscreen element's
 *  subtree is painted, so point every portal at it instead. */
const portalContainer = (): HTMLElement =>
  (document.fullscreenElement as HTMLElement | null) ?? document.body;

const MUI_OVERRIDES = {
  components: {
    MuiModal: { defaultProps: { container: portalContainer } },
    MuiPopper: { defaultProps: { container: portalContainer } },
    MuiPopover: { defaultProps: { container: portalContainer } },
  },
};

/** The JBrowse palette taken from the Mantine theme (light/dark follows the
 *  dashboard). The same mapping as the linear genome view tile. */
export function useExtraViewTheme(): Record<string, unknown> {
  const mantine = useMantineTheme();
  const scheme = useComputedColorScheme('light');
  return useMemo(
    () => jbrowseThemeFromMantine(mantine, scheme === 'dark'),
    [mantine, scheme],
  );
}

/** The slice of a view model the frame drives. */
interface FramedView {
  type: string;
  setWidth: (w: number) => unknown;
  setHeight?: (h: number) => unknown;
}

interface FrameProps {
  /** The session of the root model (`viewState.session`). */
  session: unknown;
  view: FramedView;
  jbTheme: Record<string, unknown>;
  /** Drive the view's own `height` from the box (circular view). The linear
   *  based views size themselves and scroll inside the box instead. */
  fillHeight?: boolean;
}

/**
 * The view without JBrowse's own app chrome: Depictio's modal already frames
 * it. Mirrors `EmbeddedLGV` in `JBrowseRenderer`: a scoped MUI theme, the
 * width reported to the view model, JBrowse's dialogs and its feature-detail
 * modal rendered inside the same theme.
 */
export const ExtraViewFrame = observer(function ExtraViewFrame({
  session,
  view,
  jbTheme,
  fillHeight = false,
}: FrameProps) {
  const sess = session as {
    DialogComponent?: React.ComponentType<Record<string, unknown>>;
    DialogProps?: Record<string, unknown>;
  };
  const { pluginManager } = getEnv(session as Parameters<typeof getEnv>[0]) as {
    pluginManager: {
      getViewType: (t: string) => { ReactComponent: React.ComponentType<Record<string, unknown>> };
    };
  };
  const { ReactComponent } = pluginManager.getViewType(view.type);
  const theme = useMemo(() => createTheme(createJBrowseTheme(jbTheme), MUI_OVERRIDES), [jbTheme]);
  const widthRef = useWidthSetter(view as Parameters<typeof useWidthSetter>[0], '0px');
  const boxRef = React.useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const el = boxRef.current;
    if (!fillHeight || !el || !view.setHeight || typeof ResizeObserver === 'undefined') return;
    const apply = () => {
      if (el.clientHeight > 0) view.setHeight?.(el.clientHeight);
    };
    apply();
    const ro = new ResizeObserver(apply);
    ro.observe(el);
    return () => ro.disconnect();
  }, [fillHeight, view]);

  return (
    <ThemeProvider theme={theme}>
      <Box
        ref={boxRef}
        data-testid="jbrowse-extra-view"
        style={{ height: '100%', minHeight: 0, overflowY: 'auto', overflowX: 'hidden' }}
      >
        <div style={{ all: 'initial', display: 'block' }}>
          <ScopedCssBaseline>
            <Paper
              ref={widthRef as React.RefObject<HTMLDivElement>}
              elevation={0}
              square
              style={{ overflow: 'hidden' }}
            >
              {sess.DialogComponent ? (
                <Suspense fallback={null}>
                  <sess.DialogComponent {...(sess.DialogProps ?? {})} />
                </Suspense>
              ) : null}
              <Suspense fallback={<LoadingEllipses />}>
                <ReactComponent model={view} session={session} />
              </Suspense>
            </Paper>
          </ScopedCssBaseline>
        </div>
      </Box>
      <ModalWidget session={session as Parameters<typeof ModalWidget>[0]['session']} />
    </ThemeProvider>
  );
});
