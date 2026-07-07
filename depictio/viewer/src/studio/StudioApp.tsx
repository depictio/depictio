/**
 * Depictio Studio — the 3-column shell.
 *
 *   ┌ file tree ┬ data preview + schema + recognition ┬ designer ┐
 *   │           │                                     │ + live   │
 *   │  (pick)   │                                     │  preview │
 *   ├───────────┴──────────── cart + export ──────────┴──────────┤
 *
 * All authoring is service-free: the columns talk to the local `/studio/*` API
 * (backend.ts); the live preview renders through the viewer's real
 * `ComponentRenderer` fed by build_payload (LivePreview.tsx).
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Box, Grid, Group, ScrollArea, Text, Title } from '@mantine/core';
import { Icon } from '@iconify/react';
import * as api from './backend';
import type { PreviewData, RecognizeResult, TreeNode, VizSuggestion } from './backend';
import FileTree from './FileTree';
import DataPanel from './DataPanel';
import Designer from './Designer';
import LivePreview from './LivePreview';
import Cart, { dcTagForFile } from './Cart';
import type { CartItem, VizSpec } from './spec';
import { specLabel } from './spec';

let _cartSeq = 0;

const Column: React.FC<{ title: string; icon: string; children: React.ReactNode }> = ({ title, icon, children }) => (
  <Box style={{ height: '100%', display: 'flex', flexDirection: 'column', borderRight: '1px solid var(--mantine-color-default-border)' }}>
    <Group gap={6} px="sm" py={6} style={{ borderBottom: '1px solid var(--mantine-color-default-border)', flexShrink: 0 }}>
      <Icon icon={icon} width={15} color="var(--mantine-color-dimmed)" />
      <Text size="xs" fw={700} tt="uppercase" c="dimmed">{title}</Text>
    </Group>
    <ScrollArea style={{ flex: 1 }}>{children}</ScrollArea>
  </Box>
);

const StudioApp: React.FC<{ theme: 'light' | 'dark' }> = ({ theme }) => {
  const [tree, setTree] = useState<TreeNode | null>(null);
  const [activeFile, setActiveFile] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [preview, setPreview] = useState<PreviewData | null>(null);
  const [recognize, setRecognize] = useState<RecognizeResult | null>(null);
  const [suggestions, setSuggestions] = useState<VizSuggestion[]>([]);
  const [previewSpec, setPreviewSpec] = useState<VizSpec | null>(null);
  const [cart, setCart] = useState<CartItem[]>([]);

  useEffect(() => {
    api.getTree().then(setTree).catch(() => setTree({ name: '', path: '', type: 'dir', children: [] }));
  }, []);

  const activate = useCallback((path: string) => {
    setActiveFile(path);
    setPreviewSpec(null);
    setPreview(null);
    setRecognize(null);
    setSuggestions([]);
    api.previewData(path).then((pv) => {
      setPreview(pv);
      api.suggest(pv.schema).then((s) => setSuggestions(s.suggestions)).catch(() => {});
    }).catch(() => {});
    api.recognize(path).then(setRecognize).catch(() => {});
  }, []);

  const togglePick = useCallback((path: string) => {
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }, []);

  const addToCart = useCallback((spec: VizSpec) => {
    if (!activeFile) return;
    setPicked((prev) => new Set(prev).add(activeFile));
    setPreviewSpec(spec);
    setCart((prev) => [
      ...prev,
      {
        id: `c${_cartSeq++}`,
        file: activeFile,
        dcTag: dcTagForFile(activeFile),
        label: specLabel(spec),
        spec,
      },
    ]);
  }, [activeFile]);

  const removeFromCart = useCallback((id: string) => setCart((p) => p.filter((i) => i.id !== id)), []);

  return (
    <Box style={{ height: '100vh', display: 'flex', flexDirection: 'column' }}>
      <Group justify="space-between" px="md" py={8} style={{ borderBottom: '1px solid var(--mantine-color-default-border)', flexShrink: 0 }}>
        <Group gap="xs">
          <Icon icon="mdi:palette-swatch" width={20} color="var(--mantine-color-violet-6)" />
          <Title order={5}>Depictio Studio</Title>
          <Text size="xs" c="dimmed">local · service-free authoring</Text>
        </Group>
      </Group>

      <Grid columns={24} gutter={0} style={{ flex: 1, minHeight: 0 }}>
        <Grid.Col span={5} style={{ height: '100%' }}>
          <Column title="Files" icon="mdi:file-tree">
            <FileTree tree={tree} activeFile={activeFile} picked={picked} onActivate={activate} onTogglePick={togglePick} />
          </Column>
        </Grid.Col>
        <Grid.Col span={11} style={{ height: '100%' }}>
          <Column title="Data" icon="mdi:table-eye">
            <DataPanel preview={preview} recognize={recognize} theme={theme} />
          </Column>
        </Grid.Col>
        <Grid.Col span={8} style={{ height: '100%' }}>
          <Column title="Designer" icon="mdi:auto-fix">
            <Designer preview={preview} recognize={recognize} suggestions={suggestions} onPreview={setPreviewSpec} onAdd={addToCart} />
            <Box px="sm" pb="md">
              <Text size="xs" fw={700} tt="uppercase" c="dimmed" mb={4}>Preview</Text>
              <LivePreview file={activeFile} spec={previewSpec} theme={theme} />
            </Box>
          </Column>
        </Grid.Col>
      </Grid>

      <Cart items={cart} onRemove={removeFromCart} />
    </Box>
  );
};

export default StudioApp;
