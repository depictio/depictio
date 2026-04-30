/**
 * Step 1: pick a workflow + data collection. Mirrors
 * depictio/dash/layouts/stepper_parts/part_one.py.
 *
 * Layout:
 *  - section title "Select Data Source" + description
 *  - "Selected Component:" badge with the type chosen in step 0
 *  - 2-col SimpleGrid: Workflow Select + Data Collection Select
 *  - Data Collection Information card (9-row definition table)
 *  - Data preview table (paginated) for table DCs, alert for multiqc/non-tabular
 */
import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Badge,
  Divider,
  Group,
  Loader,
  Select,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import {
  fetchProjectFromDashboard,
  fetchDeltaShape,
  fetchSpecs,
  fetchDataCollectionConfig,
} from 'depictio-react-core';
import type { WorkflowEntry } from 'depictio-react-core';
import { useBuilderStore } from '../store/useBuilderStore';
import type { ColumnSpec } from '../store/useBuilderStore';
import { getComponentTypeMeta } from '../componentTypes';
import DataCollectionInfoCard from '../data/DataCollectionInfoCard';
import DataPreviewTable from '../data/DataPreviewTable';
import type { DataCollectionInfo } from '../data/DataCollectionInfoCard';

const StepData: React.FC = () => {
  const dashboardId = useBuilderStore((s) => s.dashboardId);
  const wfId = useBuilderStore((s) => s.wfId);
  const dcId = useBuilderStore((s) => s.dcId);
  const dcConfigType = useBuilderStore((s) => s.dcConfigType);
  const componentType = useBuilderStore((s) => s.componentType);
  const setWorkflow = useBuilderStore((s) => s.setWorkflow);
  const setDataCollection = useBuilderStore((s) => s.setDataCollection);
  const setCols = useBuilderStore((s) => s.setCols);

  const [workflows, setWorkflows] = useState<WorkflowEntry[]>([]);
  const [loadingWorkflows, setLoadingWorkflows] = useState(true);
  const [workflowsError, setWorkflowsError] = useState<string | null>(null);

  const [shape, setShape] = useState<{
    num_rows?: number;
    num_columns?: number;
  } | null>(null);
  const [shapeLoading, setShapeLoading] = useState(false);
  const [dcInfo, setDcInfo] = useState<DataCollectionInfo | null>(null);

  // Mirror depictio/models/components/validation.py:COMPONENT_DC_TYPE_MAPPING.
  // Picking a component type narrows the DC dropdown to compatible DC types.
  const allowedDcTypes = useMemo<string[] | null>(() => {
    if (!componentType) return null;
    switch (componentType) {
      case 'figure':
      case 'card':
      case 'interactive':
      case 'table':
        return ['table'];
      case 'map':
        return ['table', 'geojson'];
      case 'multiqc':
        return ['multiqc'];
      case 'image':
        return ['image'];
      default:
        return null;
    }
  }, [componentType]);

  useEffect(() => {
    if (!dashboardId) {
      setLoadingWorkflows(false);
      return;
    }
    setLoadingWorkflows(true);
    fetchProjectFromDashboard(dashboardId)
      .then(({ project }) => {
        const wfs = project.workflows || [];
        setWorkflows(wfs);
        setWorkflowsError(null);
        if (!wfId && wfs.length > 0) {
          // Pick the first workflow that has at least one DC compatible with
          // the chosen componentType, then auto-select that compatible DC.
          // This avoids landing the user on a multiqc DC after picking Card.
          const wfWithDc =
            wfs.find((w) => {
              const dcs = w.data_collections || [];
              return dcs.some((dc) => {
                if (!allowedDcTypes) return true;
                const t = (dc.config?.type as string | undefined)?.toLowerCase();
                return t ? allowedDcTypes.includes(t) : false;
              });
            }) || wfs[0];
          setWorkflow(
            wfWithDc._id,
            (wfWithDc.project_id as string) || (project._id as string) || null,
          );
          const compatDc =
            (wfWithDc.data_collections || []).find((dc) => {
              if (!allowedDcTypes) return true;
              const t = (dc.config?.type as string | undefined)?.toLowerCase();
              return t ? allowedDcTypes.includes(t) : false;
            }) || wfWithDc.data_collections?.[0];
          if (compatDc) {
            setDataCollection(
              compatDc._id,
              (compatDc.config?.type as string) || null,
            );
          }
        }
      })
      .catch((err) => {
        setWorkflows([]);
        setWorkflowsError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => setLoadingWorkflows(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dashboardId]);

  const wfOptions = useMemo(
    () =>
      workflows.map((w) => ({
        value: w._id,
        label: w.workflow_tag || w.name || w._id,
      })),
    [workflows],
  );

  const dcOptions = useMemo(() => {
    const wf = workflows.find((w) => w._id === wfId);
    if (!wf) return [];
    return (wf.data_collections || [])
      .filter((dc) => {
        if (!allowedDcTypes) return true;
        const t = (dc.config?.type as string | undefined)?.toLowerCase();
        return t ? allowedDcTypes.includes(t) : false;
      })
      .map((dc) => ({
        value: dc._id,
        label: dc.data_collection_tag || dc._id,
      }));
  }, [workflows, wfId, allowedDcTypes]);

  // If the currently selected DC is no longer compatible with the component
  // type (e.g. user backed out and changed the type), reset the picker.
  useEffect(() => {
    if (!dcId || !allowedDcTypes) return;
    const wf = workflows.find((w) => w._id === wfId);
    const dc = wf?.data_collections?.find((d) => d._id === dcId);
    const t = (dc?.config?.type as string | undefined)?.toLowerCase();
    if (!t || !allowedDcTypes.includes(t)) {
      setDataCollection(null, null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allowedDcTypes, dcId, wfId, workflows]);

  // After workflows are loaded and the user has chosen a component type, if no
  // DC is selected (either fresh load or just-reset by the effect above), pick
  // the first compatible DC across all workflows.
  useEffect(() => {
    if (dcId || !workflows.length || !allowedDcTypes) return;
    const wf = workflows.find((w) => w._id === wfId) || workflows[0];
    const dc = (wf.data_collections || []).find((d) => {
      const t = (d.config?.type as string | undefined)?.toLowerCase();
      return t ? allowedDcTypes.includes(t) : false;
    });
    if (dc) {
      if (wf._id !== wfId) {
        setWorkflow(
          wf._id,
          (wf.project_id as string) || null,
        );
      }
      setDataCollection(dc._id, (dc.config?.type as string) || null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allowedDcTypes, dcId, workflows]);

  // Re-fetch shape + columns + DC config when DC changes.
  useEffect(() => {
    if (!dcId) {
      setShape(null);
      setCols([]);
      setDcInfo(null);
      return;
    }
    setShapeLoading(true);
    Promise.allSettled([
      fetchDeltaShape(dcId),
      fetchSpecs(dcId),
      fetchDataCollectionConfig(dcId),
    ])
      .then(([shapeR, specsR, cfgR]) => {
        if (shapeR.status === 'fulfilled') setShape(shapeR.value);
        else setShape(null);

        if (specsR.status === 'fulfilled') {
          const specs = specsR.value;
          if (Array.isArray(specs)) {
            setCols(specs as ColumnSpec[]);
          } else if (specs && typeof specs === 'object') {
            const colsList: ColumnSpec[] = Object.entries(
              specs as Record<string, Record<string, unknown>>,
            ).map(([name, info]) => ({
              name,
              type: String(info?.type ?? ''),
              specs: info,
            }));
            setCols(colsList);
          } else {
            setCols([]);
          }
        } else {
          setCols([]);
        }

        if (cfgR.status === 'fulfilled') {
          const cfg = cfgR.value as Record<string, unknown> | null;
          const wf = workflows.find((w) => w._id === wfId);
          const dc = wf?.data_collections?.find((d) => d._id === dcId);
          setDcInfo({
            workflowId: wfId || '',
            dataCollectionId: dcId,
            type: (cfg?.type as string) || dcConfigType || 'unknown',
            metaType: (cfg?.metatype as string) || 'Regular',
            name: (dc?.data_collection_tag as string) || dcId,
            description:
              (cfg?.description as string) ||
              ((dc?.description as string) || ''),
            deltaVersion:
              cfg && typeof cfg === 'object' && 'delta_version' in cfg
                ? String((cfg as Record<string, unknown>).delta_version || 'v1')
                : 'v1',
            numRows:
              shapeR.status === 'fulfilled' ? shapeR.value?.num_rows : null,
            numColumns:
              shapeR.status === 'fulfilled'
                ? shapeR.value?.num_columns
                : null,
          });
        } else {
          // Even if config fetch fails (e.g. multiqc), still display what we know.
          const wf = workflows.find((w) => w._id === wfId);
          const dc = wf?.data_collections?.find((d) => d._id === dcId);
          setDcInfo({
            workflowId: wfId || '',
            dataCollectionId: dcId,
            type: dcConfigType || 'unknown',
            metaType: 'Regular',
            name: (dc?.data_collection_tag as string) || dcId,
            description: (dc?.description as string) || '',
            deltaVersion: 'v1',
            numRows:
              shapeR.status === 'fulfilled' ? shapeR.value?.num_rows : null,
            numColumns:
              shapeR.status === 'fulfilled'
                ? shapeR.value?.num_columns
                : null,
          });
        }
      })
      .finally(() => setShapeLoading(false));
  }, [dcId, wfId, workflows, dcConfigType, setCols]);

  const handleWfChange = (val: string | null) => {
    const wf = workflows.find((w) => w._id === val);
    setWorkflow(val, (wf?.project_id as string) || null);
  };

  const handleDcChange = (val: string | null) => {
    const wf = workflows.find((w) => w._id === wfId);
    const dc = wf?.data_collections?.find((d) => d._id === val);
    const cfgType = (dc?.config?.type as string) || null;
    setDataCollection(val, cfgType);
  };

  const componentMeta = componentType ? getComponentTypeMeta(componentType) : null;

  return (
    <Stack gap="md" pt="md">
      <Stack gap="xs" align="center">
        <Title order={3} ta="center" fw={700}>
          Select Data Source
        </Title>
        <Text size="sm" c="gray" ta="center">
          Choose the workflow and data collection for your component
        </Text>
      </Stack>

      {componentMeta && (
        <Group gap="sm" align="center" mt="xs" mb="xs">
          <Text fw={700} size="md">
            Selected Component:
          </Text>
          <Badge
            size="lg"
            variant="filled"
            color="blue"
            style={{ background: componentMeta.iconBg }}
            leftSection={
              componentMeta.type === 'multiqc' ? null : (
                <Icon icon={componentMeta.icon} width={14} color="white" />
              )
            }
          >
            {componentMeta.label}
          </Badge>
        </Group>
      )}

      <Divider />

      {workflowsError && (
        <Alert color="red" title="Failed to load workflows">
          <Text size="xs">{workflowsError}</Text>
        </Alert>
      )}
      {!loadingWorkflows && !workflowsError && workflows.length === 0 && (
        <Alert color="yellow" title="No workflows available">
          <Text size="sm">
            This dashboard's project has no workflows yet, or you don't have
            access to them.
          </Text>
        </Alert>
      )}

      <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="lg">
        <Select
          label="Workflow"
          placeholder={loadingWorkflows ? 'Loading…' : 'Select workflow...'}
          data={wfOptions}
          value={wfId}
          onChange={handleWfChange}
          searchable
          disabled={loadingWorkflows}
          leftSection={<Icon icon="mdi:source-branch" width={16} />}
        />
        <Select
          label="Data Collection"
          placeholder={
            !wfId ? 'Pick a workflow first' : 'Select data collection...'
          }
          data={dcOptions}
          value={dcId}
          onChange={handleDcChange}
          searchable
          disabled={!wfId}
          leftSection={<Icon icon="mdi:database" width={16} />}
        />
      </SimpleGrid>

      {dcId && (
        <Stack gap="sm" mt="md">
          <Title order={4} fw={700} size="md">
            Data Collection Information
          </Title>
          <Divider />
          {shapeLoading ? (
            <Group p="md">
              <Loader size="sm" />
              <Text size="sm" c="dimmed">
                Loading data collection details…
              </Text>
            </Group>
          ) : (
            dcInfo && <DataCollectionInfoCard info={dcInfo} />
          )}

          <DataPreviewTable
            dcId={dcId}
            dcType={dcConfigType}
            shape={shape}
          />
        </Stack>
      )}
    </Stack>
  );
};

export default StepData;
