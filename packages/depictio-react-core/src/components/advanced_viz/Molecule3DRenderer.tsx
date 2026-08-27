import React, { useEffect, useRef, useState } from 'react';
import {
  Center,
  SegmentedControl,
  Select,
  Stack,
  Text,
  useMantineColorScheme,
} from '@mantine/core';

import { fetchStructureFile, InteractiveFilter, StoredMetadata } from '../../api';
import AdvancedVizFrame from './AdvancedVizFrame';
import { useWebglSlot } from '../../webglBudget';
import type { ColorMode, Representation, StructureViewer } from './molecule/viewer';

interface Molecule3DConfig {
  structure_wf_id: string;
  structure_dc_id: string;
  representation?: Representation;
  color_mode?: ColorMode;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: Molecule3DConfig };
  /** Unused — molecule_3d has no tabular payload; accepted for dispatch uniformity. */
  filters: InteractiveFilter[];
  refreshTick?: number;
}

const REPRESENTATIONS: Array<{ value: Representation; label: string }> = [
  { value: 'cartoon', label: 'Cartoon' },
  { value: 'trace', label: 'Trace' },
  { value: 'stick', label: 'Stick' },
  { value: 'sphere', label: 'Sphere' },
];

const COLOR_MODES: Array<{ value: ColorMode; label: string }> = [
  { value: 'spectrum', label: 'Spectrum (N→C)' },
  { value: 'chain', label: 'Chain' },
  { value: 'plddt', label: 'pLDDT (B-factor)' },
];

/** mmCIF files open with a `data_` block (or bare `_category.item` loops);
 *  everything else is treated as PDB. The DC's `format` field is authoritative
 *  server-side, but the raw text is all the renderer receives. */
function sniffFormat(text: string): 'pdb' | 'mmcif' {
  const head = text.slice(0, 2000).trimStart();
  return head.startsWith('data_') || head.startsWith('_') ? 'mmcif' : 'pdb';
}

/**
 * 3D molecular structure renderer (viz_kind "molecule_3d") — 3Dmol.js behind
 * the StructureViewer adapter in ./molecule/viewer.ts.
 *
 * WebGL budget: one slot is requested via useWebglSlot. Unlike the scatter3d
 * path (which draws anyway when it misses a slot), a denied molecule tile
 * renders a placeholder and never instantiates the viewer, so no uncounted
 * GL context is ever created.
 */
const Molecule3DRenderer: React.FC<Props> = ({ metadata, refreshTick }) => {
  const { colorScheme } = useMantineColorScheme();
  const isDark = colorScheme === 'dark';
  const config = (metadata.config || {}) as Molecule3DConfig;

  const glGranted = useWebglSlot(true);

  // ---- Tier-2 (intra-viz) controls ----------------------------------------
  const [representation, setRepresentation] = useState<Representation>(
    config.representation ?? 'cartoon',
  );
  const [colorMode, setColorMode] = useState<ColorMode>(config.color_mode ?? 'spectrum');

  // ---- Data fetching ------------------------------------------------------
  const [structureText, setStructureText] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!config.structure_dc_id) {
      setError('Molecule 3D: missing structure DC binding');
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchStructureFile(config.structure_dc_id)
      .then((text) => {
        if (!cancelled) setStructureText(text);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [config.structure_dc_id, refreshTick]);

  // ---- Viewer lifecycle ----------------------------------------------------
  const hostRef = useRef<HTMLDivElement | null>(null);
  const viewerRef = useRef<StructureViewer | null>(null);
  const [viewerReady, setViewerReady] = useState(false);

  // Create once we hold a GL slot and have both a host node and data; tear
  // down when the slot is lost so the context is actually released.
  useEffect(() => {
    if (!glGranted || !structureText) return;
    const host = hostRef.current;
    if (!host) return;
    let disposed = false;
    import('./molecule/viewer').then(({ createStructureViewer }) =>
      createStructureViewer(host, { dark: isDark }).then((viewer) => {
        if (disposed) {
          viewer.dispose();
          return;
        }
        viewerRef.current = viewer;
        viewer.setModels(
          [{ id: 'main', data: structureText, format: sniffFormat(structureText) }],
          true,
        );
        setViewerReady(true);
        // Screenshot hook: signals "structure drawn" to headless capture
        // (wait_for_plotly_drawn only watches .plotly-graph-div).
        host.dataset.moleculeReady = 'true';
      }),
    );
    return () => {
      disposed = true;
      setViewerReady(false);
      if (hostRef.current) delete hostRef.current.dataset.moleculeReady;
      viewerRef.current?.dispose();
      viewerRef.current = null;
    };
    // isDark is applied live via setDark below — not a recreate trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [glGranted, structureText]);

  useEffect(() => {
    if (viewerReady) viewerRef.current?.setDark(isDark);
  }, [isDark, viewerReady]);

  useEffect(() => {
    if (viewerReady) viewerRef.current?.setRepresentation(representation);
  }, [representation, viewerReady]);

  useEffect(() => {
    if (viewerReady) viewerRef.current?.setColorMode(colorMode);
  }, [colorMode, viewerReady]);

  // The tile owns geometry — forward container resizes to the canvas.
  useEffect(() => {
    const host = hostRef.current;
    if (!host || !viewerReady) return;
    const ro = new ResizeObserver(() => viewerRef.current?.resize());
    ro.observe(host);
    return () => ro.disconnect();
  }, [viewerReady]);

  // ---- Controls (Settings popover) ----------------------------------------
  const controls = (
    <Stack gap="xs">
      <div>
        <Text size="xs" fw={500} mb={4}>
          Representation
        </Text>
        <SegmentedControl
          size="xs"
          fullWidth
          value={representation}
          onChange={(v) => setRepresentation(v as Representation)}
          data={REPRESENTATIONS}
        />
      </div>
      <Select
        size="xs"
        label="Color by"
        value={colorMode}
        onChange={(v) => v && setColorMode(v as ColorMode)}
        data={COLOR_MODES}
        allowDeselect={false}
      />
    </Stack>
  );

  return (
    <AdvancedVizFrame
      title={metadata.title || '3D structure'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      controls={controls}
      loading={loading}
      error={error}
      emptyMessage={
        !loading && !error && structureText != null && structureText.trim() === ''
          ? 'Empty structure file'
          : undefined
      }
    >
      {glGranted ? (
        <div
          ref={hostRef}
          style={{ position: 'relative', width: '100%', height: '100%', minHeight: 240 }}
        />
      ) : (
        <Center h="100%" mih={240}>
          <Stack gap={4} align="center">
            <Text size="sm" c="dimmed" fw={500}>
              3D viewer paused
            </Text>
            <Text size="xs" c="dimmed" ta="center">
              The WebGL context budget is exhausted — close or scroll past another GL-heavy tile
              to activate this viewer.
            </Text>
          </Stack>
        </Center>
      )}
    </AdvancedVizFrame>
  );
};

export default Molecule3DRenderer;
