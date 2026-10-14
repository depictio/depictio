/**
 * The builder's mode for every component below the page: which create flow
 * applies (`from_run` in server mode, `/plan` + `/write` standalone) and
 * whether the root can be picked at all.
 */
import React, { createContext, useContext } from 'react';

import type { BuilderMode } from './mode';

const BuilderModeContext = createContext<BuilderMode>('server');

export const BuilderModeProvider: React.FC<{ mode: BuilderMode; children: React.ReactNode }> = ({
  mode,
  children,
}) => <BuilderModeContext.Provider value={mode}>{children}</BuilderModeContext.Provider>;

export function useBuilderMode(): BuilderMode {
  return useContext(BuilderModeContext);
}
