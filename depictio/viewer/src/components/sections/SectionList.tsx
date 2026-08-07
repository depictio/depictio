/** The section list for one namespace (filter panel or dashboard grid). */
import React, { useState } from 'react';
import {
  Alert,
  Button,
  Group,
  Modal,
  Radio,
  Select,
  Stack,
  Text,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import type { DashboardData, FilterSectionSpec } from 'depictio-react-core';

import SectionForm from './SectionForm';
import SectionRow from './SectionRow';
import type { SectionKind, SectionOp } from './sectionMutations';
import { memberCounts, sectionsFor } from './sectionMutations';

const OTHER: Record<SectionKind, SectionKind> = { filter: 'grid', grid: 'filter' };

export interface SectionListProps {
  kind: SectionKind;
  dashboard: DashboardData;
  onOp: (op: SectionOp) => void;
}

const SectionList: React.FC<SectionListProps> = ({ kind, dashboard, onOp }) => {
  /** null = nothing being edited, '' = the create form, otherwise a section name. */
  const [editing, setEditing] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<FilterSectionSpec | null>(null);
  const [deleteMode, setDeleteMode] = useState<'unsectioned' | 'move'>('unsectioned');
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  const specs = sectionsFor(dashboard, kind);
  const counts = memberCounts(dashboard, kind);
  const otherNames = new Set(sectionsFor(dashboard, OTHER[kind]).map((s) => s.name));

  const namesExcept = (self?: string) =>
    specs.filter((s) => s.name !== self).map((s) => s.name.toLowerCase());

  const startDelete = (spec: FilterSectionSpec) => {
    const count = counts.get(spec.name) ?? 0;
    if (count === 0) {
      // Nothing to reassign, so nothing to confirm.
      onOp({ op: 'delete', kind, name: spec.name, target: null });
      return;
    }
    setDeleteMode('unsectioned');
    setDeleteTarget(null);
    setDeleting(spec);
  };

  const confirmDelete = () => {
    if (!deleting) return;
    onOp({
      op: 'delete',
      kind,
      name: deleting.name,
      target: deleteMode === 'move' ? deleteTarget : null,
    });
    setDeleting(null);
  };

  const deletingCount = deleting ? counts.get(deleting.name) ?? 0 : 0;
  const moveTargets = deleting
    ? specs.filter((s) => s.name !== deleting.name).map((s) => ({ value: s.name, label: s.name }))
    : [];

  return (
    <Stack gap="sm">
      {specs.length === 0 && editing === null && (
        <Alert variant="light" color="gray" icon={<Icon icon="mdi:information-outline" />}>
          No sections yet. Add one, then move components into it from the component&apos;s ⋮
          menu or while editing it.
        </Alert>
      )}

      {specs.map((spec, i) =>
        editing === spec.name ? (
          <SectionForm
            key={spec.name}
            initial={spec}
            taken={namesExcept(spec.name)}
            onCancel={() => setEditing(null)}
            onSubmit={(next) => {
              // One op, keyed on the section's *current* name: `patch.name`
              // carries the rename and the reducer retargets the members.
              onOp({ op: 'update', kind, name: spec.name, patch: next });
              setEditing(null);
            }}
          />
        ) : (
          <SectionRow
            key={spec.name}
            spec={spec}
            memberCount={counts.get(spec.name) ?? 0}
            canMoveUp={i > 0}
            canMoveDown={i < specs.length - 1}
            sharedName={otherNames.has(spec.name)}
            onMove={(dir) => onOp({ op: 'move', kind, name: spec.name, dir })}
            onEdit={() => setEditing(spec.name)}
            onDelete={() => startDelete(spec)}
          />
        ),
      )}

      {editing === '' ? (
        <SectionForm
          initial={null}
          taken={namesExcept()}
          onCancel={() => setEditing(null)}
          onSubmit={(spec) => {
            onOp({ op: 'create', kind, spec });
            setEditing(null);
          }}
        />
      ) : (
        <Group>
          <Button
            variant="light"
            leftSection={<Icon icon="mdi:plus" width={14} />}
            onClick={() => setEditing('')}
          >
            Add section
          </Button>
        </Group>
      )}

      <Modal
        opened={deleting !== null}
        onClose={() => setDeleting(null)}
        title={deleting ? `Delete “${deleting.name}”` : ''}
        centered
        radius="md"
      >
        <Stack gap="md">
          <Text size="sm">
            {deletingCount} component{deletingCount === 1 ? ' is' : 's are'} in this section.
            Deleting the section does not delete them.
          </Text>
          <Radio.Group
            value={deleteMode}
            onChange={(v) => setDeleteMode(v as 'unsectioned' | 'move')}
            label="What happens to them"
          >
            <Stack gap="xs" mt="xs">
              <Radio value="unsectioned" label="Leave them unsectioned" />
              {moveTargets.length > 0 && (
                <Radio value="move" label="Move them to another section" />
              )}
            </Stack>
          </Radio.Group>
          {deleteMode === 'move' && (
            <Select
              data={moveTargets}
              placeholder="Pick a section"
              value={deleteTarget}
              onChange={setDeleteTarget}
              comboboxProps={{ withinPortal: false }}
            />
          )}
          <Group justify="flex-end" gap="sm">
            <Button variant="default" onClick={() => setDeleting(null)}>
              Cancel
            </Button>
            <Button
              color="red"
              disabled={deleteMode === 'move' && !deleteTarget}
              onClick={confirmDelete}
            >
              Delete section
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
};

export default SectionList;
