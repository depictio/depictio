/** Workflow-system → brand-logo mapping for the dashboard create/edit modals.
 *
 *  Selecting a workflow system overrides the dashboard's custom icon + color
 *  with the workflow's logo image and brand color. Mirrors the Dash helpers
 *  `get_workflow_icon_mapping()` / `get_workflow_icon_color()` from the
 *  (removed) `depictio/dash/layouts/layouts_toolbox.py`.
 *
 *  Only systems that ship a logo asset are listed — `workflow_system` is a
 *  free-form string on the backend, but the picker offers just the ones we can
 *  render. */

/** Dropdown options. `none` falls back to the custom Iconify icon. */
export const WORKFLOW_SYSTEM_OPTIONS: { value: string; label: string }[] = [
  { value: 'none', label: 'None (Use Custom Icon)' },
  { value: 'nextflow', label: 'Nextflow' },
  { value: 'snakemake', label: 'Snakemake' },
  { value: 'nf-core', label: 'nf-core' },
  { value: 'galaxy', label: 'Galaxy' },
  { value: 'iwc', label: 'IWC (Intergalactic Workflow Commission)' },
];

/** Logo asset path per workflow system. Served by the API at `/assets`
 *  (proxied by the dev viewer, same-origin in prod). */
export const WORKFLOW_ICON_MAP: Record<string, string> = {
  nextflow: '/assets/images/workflows/nextflow.png',
  snakemake: '/assets/images/workflows/snakemake.png',
  'nf-core': '/assets/images/workflows/nf-core.png',
  galaxy: '/assets/images/workflows/galaxy.png',
  iwc: '/assets/images/workflows/iwc.png',
};

/** Mantine brand color per workflow system (Dash's "purple" → `grape`). */
export const WORKFLOW_COLOR_MAP: Record<string, string> = {
  nextflow: 'teal',
  snakemake: 'green',
  'nf-core': 'blue',
  galaxy: 'blue',
  iwc: 'grape',
};

/** True when a workflow system is selected and has a logo (i.e. it overrides
 *  the custom icon/color). */
export function isWorkflowSelected(ws: string | null | undefined): boolean {
  return !!ws && ws !== 'none' && ws in WORKFLOW_ICON_MAP;
}
