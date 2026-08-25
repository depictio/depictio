/**
 * The section list for one namespace (filter panel or dashboard grid).
 *
 * A list and nothing more: reorder, edit, delete. Creating and editing both
 * happen in `SectionModal`, so this raises `onAdd` / `onEdit` rather than
 * growing a second copy of the form inside a row.
 */
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
  Title,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import type { DashboardData, FilterSectionSpec } from 'depictio-react-core';

import SectionRow from './SectionRow';
import { SECTION_ACCENT } from './SectionModal';
import type { SectionKind, SectionOp } from './sectionMutations';
import { memberCounts, sectionsFor } from './sectionMutations';

const OTHER: Record<SectionKind, SectionKind> = { filter: 'grid', grid: 'filter' };

export interface SectionListProps {
  kind: SectionKind;
  dashboard: DashboardData;
  onOp: (op: SectionOp) => void;
  /** Opens `SectionModal` on a new section in this namespace. */
  onAdd: (kind: SectionKind) => void;
  /** Opens `SectionModal` on an existing section. */
  onEdit: (kind: SectionKind, spec: FilterSectionSpec) => void;
}

const SectionList: React.FC<SectionListProps> = ({
  kind,
  dashboard,
  onOp,
  onAdd,
  onEdit,
}) => {
  const [deleting, setDeleting] = useState<FilterSectionSpec | null>(null);
  const [deleteMode, setDeleteMode] = useState<'unsectioned' | 'move'>('unsectioned');
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  const specs = sectionsFor(dashboard, kind);
  const counts = memberCounts(dashboard, kind);
  const otherNames = new Set(sectionsFor(dashboard, OTHER[kind]).map((s) => s.name));

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
      {specs.length === 0 && (
        <Alert variant="light" color="gray" icon={<Icon icon="mdi:information-outline" />}>
          No sections yet. Add one, then move components into it from the component&apos;s ⋮
          menu or while editing it.
        </Alert>
      )}

      {specs.map((spec, i) => (
        <SectionRow
          key={spec.name}
          spec={spec}
          memberCount={counts.get(spec.name) ?? 0}
          canMoveUp={i > 0}
          canMoveDown={i < specs.length - 1}
          sharedName={otherNames.has(spec.name)}
          onMove={(dir) => onOp({ op: 'move', kind, name: spec.name, dir })}
          onEdit={() => onEdit(kind, spec)}
          onDelete={() => startDelete(spec)}
        />
      ))}

      <Group>
        <Button
          variant="light"
          color={SECTION_ACCENT}
          radius="md"
          leftSection={<Icon icon="mdi:plus" width={16} />}
          onClick={() => onAdd(kind)}
        >
          Add section
        </Button>
      </Group>

      <Modal
        opened={deleting !== null}
        onClose={() => setDeleting(null)}
        withCloseButton
        centered
        size="md"
        radius="md"
        overlayProps={{ blur: 2 }}
      >
        <Stack gap="md">
          <Group justify="center" gap="sm" mb="xs">
            <Icon
              icon="mdi:trash-can-outline"
              width={28}
              height={28}
              color="var(--mantine-color-red-6)"
            />
            <Title order={3} c="red" m={0}>
              Delete “{deleting?.name}”
            </Title>
          </Group>
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
          <Group justify="flex-end" gap="md" mt="sm">
            <Button
              variant="outline"
              color="gray"
              radius="md"
              onClick={() => setDeleting(null)}
            >
              Cancel
            </Button>
            <Button
              color="red"
              radius="md"
              leftSection={<Icon icon="mdi:trash-can-outline" width={16} />}
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
