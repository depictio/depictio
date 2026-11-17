/**
 * What the server builds (`GET /projects/builder/capabilities`), read once
 * per page load in both modes. Every gated control reads it from here: the
 * collection types (unavailable ones disabled with their reason), table
 * formats, reader options, link targets, realtime, the genomic tracks
 * assemblies and formats, the bioimage formats.
 *
 * Until the answer arrives, or when there is none (an older server), the page
 * behaves as the v1 builder (`fallbackBuilderCapabilities`).
 */
import React, { createContext, useContext, useEffect, useMemo, useState } from 'react';

import { builderCapabilities, fallbackBuilderCapabilities } from 'depictio-react-core';
import type { BuilderCapabilities } from 'depictio-react-core';

import { useBuilderMode } from './BuilderModeContext';

export interface BuilderCapabilitiesValue {
  /** The server's answer; null while loading or when it could not say. */
  reported: BuilderCapabilities | null;
  /** What the page goes by: the answer, else the v1 fallback. */
  capabilities: BuilderCapabilities;
  status: 'loading' | 'ready' | 'error';
}

const BuilderCapabilitiesContext = createContext<BuilderCapabilitiesValue>({
  reported: null,
  capabilities: fallbackBuilderCapabilities('server'),
  status: 'loading',
});

export const BuilderCapabilitiesProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const mode = useBuilderMode();
  const [reported, setReported] = useState<BuilderCapabilities | null>(null);
  const [status, setStatus] = useState<BuilderCapabilitiesValue['status']>('loading');

  useEffect(() => {
    const controller = new AbortController();
    builderCapabilities({ signal: controller.signal })
      .then((caps) => {
        if (controller.signal.aborted) return;
        setReported(caps);
        setStatus('ready');
      })
      .catch(() => {
        if (!controller.signal.aborted) setStatus('error');
      });
    return () => controller.abort();
  }, []);

  const value = useMemo<BuilderCapabilitiesValue>(
    () => ({ reported, capabilities: reported ?? fallbackBuilderCapabilities(mode), status }),
    [reported, mode, status],
  );
  return <BuilderCapabilitiesContext.Provider value={value}>{children}</BuilderCapabilitiesContext.Provider>;
};

export function useBuilderCapabilities(): BuilderCapabilitiesValue {
  return useContext(BuilderCapabilitiesContext);
}
