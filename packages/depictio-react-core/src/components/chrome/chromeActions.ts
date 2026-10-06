/**
 * Which actions a component's chrome offers, by component type.
 *
 * Pure, and apart from `ComponentChrome` on purpose: the dashboard Guide lists
 * the actions a tab's components carry, and it must read the same table the
 * chrome draws from without pulling in the chrome's React tree.
 */

export type ChromeAction =
  | 'inspect'
  | 'catalog'
  | 'description'
  | 'metadata'
  | 'fullscreen'
  | 'download'
  | 'reset'
  | 'drag';

/** View-accessible action visibility per component type. Mirrors the
 *  view-accessible subset of `_create_component_buttons` in
 *  `depictio/dash/layouts/edit.py:236-428`. ``reset`` is always last in the
 *  list so the chrome can hide it when ``onResetFilter`` isn't provided. */
export function actionsFor(componentType: string): ChromeAction[] {
  switch (componentType) {
    case 'figure':
    case 'map':
      return ['metadata', 'fullscreen', 'reset'];
    case 'multiqc':
      return ['metadata', 'fullscreen'];
    case 'table':
      return ['metadata', 'fullscreen', 'download', 'reset'];
    case 'interactive':
      return ['metadata', 'reset'];
    case 'advanced_viz':
      // metadata + fullscreen + reset. Download is dropped — advanced viz
      // export is handled by the Settings popover (Newick export for trees,
      // PNG snapshots are out-of-scope for the multi-trace plotly figures).
      // The Settings + Show-data ActionIcons are injected via extraActions
      // from ComponentRenderer's advanced_viz dispatch.
      return ['metadata', 'fullscreen', 'reset'];
    case 'card':
    case 'image':
    case 'jbrowse':
      return ['metadata'];
    case 'text':
      return ['metadata'];
    default:
      return ['metadata'];
  }
}
