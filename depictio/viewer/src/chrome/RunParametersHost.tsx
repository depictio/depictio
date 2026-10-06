import React, { useEffect, useMemo, useState } from 'react';

import type { DashboardData, OpenRunParametersDetail } from 'depictio-react-core';
import { fetchProject, OPEN_RUN_PARAMETERS_EVENT } from 'depictio-react-core';

import { parseTemplateOrigin } from '../projects/template';
import { groupRunProvenance, readRunProvenance, RunParametersModal } from './DashboardInfoBody';

/**
 * Answers a dashboard's `params:` links: opens the Run parameters dialog the
 * Settings drawer also opens, on the project this dashboard belongs to.
 *
 * Mounted once per app, beside the Settings drawer. The project is fetched on
 * the first request only — most visits never ask.
 */
const RunParametersHost: React.FC<{ dashboard: DashboardData | null }> = ({ dashboard }) => {
  const projectId = (dashboard?.project_id as string | undefined) || null;
  const [request, setRequest] = useState<OpenRunParametersDetail | null>(null);
  // `undefined` until fetched; null when the fetch failed.
  const [origin, setOrigin] = useState<unknown>(undefined);

  useEffect(() => {
    const onOpen = (event: Event) => {
      setRequest((event as CustomEvent<OpenRunParametersDetail>).detail ?? { query: null });
    };
    window.addEventListener(OPEN_RUN_PARAMETERS_EVENT, onOpen);
    return () => window.removeEventListener(OPEN_RUN_PARAMETERS_EVENT, onOpen);
  }, []);

  useEffect(() => {
    setOrigin(undefined);
  }, [projectId]);

  useEffect(() => {
    if (!request || !projectId || origin !== undefined) return;
    let cancelled = false;
    fetchProject(projectId, { skipEnrichment: true })
      .then(({ project }) => {
        if (!cancelled) setOrigin((project as { template_origin?: unknown }).template_origin ?? null);
      })
      .catch(() => {
        if (!cancelled) setOrigin(null);
      });
    return () => {
      cancelled = true;
    };
  }, [request, projectId, origin]);

  const { groups, files, template } = useMemo(() => {
    const { entries, files: f } = readRunProvenance(origin ?? null);
    return {
      groups: groupRunProvenance(entries),
      files: f,
      template: parseTemplateOrigin(origin ?? null),
    };
  }, [origin]);

  return (
    <RunParametersModal
      // A fresh card per request, so its search opens on this link's query.
      key={request ? `open:${request.query ?? ''}` : 'closed'}
      opened={request !== null && origin !== undefined}
      onClose={() => setRequest(null)}
      template={template}
      groups={groups}
      files={files}
      initialQuery={request?.query ?? ''}
    />
  );
};

export default RunParametersHost;
