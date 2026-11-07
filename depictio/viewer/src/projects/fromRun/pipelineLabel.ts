/**
 * How the create flow names a pipeline: its id and version
 * ("nf-core/ampliseq 2.16.0"), never the catalog's long title, which stays
 * secondary text.
 */
import { bareVersion, splitTemplateId } from 'depictio-react-core';

/** "nf-core/ampliseq 2.16.0" for a catalog id; the id itself when it names
 *  no version; null without an id. */
export function pipelineLabel(templateId: string | null | undefined): string | null {
  if (!templateId) return null;
  const parts = splitTemplateId(templateId);
  return [parts.pipeline, parts.version ? bareVersion(parts.version) : null]
    .filter(Boolean)
    .join(' ');
}
