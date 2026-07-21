/**
 * Per-type design surface. Reuses depictio's real builder controls in the
 * depictio `DesignShell` (form left | preview right):
 *  - figure  → FigureBuilderLocal (depictio FigureUIMode + client Plotly preview / Pyodide code mode);
 *  - card    → depictio CardBuilder wholesale (its CardPreview is backend-less);
 *  - table   → TableDesign (depictio's display/columns form + client ag-grid preview);
 *  - interactive → InteractiveDesign (depictio's full form + client control preview);
 *  - advanced_viz → catalog-studio roles panel (depictio's builder is server-only).
 */
import { Alert, Badge, Select, Stack } from '@mantine/core';
import { Icon } from '@iconify/react';
import DesignShell from 'depictio-builder/shared/DesignShell';
import CardBuilder from 'depictio-builder/card/CardBuilder';
import type { ComponentType } from 'depictio-builder/store/useBuilderStore';
import type { KindsMap, ParsedFixture, RenderSpec } from '../types';
import VizPreview from '../viz/VizPreview';
import FigureBuilderLocal from './FigureBuilderLocal';
import InteractiveDesign from './InteractiveDesign';
import TableDesign from './TableDesign';

// ── advanced_viz: roles panel (catalog-studio owned) ────────────────────────
function AdvancedVizForm({
  fixture,
  kinds,
  draft,
  setDraft,
}: {
  fixture: ParsedFixture;
  kinds: KindsMap;
  draft: { kind: string; roles: Record<string, string> };
  setDraft: (d: { kind: string; roles: Record<string, string> }) => void;
}) {
  const kindEntries = Object.entries(kinds).sort((a, b) => a[0].localeCompare(b[0]));
  const desc = kinds[draft.kind];
  const colOptions = [{ value: '', label: '— none —' }, ...fixture.columns.map((c) => ({ value: c.name, label: c.name }))];

  return (
    <Stack gap="xs">
      <Select
        label="Advanced visualization"
        data={kindEntries.map(([kind, d]) => ({ value: kind, label: d.heavy ? `${d.label} (heavy)` : d.label }))}
        value={draft.kind || null}
        searchable
        onChange={(v) => v && setDraft({ kind: v, roles: {} })}
        placeholder="Choose a kind…"
      />
      {desc?.heavy && (
        <Badge color="orange" variant="light">
          heavy — preview only in depictio
        </Badge>
      )}
      {desc &&
        Object.keys(desc.roles).map((role) => (
          <ColumnSelectForRole
            key={role}
            role={role}
            required={desc.required_roles.includes(role)}
            dtypes={desc.roles[role]}
            options={colOptions}
            value={draft.roles[role] ?? ''}
            onChange={(v) => {
              const roles = { ...draft.roles };
              if (v) roles[role] = v;
              else delete roles[role];
              setDraft({ kind: draft.kind, roles });
            }}
          />
        ))}
    </Stack>
  );
}

function ColumnSelectForRole({
  role,
  required,
  dtypes,
  options,
  value,
  onChange,
}: {
  role: string;
  required: boolean;
  dtypes: string[];
  options: { value: string; label: string }[];
  value: string;
  onChange: (v: string | null) => void;
}) {
  return (
    <Select
      label={role}
      withAsterisk={required}
      description={dtypes.join(' / ')}
      data={options}
      value={value}
      searchable
      onChange={onChange}
    />
  );
}

export interface AdvancedDraft {
  kind: string;
  roles: Record<string, string>;
}

export default function DesignArea({
  fixture,
  type,
  kinds,
  advancedDraft,
  setAdvancedDraft,
}: {
  fixture: ParsedFixture;
  type: ComponentType;
  kinds: KindsMap;
  advancedDraft: AdvancedDraft;
  setAdvancedDraft: (d: AdvancedDraft) => void;
}) {
  if (type === 'figure') {
    // FigureBuilderLocal owns depictio's preview-left / controls-right layout.
    return <FigureBuilderLocal fixture={fixture} />;
  }
  if (type === 'card') {
    // CardBuilder renders its own DesignShell + backend-less CardPreview.
    return <CardBuilder />;
  }
  if (type === 'table') {
    return <TableDesign fixture={fixture} />;
  }
  if (type === 'interactive') {
    return <InteractiveDesign fixture={fixture} />;
  }
  // advanced_viz
  const draftRender: RenderSpec = {
    uid: 'preview',
    component: 'advanced_viz',
    kind: advancedDraft.kind,
    roles: advancedDraft.roles,
  };
  return (
    <DesignShell
      hideColumns
      formSlot={<AdvancedVizForm fixture={fixture} kinds={kinds} draft={advancedDraft} setDraft={setAdvancedDraft} />}
      previewSlot={
        advancedDraft.kind ? (
          <VizPreview fixture={fixture} render={draftRender} kinds={kinds} height={340} />
        ) : (
          <Alert color="gray" variant="light" icon={<Icon icon="mdi:chart-scatter-plot" />}>
            Choose an advanced visualization to preview.
          </Alert>
        )
      }
    />
  );
}
