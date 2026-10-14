/**
 * Workflow engines and catalogs the builder offers, and their brand marks
 * (served from `public/logos/workflows/`).
 */
import React from 'react';
import { Icon } from '@iconify/react';

import type { BuilderCatalogName } from 'depictio-react-core';

const LOGO = (name: string) => `${import.meta.env.BASE_URL}logos/workflows/${name}`;

const ENGINE_LOGOS: Record<string, string> = {
  nextflow: LOGO('nextflow.png'),
  snakemake: LOGO('snakemake.svg'),
  galaxy: LOGO('galaxy.png'),
  python: LOGO('python.svg'),
  r: LOGO('r.svg'),
};

const CATALOG_LOGOS: Record<string, string> = {
  'nf-core': LOGO('nf-core.png'),
  'smk-wf-catalog': LOGO('snakemake.svg'),
  iwc: LOGO('iwc.png'),
};

/** Canonical lowercase values paired with official-cased labels, the
 *  convention of `dashboards/lib/workflowIcons.ts`. `python` is the default
 *  for a plain data folder. */
export const ENGINE_OPTIONS: { value: string; label: string }[] = [
  { value: 'python', label: 'Python' },
  { value: 'r', label: 'R' },
  { value: 'nextflow', label: 'Nextflow' },
  { value: 'snakemake', label: 'Snakemake' },
  { value: 'galaxy', label: 'Galaxy' },
];

export const CATALOG_OPTIONS: { value: BuilderCatalogName; label: string }[] = [
  { value: 'nf-core', label: 'nf-core' },
  { value: 'workflowhub', label: 'WorkflowHub' },
  { value: 'smk-wf-catalog', label: 'Snakemake workflow catalog' },
];

/** Official-cased label for an engine (the raw value for one not listed). */
export function engineLabel(engine?: string | null): string {
  return ENGINE_OPTIONS.find((o) => o.value === engine?.toLowerCase())?.label || engine || '';
}

/** A workflow's mark: the catalog's (nf-core...) wins over the engine's; a
 *  generic glyph when neither has one. */
export const WorkflowLogo: React.FC<{
  engine?: string | null;
  catalog?: string | null;
  size?: number;
}> = ({ engine, catalog, size = 16 }) => {
  const src = (catalog && CATALOG_LOGOS[catalog]) || (engine && ENGINE_LOGOS[engine.toLowerCase()]);
  if (src) {
    return (
      <img
        src={src}
        alt={catalog || engine || 'workflow'}
        width={size}
        height={size}
        style={{ objectFit: 'contain', display: 'block', flexShrink: 0 }}
      />
    );
  }
  return (
    <Icon
      icon="mdi:sitemap-outline"
      width={size}
      color="var(--mantine-color-dimmed)"
      style={{ flexShrink: 0 }}
    />
  );
};
