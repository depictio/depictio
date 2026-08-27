/**
 * The one place a section is created or edited.
 *
 * Add and edit are the same fields, so they are the same modal: only the
 * heading, the submit label and whether the namespace is a choice differ. It
 * carries the app's modal chrome (centred accent icon + title, Cancel on the
 * left of a coloured primary), so a section reads like a tab or a dashboard
 * rather than like a form that grew inside a list.
 *
 * Reached from the header's Add menu, from the "…" on a section's own header,
 * and from the Sections manager. When it came from the manager it offers the
 * way back, and `SectionsModal` closes while it is open — a modal on top of a
 * modal is not a stack anyone wants to navigate.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Badge, Button, Group, Modal, Stack, Title } from '@mantine/core';
import { Icon } from '@iconify/react';
import type { DashboardData, FilterSectionSpec } from 'depictio-react-core';

import SectionForm from './SectionForm';
import type { SectionKind, SectionOp } from './sectionMutations';
import { sectionsFor } from './sectionMutations';

/** Grape is the sections accent — distinct from the orange of dashboards and
 *  tabs, so the two families of dialog stay tellable apart at a glance. */
export const SECTION_ACCENT = 'grape';

const KIND_LABEL: Record<SectionKind, string> = {
  grid: 'Dashboard grid',
  filter: 'Filter panel',
};
const KIND_ICON: Record<SectionKind, string> = {
  grid: 'mdi:view-grid-outline',
  filter: 'mdi:filter-variant',
};

export interface SectionModalProps {
  opened: boolean;
  /** The section being edited, or null to create one. */
  target: FilterSectionSpec | null;
  /** Namespace of `target`, or the one to preselect when creating. */
  kind: SectionKind;
  dashboard: DashboardData | null;
  onOp: (op: SectionOp) => void;
  onClose: () => void;
  /** Shown as "Manage all sections" when the manager is where this came from
   *  (or simply where the user would go next). Omitted ⇒ no such action. */
  onManageAll?: () => void;
}

const SectionModal: React.FC<SectionModalProps> = ({
  opened,
  target,
  kind,
  dashboard,
  onOp,
  onClose,
  onManageAll,
}) => {
  const editing = target !== null;
  const [draftKind, setDraftKind] = useState<SectionKind>(kind);
  const [spec, setSpec] = useState<FilterSectionSpec | null>(null);

  // The form is remounted per opening (see `key` below), so its state starts
  // from `target` every time; this only has to follow the namespace the caller
  // asked for.
  useEffect(() => {
    if (opened) setDraftKind(kind);
  }, [opened, kind]);

  const taken = dashboard
    ? sectionsFor(dashboard, draftKind)
        .filter((s) => s.name !== target?.name)
        .map((s) => s.name.toLowerCase())
    : [];

  const handleChange = useCallback((next: FilterSectionSpec | null) => setSpec(next), []);

  const submit = () => {
    if (!spec) return;
    if (editing) {
      // One op, keyed on the section's *current* name: `patch.name` carries the
      // rename and the reducer retargets the members.
      onOp({ op: 'update', kind: draftKind, name: target.name, patch: spec });
    } else {
      onOp({ op: 'create', kind: draftKind, spec });
    }
    onClose();
  };

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      withCloseButton
      centered
      // Wide enough for the two-up Icon/Colour row and for the footer to keep
      // "Manage all sections" on the same line as Cancel/Save.
      size="lg"
      radius="md"
      overlayProps={{ blur: 2 }}
    >
      <Stack gap="md">
        <Group justify="center" gap="sm" mb="xs">
          <Icon
            icon={editing ? 'mdi:square-edit-outline' : 'mdi:playlist-plus'}
            width={28}
            height={28}
            color={`var(--mantine-color-${SECTION_ACCENT}-6)`}
          />
          <Title order={3} c={SECTION_ACCENT} m={0}>
            {editing ? 'Edit section' : 'Add section'}
          </Title>
        </Group>

        {/* Editing cannot move a section between namespaces, so the namespace
            is stated rather than offered. */}
        {editing && (
          <Group justify="center" mt={-8}>
            <Badge
              variant="light"
              color={SECTION_ACCENT}
              leftSection={<Icon icon={KIND_ICON[kind]} width={12} />}
            >
              {KIND_LABEL[kind]}
            </Badge>
          </Group>
        )}

        {dashboard && (
          <SectionForm
            // Remount per opening so the fields always start from `target`,
            // and per namespace switch so a duplicate name clears with it.
            key={`${target?.name ?? '__new__'}:${draftKind}:${String(opened)}`}
            initial={target}
            kind={draftKind}
            onKindChange={editing ? undefined : setDraftKind}
            taken={taken}
            onChange={handleChange}
          />
        )}

        <Group justify={onManageAll ? 'space-between' : 'flex-end'} gap="md" mt="sm">
          {onManageAll && (
            <Button
              variant="subtle"
              color="gray"
              radius="md"
              leftSection={<Icon icon="mdi:format-list-group" width={16} />}
              onClick={onManageAll}
            >
              Manage all sections
            </Button>
          )}
          <Group gap="md">
            <Button variant="outline" color="gray" radius="md" onClick={onClose}>
              Cancel
            </Button>
            <Button
              color={SECTION_ACCENT}
              radius="md"
              leftSection={
                <Icon icon={editing ? 'mdi:content-save' : 'mdi:plus'} width={16} />
              }
              onClick={submit}
              disabled={!spec}
              data-testid="section-modal-submit"
            >
              {editing ? 'Save changes' : 'Add section'}
            </Button>
          </Group>
        </Group>
      </Stack>
    </Modal>
  );
};

export default SectionModal;
