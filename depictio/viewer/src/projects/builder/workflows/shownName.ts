import type { BuilderState, BuilderWorkflowState } from 'depictio-react-core';

/** A workflow's name as the project will have it: a template workflow the
 *  reader renamed shows its new name (the draft keeps the shipped one, which
 *  the edits are keyed by). */
export function shownWorkflowName(state: BuilderState, workflow: BuilderWorkflowState): string {
  if (!workflow.fromTemplate) return workflow.name;
  return state.base?.workflows?.[workflow.name]?.name?.trim() || workflow.name;
}
