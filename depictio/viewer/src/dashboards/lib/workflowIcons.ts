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

/** Mantine colour per workflow system, matched to the system's own logo so a
 *  badge's colour and its icon read as one thing.
 *
 *  Chosen by sampling each shipped logo's dominant non-grey pixel and taking
 *  the nearest Mantine shade-6 entry in CIELab:
 *    nextflow  #00c090 → teal    snakemake #009060 → teal
 *    nf-core   #18a860 → green   galaxy    #c0a800 → yellow
 *    iwc       #c0a818 → yellow
 *  (nf-core's apple and Galaxy/IWC's gold were previously blue/grape, which
 *  clashed with the logo sitting right next to them.)
 *
 *  `python` has no logo asset, so it is keyed off its official brand blue
 *  (#3776AB) — the badge then carries the identity the icon can't. */
export const WORKFLOW_COLOR_MAP: Record<string, string> = {
  nextflow: 'teal',
  snakemake: 'teal',
  'nf-core': 'green',
  galaxy: 'yellow',
  iwc: 'yellow',
  python: 'blue',
};

/** True when a workflow system is selected and has a logo (i.e. it overrides
 *  the custom icon/color). */
export function isWorkflowSelected(ws: string | null | undefined): boolean {
  return !!ws && ws !== 'none' && ws in WORKFLOW_ICON_MAP;
}
