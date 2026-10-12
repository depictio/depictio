/**
 * The builder's three steps, shared by both modes: "Source & project",
 * "Data collections" (the workspace) and "Review & create". The mode hands
 * in its source step and its create panel; the draft, its rules and the
 * template live here.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { Box, Button, Group, Modal, Stack, Stepper, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import {
  allBuilderDcs,
  blockingIssues,
  isS3Location,
  toProjectDraft,
  useBrandAccents,
  validateBuilderState,
} from 'depictio-react-core';
import type {
  BuilderAction,
  BuilderRootSpec,
  BuilderState,
  BuilderTemplateResult,
} from 'depictio-react-core';

import { DisabledReason, GatedButton } from '../../components/settings/SettingsSections';
import { ReviewStep } from './review/ReviewStep';
import { useBuilderTemplate } from './review/useBuilderTemplate';
import { Workspace } from './Workspace';

const BORDER = '1px solid var(--mantine-color-default-border)';

export interface CreatePanelArgs {
  template: BuilderTemplateResult | null;
  /** Why there is no template to act on; null when there is one. */
  templateBlocker: string | null;
  /** The first workflow's engine, for the plan's checks. */
  engine: string | null;
}

interface BuilderStepsProps {
  rootSpec: BuilderRootSpec | null;
  /** Why the source step cannot be left yet; null when it can. */
  notReadyReason: string | null;
  state: BuilderState;
  dispatch: React.Dispatch<BuilderAction>;
  onReset: () => void;
  /** The root could not be listed in the workspace. */
  onRootError?: (code: string | null) => void;
  /** Leaving the source step for the workspace. */
  onLeaveSource?: () => void;
  source: (remote: boolean) => React.ReactNode;
  create: (args: CreatePanelArgs) => React.ReactNode;
}

export const BuilderSteps: React.FC<BuilderStepsProps> = ({
  rootSpec,
  notReadyReason,
  state,
  dispatch,
  onReset,
  onRootError,
  onLeaveSource,
  source,
  create,
}) => {
  const accent = useBrandAccents();
  const [step, setStep] = useState(0);
  const [editRequest, setEditRequest] = useState<{ tag: string; nonce: number } | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  /** The workspace stays mounted once opened, hidden on the other steps, so
   *  a collection being edited and the open folders survive a look at the
   *  review. */
  const [workspaceOpened, setWorkspaceOpened] = useState(false);
  const remote = rootSpec ? isS3Location(rootSpec.data_root) : false;
  const dcCount = allBuilderDcs(state).length;

  // The root changed under the later steps (edited, or no longer readable).
  useEffect(() => {
    if (!rootSpec && step > 0) setStep(0);
  }, [rootSpec, step]);

  useEffect(() => {
    if (step === 1) setWorkspaceOpened(true);
  }, [step]);

  const issues = useMemo(() => validateBuilderState(state, { remote }), [state, remote]);
  const blocking = blockingIssues(issues);
  // The template is only asked for on the review step, and only for a draft
  // with no error the page already knows about.
  const draftForTemplate = useMemo(
    () => (step === 2 && blocking.length === 0 ? toProjectDraft(state, { remote }) : null),
    [step, blocking.length, state, remote],
  );
  const template = useBuilderTemplate(draftForTemplate, remote);
  const templateResult = template.status === 'ready' ? template.result : null;
  let templateBlocker: string | null = null;
  if (blocking.length) {
    templateBlocker = `Fix the ${blocking.length === 1 ? 'issue' : `${blocking.length} issues`} listed above first.`;
  } else if (template.status === 'error') {
    templateBlocker = 'The template could not be built.';
  } else if (template.status !== 'ready') {
    templateBlocker = 'Building the template.';
  }

  let nextReason: string | null = null;
  if (step === 0) nextReason = notReadyReason;
  else if (step === 1 && dcCount === 0) nextReason = 'Add a data collection first.';

  const goTo = (target: number) => {
    if (target === 1 && step === 0) onLeaveSource?.();
    setStep(target);
  };

  const editDc = (tag: string) => {
    setEditRequest((prev) => ({ tag, nonce: (prev?.nonce ?? 0) + 1 }));
    setStep(1);
  };

  return (
    <Box style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }} data-testid="project-builder">
      <Box px="md" py="sm" style={{ borderBottom: BORDER }}>
        <Stepper
          active={step}
          onStepClick={(s) => s < step && setStep(s)}
          color={accent.secondary}
          size="sm"
          allowNextStepsSelect={false}
          styles={{ content: { display: 'none' } }}
          data-testid="builder-stepper"
        >
          <Stepper.Step label="Source & project" description="Where the files are" />
          <Stepper.Step label="Data collections" description="Group files under workflows" />
          <Stepper.Step label="Review & create" description="Check, then create" />
        </Stepper>
      </Box>

      {rootSpec && (workspaceOpened || step === 1) && (
        <Box style={{ flex: 1, minHeight: 0, overflow: 'hidden', display: step === 1 ? undefined : 'none' }}>
          <Workspace
            // Another root is another workspace: nothing picked carries over.
            key={rootSpec.data_root}
            root={rootSpec}
            remote={remote}
            state={state}
            dispatch={dispatch}
            onRootError={onRootError}
            onReview={() => setStep(2)}
            editRequest={editRequest}
          />
        </Box>
      )}
      <Box style={{ flex: 1, minHeight: 0, overflow: 'auto', display: step === 1 ? 'none' : undefined }}>
        {step === 0 && source(remote)}
        {step === 2 && rootSpec && (
          <ReviewStep
            state={state}
            dataRoot={rootSpec.data_root}
            remote={remote}
            issues={issues}
            template={template}
            onEditProject={() => setStep(0)}
            onEditDc={editDc}
            createPanel={create({
              template: templateResult,
              templateBlocker,
              engine: state.workflows[0]?.engine ?? null,
            })}
          />
        )}
      </Box>

      <Group justify="space-between" px="md" py="xs" wrap="nowrap" style={{ borderTop: BORDER }}>
        <Group gap="xs" wrap="nowrap">
          <Button
            variant="default"
            onClick={() => setStep((s) => Math.max(0, s - 1))}
            disabled={step === 0}
            data-testid="builder-previous"
          >
            Previous
          </Button>
          <Button
            variant="subtle"
            color="gray"
            leftSection={<Icon icon="mdi:restore" width={16} />}
            onClick={() => setConfirmReset(true)}
            disabled={!rootSpec}
            data-testid="builder-start-over"
          >
            Start over
          </Button>
        </Group>
        {step < 2 && (
          <Group gap="sm" wrap="nowrap" style={{ minWidth: 0 }}>
            <DisabledReason reason={nextReason} icon="mdi:information-outline" testId="builder-next-reason" />
            <GatedButton
              color={accent.secondary}
              rightSection={<Icon icon="mdi:arrow-right" width={16} />}
              onClick={() => goTo(step + 1)}
              reason={nextReason}
              data-testid="builder-next"
            >
              Next
            </GatedButton>
          </Group>
        )}
      </Group>

      <Modal opened={confirmReset} onClose={() => setConfirmReset(false)} title="Start over?" centered>
        <Stack gap="md">
          <Text size="sm">
            Every workflow and data collection of this draft is dropped. The files are not touched.
          </Text>
          <Group justify="flex-end" gap="xs">
            <Button variant="default" onClick={() => setConfirmReset(false)}>
              Keep the draft
            </Button>
            <Button
              color="red"
              onClick={() => {
                onReset();
                setConfirmReset(false);
                setStep(rootSpec ? Math.min(step, 1) : 0);
              }}
              data-testid="builder-start-over-confirm"
            >
              Start over
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Box>
  );
};
