import { authFetch, fetchProject } from 'depictio-react-core';
import type { ProjectLayoutKind } from '../layout';

/** Treat a project as runs / one run / tables; null goes back to detection.
 *  The update endpoint takes a full Project, so fetch it, change `layout`,
 *  and send the whole document back. */
export async function saveProjectLayout(
  projectId: string,
  layout: ProjectLayoutKind | null,
): Promise<void> {
  const { project } = await fetchProject(projectId, { skipEnrichment: true });
  const res = await authFetch('/depictio/api/v1/projects/update', {
    method: 'PUT',
    body: JSON.stringify({ ...project, layout }),
  });
  if (!res.ok) {
    let detail = '';
    try {
      const body = await res.json();
      detail = typeof body?.detail === 'string' ? body.detail : '';
    } catch {
      /* not JSON */
    }
    throw new Error(detail || `Failed to update project (${res.status})`);
  }
}
