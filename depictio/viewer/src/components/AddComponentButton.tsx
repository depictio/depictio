import React from 'react';
import { Button } from '@mantine/core';
import { Icon } from '@iconify/react';

/**
 * Header-bar button that bounces the user to the Dash component-creation
 * stepper. Generates a fresh UUID for the new component up-front so the
 * Dash side has a stable id to write back to.
 */
interface AddComponentButtonProps {
  dashboardId: string;
  disabled?: boolean;
}

const AddComponentButton: React.FC<AddComponentButtonProps> = ({
  dashboardId,
  disabled,
}) => {
  const handleClick = () => {
    const newId =
      typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
    window.location.assign(
      `/dashboard-edit/${dashboardId}/component/add/${newId}`,
    );
  };

  return (
    <Button
      leftSection={<Icon icon="tabler:plus" width={16} />}
      color="blue"
      variant="filled"
      size="sm"
      onClick={handleClick}
      disabled={disabled || !dashboardId}
    >
      Add component
    </Button>
  );
};

export default AddComponentButton;
