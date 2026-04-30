/**
 * URL parsing for the editor SPA. Single source of truth for all routes
 * served by /dashboard-beta-edit/. Plain regex — no router lib.
 */

export type EditorRoute =
  | { kind: 'editor'; dashboardId: string }
  | { kind: 'create'; dashboardId: string; newComponentId: string }
  | { kind: 'edit'; dashboardId: string; componentId: string };

const CREATE_RE =
  /^\/dashboard-beta-edit\/([^/]+)\/component\/add\/([^/?#]+)/;
const EDIT_RE =
  /^\/dashboard-beta-edit\/([^/]+)\/component\/edit\/([^/?#]+)/;
const EDITOR_RE = /^\/dashboard-beta-edit\/([^/?#]+)/;

export function matchEditorRoute(pathname: string): EditorRoute | null {
  const create = pathname.match(CREATE_RE);
  if (create) {
    return {
      kind: 'create',
      dashboardId: create[1],
      newComponentId: create[2],
    };
  }
  const edit = pathname.match(EDIT_RE);
  if (edit) {
    return {
      kind: 'edit',
      dashboardId: edit[1],
      componentId: edit[2],
    };
  }
  const editor = pathname.match(EDITOR_RE);
  if (editor) {
    return { kind: 'editor', dashboardId: editor[1] };
  }
  return null;
}
